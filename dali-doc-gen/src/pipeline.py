import os
import sys
import shutil
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone
import json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "cache"

# ── venv 자동 생성 및 재실행 ────────────────────────────────────────────────
# 1. venv가 없으면 생성 후 requirements.txt 설치
# 2. 현재 Python이 venv Python이 아니면 venv Python으로 재실행 (os.execv)
# → 어떤 Python으로 실행해도 항상 venv 환경에서 실행됨
_venv_python = PROJECT_ROOT / "venv" / "bin" / "python"
_requirements = PROJECT_ROOT / "requirements.txt"

if not _venv_python.exists():
    print("[pipeline] venv not found — creating venv and installing requirements...")
    subprocess.check_call([sys.executable, "-m", "venv", str(PROJECT_ROOT / "venv")])
    if _requirements.exists():
        subprocess.check_call([str(_venv_python), "-m", "pip", "install",
                               "-r", str(_requirements), "--quiet"])
    print("[pipeline] venv ready.")

if Path(sys.executable).resolve() != _venv_python.resolve():
    os.execv(str(_venv_python), [str(_venv_python)] + sys.argv)
# ────────────────────────────────────────────────────────────────────────────

SESSION_STATS_PATH    = CACHE_DIR / "llm_session_stats.json"
TAXONOMY_PATH         = CACHE_DIR / "feature_taxonomy" / "feature_taxonomy.json"
TAXONOMY_OLD_PATH     = CACHE_DIR / "feature_taxonomy" / "feature_taxonomy.json.old"
DRAFTS_DIR            = CACHE_DIR / "validated_drafts"
CHANGED_APIS_PATH     = CACHE_DIR / "changed_apis.json"
PARSED_DOXYGEN_DIR    = CACHE_DIR / "parsed_doxygen"
LAST_RUN_PATH         = CACHE_DIR / "last_run_commits.json"
CLASSIFIED_MAP_PATH   = CACHE_DIR / "feature_map" / "feature_map_classified.json"

# Taxonomy 구조 변경을 판단하는 필드 목록 (원칙 1)
STRUCTURAL_KEYS = {"children", "parent", "tree_decision"}


def load_json(path):
    if not Path(path).exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def backup_parsed_doxygen():
    """
    doxygen_parser.py 실행 전에 기존 parsed_doxygen/*.json 을 *.json.old 로 백업.
    diff_detector.py 가 이 .old 파일을 기준으로 변경분을 계산한다.
    """
    if not PARSED_DOXYGEN_DIR.exists():
        print("  [*] parsed_doxygen/ not found — skipping backup.")
        return
    backed_up = 0
    for json_file in PARSED_DOXYGEN_DIR.glob("*.json"):
        if json_file.suffix == ".json" and not json_file.name.endswith(".old"):
            old_path = json_file.with_suffix(".json.old")
            shutil.copy2(json_file, old_path)
            backed_up += 1
    print(f"  [*] Backed up {backed_up} parsed_doxygen JSON(s) → *.json.old")


def save_last_run_commits():
    """
    파이프라인 완료 시 각 repo 의 현재 HEAD 커밋 해시를 last_run_commits.json 에 저장.
    다음 --mode update 실행 시 diff 기준점으로 활용된다.
    """
    import subprocess as _sp
    repos_config_path = PROJECT_ROOT / "config" / "repo_config.yaml"
    if not repos_config_path.exists():
        return
    try:
        import yaml
        with open(repos_config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except Exception:
        return

    commits = {}
    for pkg, info in config.get("repos", {}).items():
        repo_path = PROJECT_ROOT / info.get("path", "")
        if not (repo_path / ".git").exists():
            continue
        try:
            result = _sp.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_path, capture_output=True, text=True
            )
            if result.returncode == 0:
                commits[pkg] = result.stdout.strip()
        except Exception:
            pass

    commits["saved_at"] = datetime.now(timezone.utc).isoformat()
    LAST_RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LAST_RUN_PATH, "w", encoding="utf-8") as f:
        json.dump(commits, f, indent=2)
    print(f"  [*] Saved last run commits → {LAST_RUN_PATH.name}")


def run_script(script_path, args_list):
    """지정된 파이썬 스크립트를 독립 프로세스로 실행합니다."""
    # sys.executable이 venv symlink를 resolve해서 시스템 Python을 가리킬 수 있으므로
    # 항상 venv Python 경로를 명시적으로 사용
    venv_py = PROJECT_ROOT / "venv" / "bin" / "python"
    python_exe = str(venv_py) if venv_py.exists() else sys.executable
    cmd = [python_exe, str(script_path)] + args_list
    print(f"\n▶ Executing: {' '.join(cmd)}")
    subprocess.check_call(cmd)


def compute_incremental_targets(tier="app"):
    """
    구 taxonomy.old ↔ 신 taxonomy 를 비교하여
    needs_regen / needs_patch 집합을 반환합니다. (원칙 1, 2, 3)

    Returns:
        needs_regen (set): Draft 삭제 후 B+C+D 전체 재생성 대상
        needs_patch  (set): 기존 Draft 유지하며 C(patch)+D 만 실행할 대상
    """
    needs_regen = set()
    needs_patch  = set()

    old_tax = load_json(TAXONOMY_OLD_PATH)
    new_tax = load_json(TAXONOMY_PATH)

    if not old_tax:
        print("  [*] No previous taxonomy found — treating all features as new (needs_regen).")
        needs_regen = set(new_tax.keys())
        return needs_regen, needs_patch

    # ── 원칙 2: 신규 추가된 피처 탐지 + 부모 연쇄 삭제 ──────────────────────
    for feat_id in new_tax:
        if feat_id not in old_tax:
            print(f"  [+] NEW feature detected: '{feat_id}'")
            needs_regen.add(feat_id)
            parent = new_tax[feat_id].get("parent")
            if parent and parent in new_tax:
                print(f"      └─ Cascade invalidating parent: '{parent}'")
                needs_regen.add(parent)

    # ── 원칙 2: 구조 변경 탐지 (children / parent / tree_decision) + 부모 연쇄 삭제 ──
    for feat_id in new_tax:
        if feat_id in old_tax:
            old_entry = old_tax[feat_id]
            new_entry = new_tax[feat_id]
            changed_keys = [
                k for k in STRUCTURAL_KEYS
                if old_entry.get(k) != new_entry.get(k)
            ]
            if changed_keys:
                print(f"  [!] Structural change in '{feat_id}': fields {changed_keys}")
                needs_regen.add(feat_id)
                parent = new_entry.get("parent")
                if parent and parent in new_tax:
                    print(f"      └─ Cascade invalidating parent: '{parent}'")
                    needs_regen.add(parent)

    # ── 삭제된 피처: Draft 제거만 하고 재생성 없음 ───────────────────────────
    tier_validated_dir = DRAFTS_DIR / tier
    for feat_id in old_tax:
        if feat_id not in new_tax:
            draft = tier_validated_dir / f"{feat_id}.md"
            if draft.exists():
                draft.unlink()
                print(f"  [-] Removed obsolete draft: '{feat_id}'")

    # ── needs_regen 피처의 Draft 파일 삭제 (Stage B 재실행 전 반드시 선행) ───
    for feat_id in needs_regen:
        draft = tier_validated_dir / f"{feat_id}.md"
        if draft.exists():
            draft.unlink()
            print(f"  [x] Invalidated draft for regen: '{feat_id}'")

    # ── 원칙 3: API 변경 탐지 → needs_patch 분류 ──────────────────────────────
    # (needs_regen 피처는 이미 전체 재생성 대상이므로 제외)
    # changed_apis.json 포맷: {pkg: [{class, changed_members, added_members, ...}]}
    changed_apis = load_json(CHANGED_APIS_PATH)
    if changed_apis:
        # 모든 패키지의 변경 class 이름 합집합 (full name + simple name)
        changed_class_names = set()
        for pkg_apis in changed_apis.values():
            for entry in pkg_apis:
                cls = entry.get("class", "")
                if cls:
                    changed_class_names.add(cls)
                    changed_class_names.add(cls.split("::")[-1])

        if changed_class_names:
            # feature_map_classified.json 에서 feature별 api 목록 로드
            # (feature_taxonomy.json 에는 apis 필드가 없음)
            classified = load_json(CLASSIFIED_MAP_PATH)
            feat_apis_map = {}
            if classified:
                for item in classified:
                    fid = item.get("feature", "")
                    if fid:
                        feat_apis_map[fid] = set(item.get("apis", []))

            for feat_id, feat_data in new_tax.items():
                if feat_id in needs_regen:
                    continue  # regen 우선
                # feature_map_classified 의 apis 우선, 없으면 display_name 만으로 체크
                feat_apis = feat_apis_map.get(feat_id, set())
                feat_apis = feat_apis | {feat_data.get("display_name", "")}
                feat_simple = {a.split("::")[-1] for a in feat_apis}
                if feat_apis & changed_class_names or feat_simple & changed_class_names:
                    print(f"  [~] API change detected for '{feat_id}' → needs_patch")
                    needs_patch.add(feat_id)
    else:
        print("  [*] No changed_apis.json found — skipping patch detection.")

    return needs_regen, needs_patch


def main():
    parser = argparse.ArgumentParser(description="DALi Documentation Gen Pipeline")
    parser.add_argument("--mode", choices=["full", "update"], default="full",
                        help="Pipeline execution mode")
    parser.add_argument("--tier", choices=["app", "platform", "all"], default="app",
                        help="Target document tier")
    parser.add_argument("--limit", type=int, default=0,
                        help="Debug limit for stages B and C")
    parser.add_argument("--features", type=str, default="",
                        help="Exclusive features to process (comma-separated)")
    parser.add_argument("--skip-pull", action="store_true",
                        help="Skip running repo_manager (useful for local rollback testing)")
    parser.add_argument("--llm", choices=["internal", "external"], default=None,
                        help="LLM environment to use (overrides doc_config.yaml)")

    args = parser.parse_args()

    # --llm 인자가 있으면 환경변수로 전달 (doc_config.yaml 수정 없음)
    # 자식 subprocess들은 환경변수를 상속하므로 별도 처리 불필요
    if args.llm:
        os.environ["DALI_LLM_ENV"] = args.llm
        print(f"[pipeline] LLM environment override: {args.llm} (via DALI_LLM_ENV)")

    if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("INTERNAL_API_KEY"):
        print("⚠️  Warning: GEMINI_API_KEY or INTERNAL_API_KEY is not set.")

    _run_pipeline(args)


def _run_pipeline(args):
    """파이프라인 본체. main()의 try 블록에서 호출된다."""
    # LLM 세션 통계 초기화 (이전 실행 잔재 제거)
    SESSION_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SESSION_STATS_PATH, "w", encoding="utf-8") as f:
        json.dump({"total_input_tokens": 0, "total_requests": 0}, f)

    # ══════════════════════════════════════════════════════════════════════
    #  Phase 1: 코드 파싱 & Taxonomy 추출
    # ══════════════════════════════════════════════════════════════════════
    print("\n==========================================================")
    print("   [Phase 1] Code Parsing & Feature Taxonomy Extraction   ")
    print("==========================================================")

    if not args.skip_pull:
        run_script(PROJECT_ROOT / "src" / "00_extract" / "repo_manager.py", [])
    else:
        print("  [*] --skip-pull provided: Skipping repo_manager git pulls.")

    for pkg in ["dali-core", "dali-adaptor", "dali-ui"]:
        run_script(PROJECT_ROOT / "src" / "00_extract" / "doxygen_runner.py",
                   ["--package", pkg])

    # ── Update 모드: doxygen_parser 실행 전에 기존 JSON 백업 (diff 비교 기준점) ──
    if args.mode == "update":
        backup_parsed_doxygen()

    run_script(PROJECT_ROOT / "src" / "00_extract" / "doxygen_parser.py", [])

    # ── Update 모드: 새 JSON vs 백업 JSON 비교 → changed_apis.json 생성 ──────
    if args.mode == "update":
        run_script(PROJECT_ROOT / "src" / "00_extract" / "diff_detector.py", [])

    run_script(PROJECT_ROOT / "src" / "00_extract" / "callgraph_parser.py", [])
    run_script(PROJECT_ROOT / "src" / "01_cluster" / "feature_clusterer.py", [])

    # ── Update 모드에서는 taxonomy_reviewer 실행 전에 기존 taxonomy 백업 (원칙 1) ──
    if args.mode == "update" and TAXONOMY_PATH.exists():
        shutil.copy2(TAXONOMY_PATH, TAXONOMY_OLD_PATH)
        print(f"\n  [*] Backed up taxonomy → feature_taxonomy.json.old")

    run_script(PROJECT_ROOT / "src" / "01_cluster" / "taxonomy_reviewer.py", [])

    # 타겟 독자 티어 결정
    tiers_to_run = ["app", "platform"] if args.tier == "all" else [args.tier]

    print("\n==========================================================")
    print(f"   [Phase 2 & 3] LLM Pipeline & Output Rendering"
          f" ({args.mode.upper()} mode)")
    print("==========================================================")

    for current_tier in tiers_to_run:
        print(f"\n>>> Starting Pipeline for Tier: {current_tier.upper()} <<<")

        # ── Incremental Update 분류 로직 ──────────────────────────────────
        if args.mode == "update":
            print("  [*] Update Mode: Computing incremental deltas...")
            needs_regen, needs_patch = compute_incremental_targets(tier=current_tier)

            # --features 가 지정된 경우: 증분 결과를 해당 feature 로만 필터링
            # (전체 증분 로직은 동일하게 동작, 처리 범위만 제한)
            if args.features:
                filter_set = {f.strip() for f in args.features.split(",") if f.strip()}
                needs_regen = needs_regen & filter_set
                needs_patch  = needs_patch  & filter_set
                print(f"  [*] --features filter: restricting to {sorted(filter_set)}")
                print(f"      → needs_regen: {sorted(needs_regen)}")
                print(f"      → needs_patch:  {sorted(needs_patch)}")

            if not needs_regen and not needs_patch:
                print(f"\n  ✅ All documents up to date for '{current_tier}'. Skipping LLM stages.")
                # 렌더링만 수행 (사이드바 갱신 등)
                render_args = ["--tier", current_tier]
                run_script(PROJECT_ROOT / "src" / "03_render" / "md_renderer.py", render_args)
                run_script(PROJECT_ROOT / "src" / "03_render" / "sidebar_generator.py", render_args)
                run_script(PROJECT_ROOT / "src" / "03_render" / "index_generator.py", render_args)
                continue

            # ── needs_regen: Stage B → C (full) → D ──────────────────────
            if needs_regen:
                print(f"\n  [REGEN] {len(needs_regen)} feature(s) require full regeneration:")
                for f in sorted(needs_regen):
                    print(f"          • {f}")

                regen_args = ["--tier", current_tier, "--features", ",".join(needs_regen)]
                if args.limit > 0:
                    regen_args += ["--limit", str(args.limit)]

                run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_a_classifier.py", [])
                run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_b_mapper.py", regen_args)
                run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_c_writer.py", regen_args)
                run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_d_validator.py",
                           ["--tier", current_tier])

            # ── needs_patch: Stage C (patch) → D ─────────────────────────
            if needs_patch:
                print(f"\n  [PATCH] {len(needs_patch)} feature(s) require incremental patching:")
                for f in sorted(needs_patch):
                    print(f"          • {f}")

                patch_args = [
                    "--tier", current_tier,
                    "--patch",
                    "--patch-features", ",".join(needs_patch),
                ]
                if args.limit > 0:
                    patch_args += ["--limit", str(args.limit)]

                run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_c_writer.py", patch_args)
                run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_d_validator.py",
                           ["--tier", current_tier])

        else:
            # ── Full 생성 모드 ─────────────────────────────────────────────
            stage_args = ["--tier", current_tier]
            if args.limit > 0:
                stage_args += ["--limit", str(args.limit)]
            if args.features:
                stage_args += ["--features", args.features]

            run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_a_classifier.py", [])
            run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_b_mapper.py", stage_args)
            run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_c_writer.py", stage_args)
            run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_d_validator.py",
                       ["--tier", current_tier])

        # ── Phase 3: 렌더링 (Tier별 무조건 실행) ─────────────────────────
        print(f"\n--- [Phase 3] Docusaurus Rendering for {current_tier} ---")
        render_args = ["--tier", current_tier]
        run_script(PROJECT_ROOT / "src" / "03_render" / "md_renderer.py", render_args)
        run_script(PROJECT_ROOT / "src" / "03_render" / "sidebar_generator.py", render_args)
        run_script(PROJECT_ROOT / "src" / "03_render" / "index_generator.py", render_args)

    # ── 실행 완료 후 현재 커밋 해시 저장 (다음 update 의 diff 기준점) ─────────
    save_last_run_commits()

    # ── LLM 세션 통계 출력 ────────────────────────────────────────────────
    try:
        stats = load_json(SESSION_STATS_PATH)
        total_tokens = stats.get("total_input_tokens", 0)
        total_requests = stats.get("total_requests", 0)
        print("\n─────────────────────────────────────────────────")
        print(f"  LLM Session Summary")
        print(f"    Requests sent : {total_requests:,}")
        print(f"    Input tokens  : {total_tokens:,}")
        print("─────────────────────────────────────────────────")
    except Exception:
        pass

    print("\n✅ DALi Documentation Pipeline Execution Completed!")


if __name__ == "__main__":
    main()
