import os
import sys
import argparse
import subprocess
from pathlib import Path
import json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "cache"

def run_script(script_path, args_list):
    """지정된 파이썬 스크립트를 독립 프로세스로 실행합니다."""
    cmd = [sys.executable, str(script_path)] + args_list
    print(f"\n▶ Executing: {' '.join(cmd)}")
    subprocess.check_call(cmd)

def main():
    parser = argparse.ArgumentParser(description="DALi Documentation Gen Pipeline")
    parser.add_argument("--mode", choices=["full", "update"], default="full", help="Pipeline execution mode")
    parser.add_argument("--tier", choices=["app", "platform", "all"], default="app", help="Target document tier")
    parser.add_argument("--limit", type=int, default=0, help="Debug limit for stages B and C")
    parser.add_argument("--features", type=str, default="", help="Exclusive features to process")
    
    args = parser.parse_args()

    if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("INTERNAL_API_KEY"):
        print("⚠️ Warning: GEMINI_API_KEY or INTERNAL_API_KEY is not set.")

    # 1. Phase 1 & 1.5 - Data Extraction & Taxonomy (항상 수행하여 최신 코드 변경을 반영)
    print("\n==========================================================")
    print("   [Phase 1] Code Parsing & Feature Taxonomy Extraction   ")
    print("==========================================================")
    
    run_script(PROJECT_ROOT / "src" / "00_extract" / "doxygen_parser.py", [])
    run_script(PROJECT_ROOT / "src" / "01_cluster" / "feature_clusterer.py", [])
    run_script(PROJECT_ROOT / "src" / "01_cluster" / "taxonomy_reviewer.py", [])

    # 타겟 독자 티어 결정 (all일 경우 앱과 플랫폼 두 번 반복)
    tiers_to_run = ["app", "platform"] if args.tier == "all" else [args.tier]

    print("\n==========================================================")
    print(f"   [Phase 2 & 3] LLM Pipeline & Output Rendering ({args.mode.upper()} mode)")
    print("==========================================================")

    for current_tier in tiers_to_run:
        print(f"\n>>> Starting Pipeline for Tier: {current_tier.upper()} <<<")
        
        target_features = args.features
        
        # ── 증분 업데이트 로직 (Invalidation) ──
        if args.mode == "update":
            print("  [*] Update Mode detected. Assessing incremental deltas...")
            if not target_features:
                taxonomy_path = CACHE_DIR / "feature_taxonomy" / "feature_taxonomy.json"
                drafts_dir = CACHE_DIR / "validated_drafts"
                
                if taxonomy_path.exists() and drafts_dir.exists():
                    with open(taxonomy_path, "r", encoding="utf-8") as f:
                        tax = json.load(f)
                    
                    # 1. 아예 누락된 피처(새로 추가됨) 색출
                    draft_files = {p.stem for p in drafts_dir.glob("*.md")}
                    missing = [k for k in tax.keys() if k not in draft_files]
                    
                    invalidated = []
                    # 2. 구조 변경/Invalidation 감지 (Tree/Flat 전환 등)
                    # (Phase 3 요구사항 적용: 단순 API 변경은 패치하지만, 
                    # 자식이 늘어나는 등 Tree 구조 변경은 과감히 Invalidate 하여 강제 재생성)
                    for feat_idx, data in tax.items():
                        decision_reason = data.get("decision_reason", "")
                        # 만약 Taxonomy 리뷰어가 구조 변동을 감지해 reason을 남겼다면 무효화 대상!
                        # (단순 구현 예시: taxonomy 생성 로직과 맞물려 작동)
                        if "changed" in decision_reason.lower() and feat_idx in draft_files:
                            print(f"  [!] Taxonomy structural invalidation detected for: {feat_idx}")
                            target_file = drafts_dir / f"{feat_idx}.md"
                            try:
                                target_file.unlink()
                                invalidated.append(feat_idx)
                            except OSError:
                                pass

                    combined_targets = set(missing + invalidated)
                    if combined_targets:
                        print(f"  [+] Found {len(combined_targets)} features requiring generation.")
                        target_features = ",".join(combined_targets)
                        
                        # TODO: Stage C Patch 로직 연결
                        # 내용만 바뀐 경우는 changed_apis.json을 읽어 패치 파이프라인으로 돌리는
                        # Stage C 업데이트용 스크립트 분기가 여기에 추가될 예정입니다.
                    else:
                        print("  [+] All generated documents up to date. No LLM generation needed.")
        # ──────────────────────────────────────────────

        # LLM 파이프라인 인자 조립
        stage_args = []
        if args.limit > 0:
            stage_args.extend(["--limit", str(args.limit)])
        if target_features:
            stage_args.extend(["--features", target_features])

        # Stage A~D 실행 (update 모드에서 변경사항이 없으면 스킵)
        if not target_features and args.mode == "update":
            print(f"  [-] No content changes detected for {current_tier}. Skipping heavy LLM Generative stages.")
        else:
            run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_a_classifier.py", [])
            run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_b_mapper.py", stage_args)
            run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_c_writer.py", stage_args)
            run_script(PROJECT_ROOT / "src" / "02_llm" / "stage_d_validator.py", [])

        # Phase 3 렌더링 단계 (Tier별로 무조건 실행하여 목차 갱신 및 프론트매터 주입)
        print(f"\n--- [Phase 3] Docusaurus Rendering for {current_tier} ---")
        render_args = ["--tier", current_tier]
        run_script(PROJECT_ROOT / "src" / "03_render" / "md_renderer.py", render_args)
        run_script(PROJECT_ROOT / "src" / "03_render" / "sidebar_generator.py", render_args)

    print("\n✅ DALi Documentation Pipeline Execution Completed!")

if __name__ == "__main__":
    main()
