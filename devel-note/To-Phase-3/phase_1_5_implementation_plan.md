# Implementation Plan - Phase 1.5: Feature Taxonomy & View Architecture

## Goal Description
Phase 1 (정적 분석) 과 Phase 2 (LLM 파이프라인) 사이에 **Phase 1.5 (Feature Taxonomy 설계)** 단계를 추가합니다.
이를 통해:
1. View를 독립 Feature로 강제 주입하고, Actor 대비 View 중심의 문서를 생성
2. dali-ui의 View 하위 클래스들(ImageView, Label, ScrollView 등)의 Tree 구조 여부를 LLM이 판단
3. 판단 결과를 `feature_taxonomy.json`에 영속화하여 증분 업데이트 시 재활용

---

## Proposed Changes

### 1. `config/repo_config.yaml` 수정
- `manual_features` 항목 추가
- View를 강제 Feature로 주입할 패키지와 기준 클래스 명시

---

### 2. `src/00_extract/doxygen_parser.py` 수정
- **[MODIFY]** 기존 파싱에 `base_class`(부모), `derived_classes`(자식) 필드 추가
- Doxygen XML의 `<basecompoundref>` / `<derivedcompoundref>` 태그에서 추출

---

### 3. `src/01_cluster/feature_clusterer.py` 수정
- **[MODIFY]** `repo_config.yaml`의 `manual_features`를 읽어 강제 Feature 삽입 로직 추가
- View 클래스들이 여기서 `view` Feature로 강제 분류

---

### 4. `src/01_cluster/taxonomy_reviewer.py` 신규 작성
- **[NEW]** LLM(Think)에게 상속 계층을 전달하고 Tree 구조 여부 판단 요청
- 결과를 `cache/feature_taxonomy/feature_taxonomy.json`으로 저장
- 증분 모드: 기존 taxonomy 로드 후 신규/변경 클래스만 LLM 재검토

---

### 5. `scripts/run_extract_all.sh` 수정
- Phase 1.5 단계 (taxonomy_reviewer.py) 실행 스텝 추가

---

### 6. Stage B/C 프롬프트 — View/Actor 비중 조정 강화
- Stage B: taxonomy에서 Tree 구조로 지정된 Feature는 부모-자식 관계를 TOC에 반영
- Stage C: `view`, `image-view` 등 View 계열 Feature에는 더 강화된 View 중심 컨텍스트 주입

---

## Verification Plan
1. `repo_config.yaml` manual_features 적용 → `feature_map.json`에 `view` Feature 존재 확인
2. `doxygen_parser.py` 실행 → 주요 클래스에 `derived_classes` 필드 확인
3. `taxonomy_reviewer.py` → `feature_taxonomy.json` 생성 및 Tree/Flat 판단 결과 검토
4. `run_extract_all.sh` 전체 실행 → Phase 1.5 스텝 포함 완주 확인
