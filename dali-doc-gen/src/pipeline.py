import os
import sys
import shutil
import argparse
import subprocess
from pathlib import Path
import json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "cache"

TAXONOMY_PATH     = CACHE_DIR / "feature_taxonomy" / "feature_taxonomy.json"
TAXONOMY_OLD_PATH = CACHE_DIR / "feature_taxonomy" / "feature_taxonomy.json.old"
DRAFTS_DIR        = CACHE_DIR / "validated_drafts"
CHANGED_APIS_PATH = CACHE_DIR / "changed_apis.json"

# Taxonomy 구조 변경을 판단하는 필드 목록 (원칙 1)
STRUCTURAL_KEYS = {"children", "parent", "tree_decision"}


def load_json(path):
    if not Path(path).exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_script(script_path, args_list):
    """지정된 파이썬 스크립트를 독립 프로세스로 실행합니다."""
    cmd = [sys.executable, str(script_path)] + args_list
    print(f"\n▶ Executing: {' '.join(cmd)}")
    subprocess.check_call(cmd)


def compute_incremental_targets(tiers_to_run):
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
    for feat_id in old_tax:
        if feat_id not in new_tax:
            draft = DRAFTS_DIR / f"{feat_id}.md"
            if draft.exists():
                draft.unlink()
                print(f"  [-] Removed obsolete draft: '{feat_id}'")

    # ── needs_regen 피처의 Draft 파일 삭제 (Stage B 재실행 전 반드시 선행) ───
    for feat_id in needs_regen:
        draft = DRAFTS_DIR / f"{feat_id}.md"
        if draft.exists():
            draft.unlink()
            print(f"  [x] Invalidated draft for regen: '{feat_id}'")

    # ── 원칙 3: API 변경 탐지 → needs_patch 분류 ──────────────────────────────
    # (needs_regen 피처는 이미 전체 재생성 대상이므로 제외)
    changed_apis = load_json(CHANGED_APIS_PATH)
    if changed_apis:
        # 모든 패키지의 변경 API name 합집합
        changed_api_names = set()
        for pkg_apis in changed_apis.values():
            for api in pkg_apis:
                name = api.get("name", "")
                if name:
                    changed_api_names.add(name)
                    # "Dali::Actor::SetPosition" → "SetPosition", "Actor" 등도 체크
                    changed_api_names.add(name.split("::")[-1])

        if changed_api_names:
            for feat_id, feat_data in new_tax.items():
                if feat_id in needs_regen:
                    continue  # regen 우선
                feat_apis = set(feat_data.get("apis", []))
                # 피처 apis 필드가 없는 경우 display_name 으로도 체크
                feat_apis.add(feat_data.get("display_name", ""))
                if feat_apis & changed_api_names:
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

    args = parser.parse_args()

    if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("INTERNAL_API_KEY"):
        print("⚠️  Warning: GEMINI_API_KEY or INTERNAL_API_KEY is not set.")

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

    run_script(PROJECT_ROOT / "src" / "00_extract" / "doxygen_parser.py", [])
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
        if args.mode == "update" and not args.features:
            print("  [*] Update Mode: Computing incremental deltas...")
            needs_regen, needs_patch = compute_incremental_targets(tiers_to_run)

            if not needs_regen and not needs_patch:
                print(f"\n  ✅ All documents up to date for '{current_tier}'. Skipping LLM stages.")
                # 렌더링만 수행 (사이드바 갱신 등)
                render_args = ["--tier", current_tier]
                run_script(PROJECT_ROOT / "src" / "03_render" / "md_renderer.py", render_args)
                run_script(PROJECT_ROOT / "src" / "03_render" / "sidebar_generator.py", render_args)
                continue

            # ── needs_regen: Stage B → C (full) → D ──────────────────────
            if needs_regen:
                print(f"\n  [REGEN] {len(needs_regen)} feature(s) require full regeneration:")
                for f in sorted(needs_regen):
                    print(f"          • {f}")

                regen_args = ["--features", ",".join(needs_regen)]
                if args.limit > 0:
                    regen_args += ["--limit", str(args.limit)]

                run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_a_classifier.py", [])
                run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_b_mapper.py", regen_args)
                run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_c_writer.py", regen_args)
                run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_d_validator.py", [])

            # ── needs_patch: Stage C (patch) → D ─────────────────────────
            if needs_patch:
                print(f"\n  [PATCH] {len(needs_patch)} feature(s) require incremental patching:")
                for f in sorted(needs_patch):
                    print(f"          • {f}")

                patch_args = [
                    "--patch",
                    "--patch-features", ",".join(needs_patch),
                ]
                if args.limit > 0:
                    patch_args += ["--limit", str(args.limit)]

                run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_c_writer.py", patch_args)
                run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_d_validator.py", [])

        else:
            # ── Full 생성 모드 (또는 --features 수동 지정 모드) ───────────
            stage_args = []
            if args.limit > 0:
                stage_args += ["--limit", str(args.limit)]
            if args.features:
                stage_args += ["--features", args.features]

            run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_a_classifier.py", [])
            run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_b_mapper.py", stage_args)
            run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_c_writer.py", stage_args)
            run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_d_validator.py", [])

        # ── Phase 3: 렌더링 (Tier별 무조건 실행) ─────────────────────────
        print(f"\n--- [Phase 3] Docusaurus Rendering for {current_tier} ---")
        render_args = ["--tier", current_tier]
        run_script(PROJECT_ROOT / "src" / "03_render" / "md_renderer.py", render_args)
        run_script(PROJECT_ROOT / "src" / "03_render" / "sidebar_generator.py", render_args)

    print("\n✅ DALi Documentation Pipeline Execution Completed!")


if __name__ == "__main__":
    main()
