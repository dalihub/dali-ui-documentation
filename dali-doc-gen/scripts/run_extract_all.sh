#!/bin/bash

# ============================================================
# DALi Guide Doc System - Full Pipeline (Phase 1 + Phase 2)
# ============================================================
#
# [사용법]
#   ./scripts/run_extract_all.sh
#
# [Phase 2 처리 범위 조정 방법]
#   아래의 STAGE_B_LIMIT, STAGE_C_LIMIT 값을 변경하세요.
#   0 = 전체 처리 (모든 Feature 클러스터)
#   N = 처음 N개의 클러스터만 처리 (빠른 테스트용)
#   예시: STAGE_B_LIMIT=5  →  5개 Feature만 목차 생성
#
# [RPM(분당 요청 수) 조정 방법]
#   config/doc_config.yaml 파일에서 아래 값을 바꾸세요:
#     rate_limit_delay_sec: 6   ← 이 숫자를 조정
#   계산식: delay = 60 / RPM_한도
#   예) 분당 10회 → 60/10 = 6초, 분당 15회 → 60/15 = 4초
#   단, 실제 서버의 정확한 RPM 한도를 모를 경우 여유있게 설정하세요.
#
# [사내/사외 LLM 모델 전환 방법]
#   config/doc_config.yaml 에서 llm_environment 값을 변경하세요:
#     llm_environment: "external"  ← "internal" 또는 "external"
# ============================================================

# ▼▼▼ Phase 2 처리 개수 조정 (0 = 제한 없음) ▼▼▼
STAGE_B_LIMIT=3
STAGE_C_LIMIT=3
# ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲

set -e

# GEMINI_API_KEY 환경변수 확인
if [ -z "$GEMINI_API_KEY" ] && [ -z "$INTERNAL_API_KEY" ]; then
    echo "⚠️  경고: GEMINI_API_KEY 또는 INTERNAL_API_KEY 환경 변수가 설정되지 않았습니다."
    echo "   export GEMINI_API_KEY=<your_key> 후 다시 실행하거나, .env 파일을 생성하세요."
fi

echo "=========================================================="
echo "   DALi Guide Doc System - Phase 1 + Phase 2 Full Run    "
echo "=========================================================="

# --- PHASE 1 ---

# 1. 가상 환경 설정 및 패키지 설치
echo -e "\n[Phase1 1/6] Preparing Python Environment..."
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt --quiet
echo "Environment ready."

# 2. 저장소 Clone 및 Pull
echo -e "\n[Phase1 2/6] Cloning/Pulling Repositories..."
python src/00_extract/repo_manager.py

# 3. Doxygen XML 생성
echo -e "\n[Phase1 3/6] Generating Doxygen XML (This may take a few minutes)..."
PACKAGES=("dali-core" "dali-adaptor" "dali-ui")
for pkg in "${PACKAGES[@]}"; do
    echo "  > Generating XML for $pkg..."
    python src/00_extract/doxygen_runner.py --package "$pkg"
done

# 4. XML 데이터 파싱
echo -e "\n[Phase1 4/6] Parsing XMLs to structured JSONs..."
echo "  > Structuring API JSONs (doxygen_parser.py)..."
python src/00_extract/doxygen_parser.py
echo "  > Extracting Call Graphs (callgraph_parser.py)..."
python src/00_extract/callgraph_parser.py

# 5. Git Diff 변경 감지
echo -e "\n[Phase1 5/6] Detecting API changes (Git Diff)..."
python src/00_extract/diff_detector.py --from-commit HEAD~1 --to-commit HEAD

# 6. Feature 클러스터링
echo -e "\n[Phase1 6/6] Feature Clustering..."
python src/01_cluster/feature_clusterer.py

echo -e "\n✅ Phase 1 Complete."

# --- PHASE 1.5 ---

echo -e "\n=========================================================="
echo "   Phase 1.5: Feature Taxonomy Review                     "
echo "=========================================================="

# 7. Taxonomy Review: LLM이 상속 계층 Tree 구조 여부 결정
# --full 옵션: 기존 taxonomy 무시하고 전체 재검토 (최초 1회 권장)
# 옵션 없음:   기존 taxonomy 로드 후 신규/변경 feature만 재검토 (증분)
echo -e "\n[Phase1.5 1/1] Taxonomy Review: Determining tree/flat structure..."
if [ "${TAXONOMY_FULL_REVIEW:-0}" = "1" ]; then
    echo "  > Full review mode (TAXONOMY_FULL_REVIEW=1)"
    python src/01_cluster/taxonomy_reviewer.py --full
else
    python src/01_cluster/taxonomy_reviewer.py
fi

echo -e "\n✅ Phase 1.5 Complete. Taxonomy saved to cache/feature_taxonomy/"

# --- PHASE 2 ---

echo -e "\n=========================================================="
echo "   Phase 2: LLM Pipeline                                  "
echo "=========================================================="

# 7. Stage A: 모호한 API 분류 (LLM Think 모델)
echo -e "\n[Phase2 1/3] Stage A: Classifying ambiguous API clusters..."
python src/02_llm/stage_a_classifier.py

# 8. Stage B: 문서 목차/뼈대 설계 (LLM Think 모델)
echo -e "\n[Phase2 2/3] Stage B: Generating document blueprints (TOC)..."
if [ "$STAGE_B_LIMIT" -gt 0 ]; then
    echo "  > Test mode: processing only first $STAGE_B_LIMIT clusters."
    python src/02_llm/stage_b_mapper.py --limit "$STAGE_B_LIMIT"
else
    python src/02_llm/stage_b_mapper.py
fi

# 9. Stage C: Markdown 문서 본문 작성 (LLM Instruct 모델)
echo -e "\n[Phase2 3/3] Stage C: Writing Markdown documentation drafts..."
if [ "$STAGE_C_LIMIT" -gt 0 ]; then
    echo "  > Test mode: processing only first $STAGE_C_LIMIT clusters."
    python src/02_llm/stage_c_writer.py --limit "$STAGE_C_LIMIT"
else
    python src/02_llm/stage_c_writer.py
fi

# 9.5. Stage D: Hallucination 검증 + FAIL 문서 자동 재생성 (Retry Loop)
echo -e "\n[Phase2 +] Stage D: Validating generated documents for hallucinations..."
# 빠른 테스트 시에는 --no-retry 플래그 추가 가능 (LLM 재생성 루프 건너뜀)
python src/02_llm/stage_d_validator.py

# 10. Stage E: Index.md 생성 (validated_drafts/ 기준)
echo -e "\n[Phase2 +] Stage E: Generating documentation Index.md..."
python src/03_render/index_generator.py

echo -e "\n=========================================================="
echo " ✅ Full Pipeline Complete! (Phase 1 + Phase 1.5 + Phase 2)"
echo " - Parsed data  : cache/parsed_doxygen/"
echo " - Feature map  : cache/feature_map/"
echo " - Taxonomy     : cache/feature_taxonomy/"
echo " - MD drafts    : cache/markdown_drafts/"
echo " - Index        : cache/markdown_drafts/Index.md"
echo "=========================================================="
