"""
stage_d_validator.py — Stage D: Hallucination Validation Engine

역할:
  - Stage C가 생성한 Markdown 초안에서 C++ 심볼(클래스명, 메서드명)을 추출
  - cache/parsed_doxygen/*.json(Doxygen DB)과 대조하여 존재 여부 확인
  - Pass / Warn / Fail 판정 후 결과를 JSON 리포트로 저장
  - PASS / WARN 문서는 cache/validated_drafts/ 로 복사
  - FAIL 문서는 자동으로 프롬프트 수정 후 Stage C 수준으로 재생성 (Retry Loop)
  - Retry 후에도 FAIL이면 최종 FAIL로 확정하고 리포트에 기록

판정 기준:
  PASS  : 심볼 검증률 ≥ 60%
  WARN  : 35% ~ <60%
  FAIL  : < 35%  (심볼이 3개 미만이면 LOW_CONTENT 로 별도 처리)
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

# 판정 임계값
PASS_THRESHOLD = 1.00    # ≥ 100%: PASS (무관용 원칙 적용, 1개라도 거짓 심볼 사용 시 FAIL 처리)
WARN_THRESHOLD = 1.00    # WARN 단계 병합 (100% 미만은 모두 FAIL 취급)
MIN_SYMBOLS_FOR_SCORING = 3  # 심볼이 이 이하면 LOW_CONTENT 처리

# Retry 설정
MAX_RETRY_ATTEMPTS = 2   # FAIL 문서 자동 재생성 최대 횟수
TAXONOMY_PATH = CACHE_DIR / "feature_taxonomy" / "feature_taxonomy.json"



# ── 네임스페이스 Strip 헬퍼 (Phase 3) ──────────────────────────────────────
def _strip_dali_prefix(symbol: str) -> str:
    """
    Dali::Ui::X → X, Dali::X → X 변환.
    'using namespace Dali; using namespace Dali::Ui;' 가정 하에
    짧은 이름으로 검증할 때 사용.
    Dali::Ui:: 를 먼저 처리해야 Dali::Ui::Text::Alignment 가 올바르게 변환된다.
    """
    if symbol.startswith("Dali::Ui::"):
        return symbol[len("Dali::Ui::"):]
    if symbol.startswith("Dali::"):
        return symbol[len("Dali::"):]
    return symbol


def _symbol_aliases(symbol: str) -> list:
    """
    심볼에 대한 검증용 alias 목록을 반환합니다 (원본 제외).
    1. Dali::Ui:: / Dali:: 접두사 strip
    2. ::Type:: 중간 레이어 skip
       ex) LoadPolicy::Type::IMMEDIATE → LoadPolicy::IMMEDIATE
       (DALi의 'struct { struct Type { enum {...}; }; }' 패턴 대응)
    """
    aliases = set()

    stripped = _strip_dali_prefix(symbol)
    if stripped != symbol:
        aliases.add(stripped)

    # ::Type:: skip — strip 전/후 모두 적용
    for s in [symbol, stripped]:
        if "::Type::" in s:
            no_type = s.replace("::Type::", "::")
            aliases.add(no_type)
            # strip + type-skip 조합
            stripped_no_type = _strip_dali_prefix(no_type)
            if stripped_no_type != no_type:
                aliases.add(stripped_no_type)

    aliases.discard(symbol)
    return list(aliases)


# ── 상속 Alias 빌더 ──────────────────────────────────────────────────────
def _build_inheritance_aliases(parsed_doxygen_dir) -> set:
    """
    모든 parsed_doxygen JSON을 읽어 상속 체인을 재귀 탐색하고,
    부모 클래스의 메서드를 자식 클래스 이름으로 alias한 full_names 집합을 반환한다.

    예) Dali::Ui::ImageView → Dali::Ui::View → Dali::Actor
        → "ImageView::Add", "View::Add" 등을 full_names에 추가

    cross-package 상속 대응:
      base_classes에 단축명("CustomActor")이 들어있는 경우
      전체 compounds 맵에서 short name으로도 탐색한다.
    """
    all_comps: dict = {}
    short_to_full: dict = {}

    for pkg_json in Path(parsed_doxygen_dir).glob("*.json"):
        try:
            with open(pkg_json, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        for comp in data.get("compounds", []):
            cn = comp.get("name", "")
            if not cn:
                continue
            all_comps[cn] = comp
            short = cn.split("::")[-1]
            short_to_full.setdefault(short, []).append(cn)

    def resolve_base(base_name: str):
        if base_name in all_comps:
            return all_comps[base_name]
        candidates = short_to_full.get(base_name, [])
        return all_comps[candidates[0]] if candidates else None

    def collect_ancestor_members(class_name: str, visited: set) -> list:
        if class_name in visited:
            return []
        visited.add(class_name)
        comp = resolve_base(class_name)
        if comp is None:
            return []
        members = [mb.get("name", "") for mb in comp.get("members", []) if mb.get("name")]
        for base in comp.get("base_classes", []):
            members.extend(collect_ancestor_members(base, visited))
        return members

    alias_set: set = set()
    for cn, comp in all_comps.items():
        bases = comp.get("base_classes", [])
        if not bases:
            continue
        inherited = []
        for base in bases:
            inherited.extend(collect_ancestor_members(base, set()))
        short_cn = _strip_dali_prefix(cn)
        for mn in inherited:
            if mn.startswith("~") or mn.startswith("operator") or not mn:
                continue
            full_sym = f"{cn}::{mn}"
            short_sym = f"{short_cn}::{mn}"
            alias_set.add(full_sym)
            alias_set.add(short_sym)
            alias_set.update(_symbol_aliases(full_sym))

    return alias_set


# ── Doxygen DB 구축 ──────────────────────────────────────────────────────
def build_doxygen_symbol_set():
    """
    모든 parsed_doxygen JSON에서 compound 이름 + member 이름을 수집하여
    검색용 집합(set)을 반환합니다.

    반환:
      full_names  : "Dali::Actor::Property::SIZE" 등 완전한 심볼 이름 (기본 검증 기준)
      simple_names: "SetResourceUrl" 등 단순 이름
                    → dot-call 타입 추론 실패 시 폴백 검증으로만 사용
    """
    full_names = set()
    simple_names = set()

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
                full_names.update(_symbol_aliases(comp_name))
                simple_names.add(comp_name.split("::")[-1])

            for mb in comp.get("members", []):
                mb_name = mb.get("name", "")
                if mb_name:
                    full_sym = f"{comp_name}::{mb_name}"
                    full_names.add(full_sym)
                    full_names.update(_symbol_aliases(full_sym))
                    simple_names.add(mb_name)

    # 상속 체인 alias 등록 (View::Add, ImageView::Add 등 파생 클래스 메서드 검증 지원)
    inheritance_aliases = _build_inheritance_aliases(PARSED_DOXYGEN_DIR)
    full_names.update(inheritance_aliases)

    print(f"[Validator] Doxygen DB built: {len(full_names)} full symbols "
          f"(+{len(inheritance_aliases)} inheritance aliases), "
          f"{len(simple_names)} simple names.")
    return full_names, simple_names


# ── 심볼 추출 ─────────────────────────────────────────────────────────────
def extract_symbols_from_markdown(md_text):
    """
    Markdown 텍스트에서 C++ 심볼 참조를 추출합니다.
    추출 대상:
      - 코드 블록 내 Dali:: / Ui:: 네임스페이스 패턴 (완전 네임스페이스)
      - 코드 블록 내 dot-call 패턴:
          * 선언부에서 변수명 → Dali:: 타입 매핑 구축 후
            "Dali::Ui::ImageView::SetResourceUrl" 형태로 재구성 → full_names 검증
          * 타입 추론 불가(auto 등)인 경우 메서드 단순이름으로 폴백
      - 인라인 backtick 내 Dali:: 패턴 또는 CamelCase 식별자
    """
    symbols = set()

    # 1. 코드 블록 전체 추출
    code_blocks = re.findall(r'```(?:cpp|c\+\+)?\s*(.*?)\s*```', md_text, re.DOTALL | re.IGNORECASE)
    for block in code_blocks:
        # 1-a. 스코프 해소 심볼 추출 (Dali:: 전체 네임스페이스 및 CamelCase::Name 단축 이름 모두)
        #      Phase 3: using namespace 스타일 코드는 Dali:: 없이 CamelCase::Name 형태로 작성됨
        #      ex) Dali::Ui::AbsoluteLayout::New() 또는 AbsoluteLayout::New() 모두 캡처
        found = re.findall(
            r'\b(?:Dali::Ui::|Dali::)?[A-Z][A-Za-z0-9_]*(?:::[A-Za-z0-9_]+)+',
            block
        )
        # 추출된 심볼을 strip 정규화 후 추가 (Dali::Ui::X → X, Dali::X → X)
        for sym in found:
            symbols.add(_strip_dali_prefix(sym))

        # 1-b. dot-call 타입 추론
        #   선언부: "Dali::Ui::ImageView imageView = ..." 또는 "ImageView imageView = ..."
        #   "Type& varname" 레퍼런스 파라미터도 캡처 (함수 파라미터로 받은 View 타입 추론)
        #   → {"imageView": "ImageView"}  (strip 후 저장)
        var_type_map = {}
        for m in re.finditer(
            r'((?:Dali::Ui::|Dali::)?[A-Z][A-Za-z0-9_]*(?:::[A-Za-z0-9_]+)*)\s*&?\s+'
            r'([a-z_][a-zA-Z0-9_]*)\s*[=;{(,)]',
            block
        ):
            var_type_map[m.group(2)] = _strip_dali_prefix(m.group(1))

        for m in re.finditer(r'\b([a-z_][a-zA-Z0-9_]*)\.([A-Z][a-zA-Z0-9_]+)\s*\(', block):
            var_name, method = m.group(1), m.group(2)
            if var_name in var_type_map:
                # 타입 추론 성공 → short name 기반 full path 재구성
                symbols.add(f"{var_type_map[var_name]}::{method}")
            else:
                # 타입 추론 불가(반환값 체인 등) → simple_names 폴백 ('::' 미포함)
                symbols.add(method)

    # 2. 인라인 backtick
    #    Phase 3: Dali:: 없는 CamelCase::Name 패턴도 검증 대상 (using namespace 스타일)
    inline_ticks = re.findall(r'`([^`\n]+)`', md_text)
    for item in inline_ticks:
        item = item.strip()
        if '::' in item:
            # Dali:: / Ui:: 전체 네임스페이스 또는 CamelCase::Name 단축형 모두 대상
            if (item.startswith('Dali') or item.startswith('Ui::')
                    or re.match(r'^[A-Z][A-Za-z0-9_]+::', item)):
                symbols.add(_strip_dali_prefix(item))
        elif re.match(r'^[A-Z][a-zA-Z]{2,}$', item):
            symbols.add(item)

    # 노이즈 제거 (C++ 예약어 / Markdown 메타 키워드)
    # View / Actor 는 DALi 핵심 클래스이므로 제외하지 않음 — 할루시네이션 검증 대상
    noise = {'Include', 'Note', 'Warning', 'True', 'False', 'nullptr',
             'Void', 'Return', 'This', 'Class', 'New', 'Delete', 'Public', 'Private'}
    symbols -= noise
    return symbols


# ── 심볼 검증 ─────────────────────────────────────────────────────────────
def verify_symbols(symbols, full_names, simple_names):
    """
    추출된 심볼 각각을 Doxygen DB에서 검색합니다.

    검증 전략:
      1. '::' 포함 심볼 → full_names 직접 매칭
         (Dali:: 접두사 심볼 및 dot-call 타입추론 재구성 심볼 모두)
         pair_names 폴백 없음 — full_names에 없으면 unverified
      2. '::' 미포함 심볼 → simple_names 폴백
         (dot-call 타입 추론 실패 시 메서드명 검증)
    """
    verified = []
    unverified = []

    for sym in symbols:
        if '::' in sym:
            if sym in full_names:
                verified.append(sym)
            else:
                unverified.append(sym)
        else:
            if sym in simple_names:
                verified.append(sym)
            else:
                unverified.append(sym)

    return verified, unverified




# ── LLM 보조 검증 (원래 FAIL 진단용, 현재는 retry가 주 메커니즘) ────────────────
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


# ── Surgical Patch ───────────────────────────────────────────────────────
def extract_hallucinated_blocks(md_text, unverified_symbols):
    """
    unverified 심볼이 포함된 코드 블록과 직전 섹션 헤더를 추출합니다.
    전체 문서 재생성 대신 오염된 블록만 교체하는 surgical patch에 사용합니다.

    반환: [(section_header, code_block), ...] 리스트
    """
    unverified_simples = {s.split("::")[-1] for s in unverified_symbols}

    results = []
    # 코드 블록과 나머지 텍스트를 분리 (코드 블록 구분자 포함)
    pattern = re.compile(r'(```(?:cpp|c\+\+)?[^\n]*\n.*?```)', re.DOTALL | re.IGNORECASE)
    segments = pattern.split(md_text)

    current_header = ""
    for seg in segments:
        if seg.startswith('```'):
            contains_hallucination = any(sym_part in seg for sym_part in unverified_simples)
            if contains_hallucination:
                results.append((current_header, seg))
        else:
            headers = re.findall(r'^#{1,3} .+', seg, re.MULTILINE)
            if headers:
                current_header = headers[-1]

    return results


def surgical_patch_document(feat_name, md_text, unverified_symbols, specs, client):
    """
    unverified 심볼이 포함된 코드 블록만 재생성하여 문서에 적용합니다.
    전체 문서 재생성 대신 오염된 블록만 교체하므로 토큰 사용량을 크게 줄입니다.

    반환: (patched_md_text, patch_count)
      patch_count: 실제로 교체된 블록 수 (0이면 패치 대상 없음)
    """
    bad_blocks = extract_hallucinated_blocks(md_text, unverified_symbols)
    if not bad_blocks:
        return md_text, 0

    permitted = sorted({
        s["name"].split("::")[-1]
        for s in specs
        if s.get("kind") == "function"
        and not s["name"].split("::")[-1].startswith(("operator", "~"))
    })
    permitted_str = (
        "\n".join(f"  - {m}" for m in permitted)
        if permitted
        else "  (no callable methods — use only type declarations from specs)"
    )

    patched_text = md_text
    patch_count = 0

    for section_header, bad_block in bad_blocks:
        prompt = f"""You are a C++ technical writer for the Samsung DALi GUI framework.
The following code example in the '{feat_name}' documentation contains incorrect API calls.

Section: {section_header}

[INCORRECT CODE BLOCK]
{bad_block}

[VERIFIED API SPECS]
{json.dumps(specs[:15], indent=2)}

Permitted method names — call ONLY these in the fixed code:
{permitted_str}

Rewrite ONLY the code block above. Fix incorrect method names using only the permitted list above.
Keep the overall structure and intent of the example intact.
Output only the corrected ```cpp ... ``` block. No explanation before or after."""
        try:
            new_block = client.generate(prompt, use_think=False).strip()
            if new_block.startswith('```') and '```' in new_block[3:]:
                patched_text = patched_text.replace(bad_block, new_block, 1)
                patch_count += 1
            else:
                print(f"    [Surgical] Block replacement skipped — LLM did not return a code block.")
        except Exception as e:
            print(f"    [Surgical] Patch failed for block in '{section_header}': {e}")

    return patched_text, patch_count


# ── Retry 전용 헬퍼 함수 ─────────────────────────────────────────────────
def strip_markdown_wrapping(text):
    """markdown ``` 래퍼링 제거."""
    stripped = text.strip()
    if stripped.startswith("```markdown"):
        stripped = stripped[11:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    elif stripped.startswith("```"):
        stripped = stripped[3:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()


def load_blueprints(tier):
    """
    Stage B 블루프린트에서 feature별 outline/packages 정보 로드.
    """
    path = CACHE_DIR / "doc_blueprints" / f"stage_b_blueprints_{tier}.json"
    if not path.exists():
        path = CACHE_DIR / "doc_blueprints" / "stage_b_blueprints.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {item["feature"]: item for item in data}


def get_api_specs_for_retry(packages, api_names, allowed_tiers=None, max_specs=30):
    """
    Stage C와 동일한 방식으로 Doxygen에서 API spec 추출 (Retry 전용).

    allowed_tiers: set of api_tier strings to include (e.g. {"public-api"}).
                   None means no filtering (all tiers included).
    """
    specs = []
    api_name_set = set(a.split("::")[-1] for a in api_names)
    for pkg in packages:
        pkg_path = PARSED_DOXYGEN_DIR / f"{pkg}.json"
        if not pkg_path.exists():
            continue
        with open(pkg_path, "r", encoding="utf-8") as f:
            pkg_data = json.load(f)
        for comp in pkg_data.get("compounds", []):
            if not isinstance(comp, dict):
                continue
            if allowed_tiers and comp.get("api_tier") not in allowed_tiers:
                continue
            c_name = comp.get("name", "")
            is_match = any(a in c_name for a in api_names) or \
                       any(c_name.split("::")[-1] in api_name_set for _ in [1])
            if is_match:
                specs.append({"name": c_name, "kind": comp.get("kind"), "brief": comp.get("brief", "")})
                for mb in comp.get("members", []):
                    if not isinstance(mb, dict):
                        continue
                    specs.append({
                        "name": f"{c_name}::{mb.get('name', '')}",
                        "kind": mb.get("kind"),
                        "brief": mb.get("brief", ""),
                        "signature": mb.get("signature", "")
                    })
                    if len(specs) >= max_specs:
                        break
            if len(specs) >= max_specs:
                break
        if len(specs) >= max_specs:
            break
    return specs


def regenerate_failed_document(feat_name, blueprint, taxonomy, unverified_set, client):
    """
    FAIL 판정된 문서를 할루시네이션 목록을 포함한 수정된 프롬프트로 재생성합니다.
    """
    outline = blueprint.get("outline", [])
    packages = blueprint.get("packages", [])
    api_names = blueprint.get("apis", [])
    allowed_tiers = blueprint.get("allowed_tiers")
    specs = get_api_specs_for_retry(packages, api_names, allowed_tiers=allowed_tiers)

    # Taxonomy context (stage_c_writer.py와 동일)
    tax = {}
    if TAXONOMY_PATH.exists():
        with open(TAXONOMY_PATH, "r", encoding="utf-8") as f:
            tax = json.load(f)
    tax_entry = tax.get(feat_name, {})
    tree_decision = tax_entry.get("tree_decision", "flat")
    children = tax_entry.get("children", [])
    parent = tax_entry.get("parent", None)

    taxonomy_context = ""
    if tree_decision == "tree" and children:
        taxonomy_context = f"This is a PARENT OVERVIEW page for '{feat_name}'. " \
                           f"Child pages: {', '.join(children)}."
    elif tree_decision == "leaf" and parent:
        taxonomy_context = f"This is a CHILD DETAIL page for '{feat_name}', " \
                           f"sub-component of '{parent}'."

    # Hallucination correction hints
    sym_list = "\n".join(f"  - {s}" for s in sorted(unverified_set))
    correction = f"""
CORRECTION REQUIRED — HALLUCINATION DETECTED:
The previous draft referenced the following symbols that do NOT exist in the DALi Doxygen DB:
{sym_list}
STRICT RULES FOR THIS REVISION:
1. Do NOT use any of the above symbols.
2. Use ONLY the verified C++ API specs provided below.
3. If a concept cannot be expressed using verified specs, omit or generalize it.
"""

    prompt = f"""
You are an elite C++ technical writer documenting the Samsung DALi GUI framework.
Rewrite the COMPLETE Markdown documentation for the '{feat_name}' module.
{taxonomy_context}
{correction}
Follow this Table of Contents structure exactly:
{json.dumps(outline, indent=2)}

VERIFIED API SPECS (use ONLY these for signatures and class names):
{json.dumps(specs, indent=2)}

Writing Guidelines:
- Write entirely in valid GitHub Flavored Markdown.
- Use ## for section titles and ### for sub-sections.
- Each section must be DETAILED and THOROUGH.
- Include at least one realistic C++ code example per section.
- Output raw markdown text only. Do NOT wrap in ```markdown blocks.
"""
    return client.generate(prompt, use_think=False)


# ── 메인 ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip LLM review for FAIL documents.")
    parser.add_argument("--no-retry", action="store_true",
                        help="Skip auto-regeneration retry loop for FAIL documents.")
    parser.add_argument("--tier", type=str, choices=["app", "platform"], default="app",
                        help="Documentation tier: matches the tier used in Stage C.")
    args = parser.parse_args()

    print("=================================================================")
    print(f" Stage D: Hallucination Validation Engine [{args.tier.upper()}]")
    print("=================================================================")

    # 티어별 드래프트 읽기/검증 출력 경로
    tier_drafts_dir = DRAFTS_DIR / args.tier
    tier_validated_dir = OUT_VALIDATED_DIR / args.tier
    report_path = OUT_REPORT_DIR / f"stage_d_report_{args.tier}.json"

    # 디렉터리 준비
    OUT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    tier_validated_dir.mkdir(parents=True, exist_ok=True)

    # Doxygen DB 구축
    full_names, simple_names = build_doxygen_symbol_set()


    # 검증 대상 파일 수집 (Index.md 제외)
    if not tier_drafts_dir.exists():
        print(f"No markdown drafts found in {tier_drafts_dir}. Run Stage C --tier {args.tier} first.")
        return
    md_files = sorted([p for p in tier_drafts_dir.glob("*.md") if p.name != "Index.md"])
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

        # WARN/FAIL이고 LLM 클라이언트가 있으면 surgical patch 시도
        # PASS / LOW_CONTENT는 그대로 복사
        llm_comment = None
        surgical_patches = 0
        
        history = [{
            "attempt": 0,
            "type": "initial",
            "verdict": verdict,
            "score": round(score, 4) if score is not None else None,
            "verified_symbols": verified_syms[:],
            "unverified_symbols": unverified_syms[:],
            "copy_status": "pending",
            "surgical_patches": 0,
            "llm_review": None
        }]

        if verdict in ("WARN", "FAIL") and client and unverified_syms and not args.no_retry:
            pre_verdict = verdict  # stats 재조정 시 원래 verdict 참조용
            print(f"  [Surgical] '{feat_name}': {len(unverified_syms)} unverified symbol(s) — "
                  f"attempting block-level patch...")
            # API 스펙 로드 (surgical patch 프롬프트용)
            blueprints_map_local = load_blueprints(args.tier)
            bp_local = blueprints_map_local.get(feat_name, {})
            allowed_tiers_local = {"public-api"} if args.tier == "app" else None
            patch_specs = get_api_specs_for_retry(
                bp_local.get("packages", []),
                bp_local.get("apis", []),
                allowed_tiers=allowed_tiers_local
            )
            patched_md, surgical_patches = surgical_patch_document(
                feat_name, md_text, set(unverified_syms), patch_specs, client
            )
            if surgical_patches > 0:
                # 패치된 내용으로 draft 파일 갱신 후 재검증
                md_path.write_text(patched_md, encoding="utf-8")
                new_symbols = extract_symbols_from_markdown(patched_md)
                if len(new_symbols) >= MIN_SYMBOLS_FOR_SCORING:
                    new_verified, new_unverified = verify_symbols(
                        new_symbols, full_names, simple_names)

                    new_score = len(new_verified) / len(new_symbols)
                    if new_score >= PASS_THRESHOLD:
                        verdict = "PASS"
                    elif new_score >= WARN_THRESHOLD:
                        verdict = "WARN"
                    else:
                        verdict = "FAIL"
                    verified_syms, unverified_syms = new_verified, new_unverified
                    score = new_score
                    print(f"  [Surgical] Re-validated after patch: [{verdict}] "
                          f"score={score:.1%} ({surgical_patches} block(s) replaced)")
                    
                    history.append({
                        "attempt": 0,
                        "type": "surgical_patch",
                        "verdict": verdict,
                        "score": round(score, 4) if score is not None else None,
                        "verified_symbols": verified_syms[:],
                        "unverified_symbols": unverified_syms[:],
                        "copy_status": "pending",
                        "surgical_patches": surgical_patches,
                        "llm_review": None
                    })

                    # stats 재조정: 원래 verdict(pre_verdict)를 -1, 새 verdict를 +1
                    stats[pre_verdict.lower()] = max(0, stats.get(pre_verdict.lower(), 0) - 1)
                    stats[verdict.lower()] = stats.get(verdict.lower(), 0) + 1
            else:
                print(f"  [Surgical] No patchable blocks found — keeping original verdict.")

        elif verdict == "FAIL" and client and unverified_syms:
            # --no-retry 또는 surgical patch 미적용 경우 LLM 분석만
            print(f"  [LLM Review] Requesting analysis for FAIL document '{feat_name}'...")
            llm_comment = llm_review_fail(feat_name, md_text, unverified_syms, client)

        # PASS / WARN / LOW_CONTENT → validated_drafts/{tier}/ 복사
        if verdict in ("PASS", "WARN", "LOW_CONTENT"):
            shutil.copy2(md_path, tier_validated_dir / md_path.name)
            copy_status = "copied"
        else:
            copy_status = "blocked"

        score_display = f"{score:.1%}" if score is not None else "N/A"
        print(f"  [{verdict:12s}] {feat_name}.md  "
              f"symbols={len(symbols)}, verified={len(verified_syms)}, "
              f"score={score_display}  surgical_patches={surgical_patches}  → {copy_status}")

        report.append({
            "feature": feat_name,
            "verdict": verdict,
            "total_symbols": len(symbols),
            "history": history
        })

    # 리포트 저장
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # ── Stage D Retry Loop ───────────────────────────────────────────────
    fail_entries = [r for r in report if r["verdict"] == "FAIL"]

    if fail_entries and not args.no_retry and not args.no_llm:
        print(f"\n[Retry] {len(fail_entries)} FAIL document(s) detected. "
              f"Starting auto-regeneration loop (max {MAX_RETRY_ATTEMPTS} attempts)...")
        blueprints_map = load_blueprints(args.tier)
        retry_client = client if client else LLMClient()

        for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
            still_failing = []
            for entry in fail_entries:
                feat_name = entry["feature"]
                unverified_set = set(entry["history"][-1].get("unverified_symbols", []))
                blueprint = blueprints_map.get(feat_name)
                if not blueprint:
                    print(f"  [Retry {attempt}] '{feat_name}': No blueprint found, skipping.")
                    still_failing.append(entry)
                    continue

                print(f"  [Retry {attempt}/{MAX_RETRY_ATTEMPTS}] Regenerating '{feat_name}'.md "
                      f"({len(unverified_set)} unverified symbols)...")
                # tier 필터를 blueprint에 주입하여 get_api_specs_for_retry가 올바른 tier만 조회하게 함
                blueprint_with_tier = dict(blueprint)
                blueprint_with_tier["allowed_tiers"] = (
                    {"public-api"} if args.tier == "app" else None
                )
                try:
                    new_md_raw = regenerate_failed_document(
                        feat_name, blueprint_with_tier, {}, unverified_set, retry_client)
                    new_md = strip_markdown_wrapping(new_md_raw)
                except Exception as e:
                    print(f"    [!] Regeneration failed: {e}")
                    still_failing.append(entry)
                    continue

                # 새 draft 덮어쓰기
                draft_path = tier_drafts_dir / f"{feat_name}.md"
                draft_path.write_text(new_md, encoding="utf-8")

                # 재검증
                new_symbols = extract_symbols_from_markdown(new_md)
                if len(new_symbols) < MIN_SYMBOLS_FOR_SCORING:
                    new_verdict = "LOW_CONTENT"
                    new_score = None
                    new_verified, new_unverified = [], list(new_symbols)
                else:
                    new_verified, new_unverified = verify_symbols(
                        new_symbols, full_names, simple_names)

                    new_score = len(new_verified) / len(new_symbols)
                    if new_score >= PASS_THRESHOLD:
                        new_verdict = "PASS"
                    elif new_score >= WARN_THRESHOLD:
                        new_verdict = "WARN"
                    else:
                        new_verdict = "FAIL"

                score_disp = f"{new_score:.1%}" if new_score else "N/A"
                print(f"    → Re-validated: [{new_verdict}] score={score_disp}")

                # 리포트 업데이트
                for r in report:
                    if r["feature"] == feat_name:
                        r["verdict"] = new_verdict
                        r.setdefault("history", []).append({
                            "attempt": attempt,
                            "type": "full_regeneration",
                            "verdict": new_verdict,
                            "score": round(new_score, 4) if new_score else None,
                            "verified_symbols": new_verified[:],
                            "unverified_symbols": new_unverified[:],
                            "copy_status": "copied" if new_verdict != "FAIL" else "blocked",
                            "surgical_patches": 0,
                            "llm_review": None
                        })
                        break

                # PASS/WARN/LOW_CONTENT 이면 validated_drafts/{tier}에 복사
                if new_verdict != "FAIL":
                    shutil.copy2(draft_path, tier_validated_dir / f"{feat_name}.md")
                    stats[new_verdict.lower()] = stats.get(new_verdict.lower(), 0) + 1
                    stats["fail"] = max(0, stats["fail"] - 1)
                else:
                    entry["unverified_symbols"] = new_unverified
                    still_failing.append(entry)

            fail_entries = still_failing
            if not fail_entries:
                print(f"  [Retry] All documents recovered after {attempt} attempt(s). ✅")
                break

        if fail_entries:
            remaining = [e["feature"] for e in fail_entries]
            print(f"  [Retry] {len(fail_entries)} document(s) remain FAIL after "
                  f"{MAX_RETRY_ATTEMPTS} attempts: {remaining}")
    elif fail_entries and args.no_retry:
        print(f"\n[Retry] Skipped (--no-retry). {len(fail_entries)} FAIL document(s) not retried.")
    # ────────────────────────────────────────────────────────────────────

    # ── 리포트 최종 저장 (리트라이 정보 포함) ──────────────────────────────────
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # 최종 요약
    total = len(md_files)
    print(f"\n=================================================================")
    print(f" Stage D Complete! Validation report saved.")
    print(f" Results: PASS={stats['pass']}, WARN={stats['warn']}, "
          f"FAIL={stats['fail']}, LOW_CONTENT={stats['low_content']} / {total} files")
    print(f" Report  : {report_path}")
    print(f" Validated: {tier_validated_dir}")
    print("=================================================================")


if __name__ == "__main__":
    main()
