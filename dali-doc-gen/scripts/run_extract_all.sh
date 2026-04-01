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

# ▼▼▼ 테스트 대상 Feature 목록 (비워두면 전체) ▼▼▼
TARGET_FEATURES="view,image-view"
LIMIT=3
# ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲

set -e

echo "=========================================================="
echo "   [TEST HARNESS] Incremental Update E2E Simulation       "
echo "=========================================================="

if [ -z "$GEMINI_API_KEY" ] && [ -z "$INTERNAL_API_KEY" ]; then
    echo "⚠️  경고: GEMINI_API_KEY 변수가 없습니다."
fi

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt --quiet

# 파이프라인 인자 조립 (repo_manager 실행을 막기 위해 --skip-pull 추가)
PIPELINE_ARGS="--tier app --limit $LIMIT --skip-pull"
if [ -n "$TARGET_FEATURES" ]; then
    PIPELINE_ARGS="$PIPELINE_ARGS --features $TARGET_FEATURES"
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

echo -e "\n[Step 2] 구버전 바탕으로 최초 전체 생성 (mode: full) 실행"
echo "  > Running: python src/pipeline.py --mode full $PIPELINE_ARGS"
python src/pipeline.py --mode full $PIPELINE_ARGS

echo -e "\n[Step 3] 생성된 Output 폴더를 output_prev로 백업"
rm -rf output_prev
if [ -d "output" ]; then
    cp -r output output_prev
    echo "  > 백업 완료: output_prev 폴더 생성"
fi

echo -e "\n[Step 4] 소스코드를 최신 상태로 복구 (HEAD)"
for pkg in "${PACKAGES[@]}"; do
    echo "  > Updating $pkg to latest HEAD..."
    cd "repos/$pkg"
    # dali-ui는 devel, 나머지는 master
    if [ "$pkg" == "dali-ui" ]; then
        git checkout devel || true
    else
        git checkout master || true
    fi
    git pull
    cd ../..
done

echo -e "\n[Step 4.5] 변경 감지 (HEAD~30 .. HEAD)"
echo "  > Running: python src/00_extract/diff_detector.py --from-commit HEAD~30 --to-commit HEAD"
python src/00_extract/diff_detector.py --from-commit HEAD~30 --to-commit HEAD

echo -e "\n[Step 5] 최신 소스 바탕으로 증분 업데이트 (mode: update) 실행"
echo "  > Running: python src/pipeline.py --mode update $PIPELINE_ARGS"
python src/pipeline.py --mode update $PIPELINE_ARGS

echo -e "\n=========================================================="
echo " 🎉 E2E 시뮬레이션(롤백-업데이트) 종료!"
echo " 현재 output/ 폴더와 백업된 output_prev/ 폴더를 비교해 보세요."
echo " >> diff -r output_prev/app-guide/docs output/app-guide/docs"
echo "=========================================================="
