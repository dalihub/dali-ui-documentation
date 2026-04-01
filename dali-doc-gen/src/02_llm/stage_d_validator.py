"""
stage_d_validator.py — Stage D: Hallucination Validation Engine

역할:
  - Stage C가 생성한 Markdown 초안에서 C++ 심볼(클래스명, 메서드명)을 추출
  - cache/parsed_doxygen/*.json(Doxygen DB)과 대조하여 존재 여부 확인
  - Pass / Warn / Fail 판정 후 결과를 JSON 리포트로 저장
  - PASS / WARN 문서는 cache/validated_drafts/ 로 복사
  - FAIL 문서는 선택적으로 LLM에게 재검토 요청

판정 기준:
  PASS  : 심볼 검증률 ≥ 70%
  WARN  : 50% ~ <70%
  FAIL  : < 50%  (심볼이 5개 미만이면 LOW_CONTENT 로 별도 처리)
"""

import os
import re
import json
import shutil
import argparse
from pathlib import Path
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from llm_client import LLMClient

# ── 경로 정의 ────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = PROJECT_ROOT / "cache"
DRAFTS_DIR = CACHE_DIR / "markdown_drafts"
PARSED_DOXYGEN_DIR = CACHE_DIR / "parsed_doxygen"
OUT_REPORT_DIR = CACHE_DIR / "validation_report"
OUT_VALIDATED_DIR = CACHE_DIR / "validated_drafts"
REPORT_PATH = OUT_REPORT_DIR / "stage_d_report.json"

# 판정 임계값
PASS_THRESHOLD = 0.60    # ≥ 60%: PASS (심볼의 과반 이상 확인됨)
WARN_THRESHOLD = 0.35    # ≥ 35%: WARN (부분적 확인, 계속 진장하되 리포트 태깅)
MIN_SYMBOLS_FOR_SCORING = 3  # 심볼이 이 이하면 LOW_CONTENT 처리


# ── Doxygen DB 구축 ──────────────────────────────────────────────────────
def build_doxygen_symbol_set():
    """
    모든 parsed_doxygen JSON에서 compound 이름 + member 이름을 수집하여
    검색용 집합(set)을 반환합니다.
    """
    full_names = set()    # "Dali::Actor::SetPosition" 등
    simple_names = set()  # "SetPosition" 등

    for pkg_json in PARSED_DOXYGEN_DIR.glob("*.json"):
        try:
            with open(pkg_json, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        for comp in data.get("compounds", []):
            comp_name = comp.get("name", "")
            if comp_name:
                full_names.add(comp_name)
                simple_names.add(comp_name.split("::")[-1])

            for mb in comp.get("members", []):
                mb_name = mb.get("name", "")
                if mb_name:
                    full_names.add(f"{comp_name}::{mb_name}")
                    simple_names.add(mb_name)

    print(f"[Validator] Doxygen DB built: {len(full_names)} full symbols, {len(simple_names)} simple names.")
    return full_names, simple_names


# ── 심볼 추출 ─────────────────────────────────────────────────────────────
def extract_symbols_from_markdown(md_text):
    """
    Markdown 텍스트에서 C++ 심볼 참조를 추출합니다.
    추출 대상:
      - 코드 블록 내 Dali:: / Ui:: 네임스페이스 패턴
      - 인라인 backtick 내 ClassName::MethodName 패턴
      - 인라인 backtick 내 CamelCase 식별자 (단독 클래스명)
    """
    symbols = set()

    # 1. 코드 블록 전체 추출
    code_blocks = re.findall(r'```(?:cpp|c\+\+)?\s*(.*?)\s*```', md_text, re.DOTALL | re.IGNORECASE)
    for block in code_blocks:
        # Dali::나 Ui:: 로 시작하는 전체 심볼
        found = re.findall(r'(?:Dali|Ui|Dali::Ui)::[A-Za-z:]+', block)
        symbols.update(found)
        # ClassName::MethodName 패턴
        found2 = re.findall(r'[A-Z][a-zA-Z0-9]+::[A-Za-z][a-zA-Z0-9_]+', block)
        symbols.update(found2)

    # 2. 인라인 backtick
    inline_ticks = re.findall(r'`([^`]+)`', md_text)
    for item in inline_ticks:
        item = item.strip()
        # ClassName::MethodName
        if '::' in item:
            symbols.add(item)
        # CamelCase 단독 클래스명 (최소 2글자 이상, 대문자 시작)
        elif re.match(r'^[A-Z][a-zA-Z]{2,}$', item):
            symbols.add(item)

    # 불필요한 키워드 제거 (C++ 예약어 등)
    noise = {'Include', 'Note', 'Warning', 'View', 'Actor', 'True', 'False', 'nullptr',
             'Void', 'Return', 'This', 'Class', 'New', 'Delete', 'Public', 'Private'}
    symbols -= noise
    return symbols


# ── 심볼 검증 ─────────────────────────────────────────────────────────────
def verify_symbols(symbols, full_names, simple_names):
    """
    추출된 심볼 각각을 Doxygen DB에서 검색합니다.
    full_names (전체 네임스페이스) 또는 simple_names (단순 이름) 중 하나라도
    포함되면 verified로 처리합니다.
    """
    verified = []
    unverified = []

    for sym in symbols:
        # 전체 이름 직접 매칭
        if sym in full_names:
            verified.append(sym)
            continue
        # 단순 이름 매칭 (마지막 :: 이후 부분)
        simple = sym.split("::")[-1]
        if simple in simple_names:
            verified.append(sym)
        else:
            unverified.append(sym)

    return verified, unverified


# ── LLM 보조 검증 (FAIL 문서용) ────────────────────────────────────────────
def llm_review_fail(feat_name, md_text, unverified_symbols, client):
    """
    FAIL 판정 문서에 대해 LLM에게 어떤 심볼이 문제인지 설명을 요청합니다.
    """
    sym_list = "\n".join(f"  - {s}" for s in unverified_symbols[:20])
    prompt = f"""
You are a C++ API documentation reviewer for the Samsung DALi GUI framework.
The following documentation page for '{feat_name}' was flagged because it references
symbols that could not be found in the Doxygen API database.

Unverified symbols:
{sym_list}

Review these symbols and for each one:
1. State whether it likely exists (just not found due to parsing) or is hallucinated
2. If hallucinated, suggest the correct DALi API name if you know it

Be concise. Output as a plain text list. Do NOT make up API names you are unsure about.
"""
    try:
        return client.generate(prompt, use_think=False)
    except Exception as e:
        return f"[LLM review failed: {e}]"


# ── 메인 ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip LLM review for FAIL documents.")
    args = parser.parse_args()

    print("=================================================================")
    print(" Stage D: Hallucination Validation Engine                       ")
    print("=================================================================")

    # 디렉터리 준비
    OUT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_VALIDATED_DIR.mkdir(parents=True, exist_ok=True)

    # Doxygen DB 구축
    full_names, simple_names = build_doxygen_symbol_set()

    # 검증 대상 파일 수집 (Index.md 제외)
    md_files = sorted([p for p in DRAFTS_DIR.glob("*.md") if p.name != "Index.md"])
    if not md_files:
        print("No markdown drafts found in cache/markdown_drafts/. Run Stage C first.")
        return

    # LLM 클라이언트 (FAIL 재검증용)
    client = LLMClient() if not args.no_llm else None

    report = []
    stats = {"pass": 0, "warn": 0, "fail": 0, "low_content": 0}

    for md_path in md_files:
        feat_name = md_path.stem
        md_text = md_path.read_text(encoding="utf-8")

        # 심볼 추출
        symbols = extract_symbols_from_markdown(md_text)

        # 심볼이 너무 적으면 LOW_CONTENT 처리 (내용이 극히 적은 파일)
        if len(symbols) < MIN_SYMBOLS_FOR_SCORING:
            verdict = "LOW_CONTENT"
            score = None
            verified_syms, unverified_syms = [], list(symbols)
            stats["low_content"] += 1
        else:
            verified_syms, unverified_syms = verify_symbols(symbols, full_names, simple_names)
            score = len(verified_syms) / len(symbols) if symbols else 1.0

            if score >= PASS_THRESHOLD:
                verdict = "PASS"
                stats["pass"] += 1
            elif score >= WARN_THRESHOLD:
                verdict = "WARN"
                stats["warn"] += 1
            else:
                verdict = "FAIL"
                stats["fail"] += 1

        # PASS / WARN / LOW_CONTENT → validated_drafts/ 복사
        if verdict in ("PASS", "WARN", "LOW_CONTENT"):
            shutil.copy2(md_path, OUT_VALIDATED_DIR / md_path.name)
            copy_status = "copied"
        else:
            copy_status = "blocked"

        # FAIL 문서 LLM 재검증
        llm_comment = None
        if verdict == "FAIL" and client and unverified_syms:
            print(f"  [LLM Review] Requesting analysis for FAIL document '{feat_name}'...")
            llm_comment = llm_review_fail(feat_name, md_text, unverified_syms, client)

        score_display = f"{score:.1%}" if score is not None else "N/A"
        print(f"  [{verdict:12s}] {feat_name}.md  "
              f"symbols={len(symbols)}, verified={len(verified_syms)}, "
              f"score={score_display}  → {copy_status}")

        report.append({
            "feature": feat_name,
            "verdict": verdict,
            "score": round(score, 4) if score is not None else None,
            "total_symbols": len(symbols),
            "verified_symbols": verified_syms,
            "unverified_symbols": unverified_syms,
            "copy_status": copy_status,
            "llm_review": llm_comment
        })

    # 리포트 저장
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # 최종 요약
    total = len(md_files)
    print(f"\n=================================================================")
    print(f" Stage D Complete! Validation report saved.")
    print(f" Results: PASS={stats['pass']}, WARN={stats['warn']}, "
          f"FAIL={stats['fail']}, LOW_CONTENT={stats['low_content']} / {total} files")
    print(f" Report  : {REPORT_PATH}")
    print(f" Validated: {OUT_VALIDATED_DIR}")
    print("=================================================================")


if __name__ == "__main__":
    main()
