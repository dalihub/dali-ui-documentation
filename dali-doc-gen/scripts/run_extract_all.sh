#!/bin/bash

# 종료 시 에러 발생 시 즉시 중단되도록 설정
set -e

echo "=========================================================="
echo "      DALi Guide Doc System - Phase 1 Extract All         "
echo "=========================================================="

# 1. 가상 환경 설정 및 패키지 설치
echo "[1/6] Preparing Python Environment..."
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# 가상 환경 활성화
source venv/bin/activate
pip install -r requirements.txt --quiet
echo "Environment ready."

# 2. 저장소 Clone 및 Pull (repo_manager.py)
echo -e "\n[2/6] Cloning/Pulling Repositories..."
python src/00_extract/repo_manager.py

# 3. Doxygen XML 생성 (doxygen_runner.py)
echo -e "\n[3/6] Generating Doxygen XML (This may take a few minutes)..."
PACKAGES=("dali-core" "dali-adaptor" "dali-ui")

for pkg in "${PACKAGES[@]}"; do
    echo "  > Generating XML for $pkg..."
    python src/00_extract/doxygen_runner.py --package "$pkg"
done

# 4. XML 데이터 파싱 (doxygen_parser & callgraph_parser)
echo -e "\n[4/6] Parsing XMLs to structured JSONs..."
echo "  > Structuring API JSONs (doxygen_parser.py)..."
python src/00_extract/doxygen_parser.py

echo "  > Extracting Call Graphs (callgraph_parser.py)..."
python src/00_extract/callgraph_parser.py

# 5. Git Diff 변경 감지 (diff_detector.py)
echo -e "\n[5/6] Detecting API changes (Git Diff)..."
# Using HEAD~1 as default delta boundary
python src/00_extract/diff_detector.py --from-commit HEAD~1 --to-commit HEAD

# 6. Feature 클러스터링 기반 형성 (feature_clusterer.py)
echo -e "\n[6/6] Grouping linked logic constructs (Feature Clustering)..."
python src/01_cluster/feature_clusterer.py

echo -e "\n=========================================================="
echo " ✅ Phase 1: All extraction, tracking, and clustering processes succeeded!"
echo " Result files are securely housed within: cache/"
echo "=========================================================="
