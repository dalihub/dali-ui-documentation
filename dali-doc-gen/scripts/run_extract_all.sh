#!/bin/bash

# ============================================================
# DALi Guide Doc - Incremental Update (Phase 3) Test Harness
# ============================================================
#
# 이 스크립트는 과거 커밋(약 30개 이전)으로 소스를 강제 롤백해 
# 최초 생성(full)을 가상으로 시뮬레이션하고,
# 다시 최신 커밋으로 당겨 증분 업데이트(update)가 어떤 차이를 
# 만들어내는지 E2E(End-to-End)로 실험할 수 있는 테스트 스크립트입니다.
# ============================================================

# ▼▼▼ 테스트 대상 Feature 목록 ▼▼▼
# update 모드에서는 needs_patch/needs_regen 결과를 이 목록으로 필터링함
# (증분 로직 자체는 전체 대상으로 동작, 처리 범위만 제한)
# 아래는 현재 HEAD~30..HEAD 기준 needs_patch 21개 중 대표 선별
TARGET_FEATURES="view,animation,image-view"
LIMIT=3
# ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲

set -e

echo "=========================================================="
echo "   [TEST HARNESS] Incremental Update E2E Simulation       "
echo "=========================================================="

# 스크립트 위치에 상관없이 dali-doc-gen/ 루트를 기준으로 경로 결정
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

if [ -z "$GEMINI_API_KEY" ] && [ -z "$INTERNAL_API_KEY" ]; then
    echo "⚠️  경고: GEMINI_API_KEY 변수가 없습니다."
fi

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt --quiet

# full 모드 인자: repo_manager 스킵 (수동으로 HEAD~30 세팅했으므로)
FULL_ARGS="--tier app --limit $LIMIT --skip-pull"
# update 모드 인자: --skip-pull 없음 → pipeline 내부에서 repo_manager가 최신화
UPDATE_ARGS="--tier app --limit $LIMIT"
# ※ platform-guide 생성이 필요하면 --tier platform 으로 별도 실행
if [ -n "$TARGET_FEATURES" ]; then
    FULL_ARGS="$FULL_ARGS --features $TARGET_FEATURES"
    UPDATE_ARGS="$UPDATE_ARGS --features $TARGET_FEATURES"
fi

PACKAGES=("dali-core" "dali-adaptor" "dali-ui")

echo -e "\n[Step 0] 로컬 저장소 확인 및 클론"
mkdir -p repos
for pkg in "${PACKAGES[@]}"; do
    if [ ! -d "repos/$pkg" ]; then
        echo "  > Cloning $pkg..."
        git clone "https://github.com/dalihub/$pkg.git" "repos/$pkg"
    fi
done

echo -e "\n[Step 1] 과거 시점으로 소스코드 통일 (HEAD~30)"
for pkg in "${PACKAGES[@]}"; do
    echo "  > Rewinding $pkg to HEAD~30..."
    cd "repos/$pkg"
    git reset --hard HEAD || true
    # dali-ui는 devel, 나머지는 master
    if [ "$pkg" == "dali-ui" ]; then
        git checkout devel || true
    else
        git checkout master || true
    fi
    git pull || true
    git checkout HEAD~30
    cd ../..
done

echo -e "\n[Step 2] 구버전 바탕으로 최초 전체 생성 (mode: full, --skip-pull)"
echo "  > Running: python3 src/pipeline.py --mode full $FULL_ARGS"
python3 src/pipeline.py --mode full $FULL_ARGS

echo -e "\n[Step 3] 생성된 Output 폴더를 output_prev로 백업"
# output은 이제 dali-guide/app-guide/ 에 위치 (dali-doc-gen 기준으로 ../app-guide/)
rm -rf ../app-guide_prev
if [ -d "../app-guide" ]; then
    cp -r ../app-guide ../app-guide_prev
    echo "  > 백업 완료: ../app-guide_prev/ (← ../app-guide 복사)"
fi

echo -e "\n[Step 4] 증분 업데이트 (mode: update)"
echo "  pipeline 내부에서 자동으로 수행:"
echo "    - repo_manager  : 최신 HEAD로 git pull"
echo "    - parsed_doxygen 백업 (HEAD~30 JSON → .old)"
echo "    - doxygen_parser: 최신 코드로 새 JSON 생성"
echo "    - diff_detector : .old vs 새 JSON 비교 → changed_apis.json"
echo "    - 이후 증분 업데이트 로직"
echo "  > Running: python3 src/pipeline.py --mode update $UPDATE_ARGS"
python3 src/pipeline.py --mode update $UPDATE_ARGS

echo -e "\n=========================================================="
echo " E2E 시뮬레이션(롤백-업데이트) 종료!"
echo " 백업된 ../app-guide_prev/ 와 최신 ../app-guide/ 를 비교해 보세요."
echo " >> diff -r ../app-guide_prev/docs ../app-guide/docs"
echo "=========================================================="
