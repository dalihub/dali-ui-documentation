# [Phase 3] 렌더링 및 CI/CD 파이프라인 통합 아키텍처

Phase 3의 핵심 목표는 생성된 검증용 마크다운 초안들을 **Docusaurus v3 스펙에 맞는 최종 산출물로 렌더링**하고, 이를 `app-guide`와 `platform-guide`로 완벽히 분리해 배포하는 **오케스트레이션 파이프라인(pipeline)**을 구축하는 것입니다.

---

## Proposed Changes

### 1. 전체 오케스트레이터 (`pipeline.py`)

- **역할**: 기존 쉘 스크립트(`run_extract_all.sh`)를 대체하는 단계별 제어기. `--tier`와 `--mode`에 따른 흐름을 관장합니다.

#### [NEW] [pipeline.py](file:///home/bshsqa/Shared/DALi/dali-guide/dali-doc-gen/src/pipeline.py)
- `--mode [full|update]`: 최초 전체 생성 모드인지, 증분 업데이트 모드인지 분기.
- `--tier [app|platform|all]`: 생성 타겟 독자층 지정. (기본값: `app`)
- **업데이트/무효화(Invalidation) 전략**: 
  - `--mode update` 시 `taxonomy_reviewer`가 비교한 구조 정보를 받습니다.
  - 구조(Tree/Flat 전환, Child 노드 추가)가 변경된 Feature 그룹을 색출합니다.
  - 해당 그룹의 `validated_drafts/` 마크다운을 자동 삭제(`os.remove`)하여 강제로 Stage C가 작동하게끔 합니다(최초 생성과 동일하게 회귀).
  - 내용만 바뀐 경우는 `changed_apis.json`과 기존 `.md`를 묶어 LLM에 반영(Patch)을 요청합니다.

---

### 2. 마크다운 렌더러 (`md_renderer.py`)

- **역할**: `validated_drafts/`의 순수 마크다운 파일에 Docusaurus용 YAML Frontmatter를 주입하고, **더미 Doxygen 링크 삽입**, 그리고 **문서 간 자동 교차 링크(Cross-linking)**를 처리합니다.

#### [NEW] [md_renderer.py](file:///home/bshsqa/Shared/DALi/dali-guide/dali-doc-gen/src/03_render/md_renderer.py)
- Jinja2 템플릿을 사용하여 Frontmatter 주입:
  ```yaml
  ---
  id: feature-name
  title: Feature Display Name
  sidebar_position: 1
  ...
  ---
  ```
- **Tier 필터링 안전장치**: `--tier app`일 때 `devel-api`가 포함되지 않도록 점검.
- **문서 간 자동 교차 링크 (Cross-Linking)**: 
  - `feature_taxonomy.json`의 모든 `display_name`(예: "ImageView", "ScrollView") 목록을 로드합니다.
  - 마크다운 본문 텍스트 내에서 해당 단어가 등장하면 Docusaurus 내부 링크로 치환합니다.
  - *안전장치*: 기계적인 텍스트 변환 시 코딩 블록(` ``` `) 내부나 이미 마크다운 링크로 묶인 경우(`[text](url)`)는 치환을 무시하도록 정규식을 짭니다.
- **더미 Doxygen 링크 삽입**: 문서 최하단에 임시로 설정한 더미 Doxygen 웹 주소(예: `https://dummy-doxygen.tizen.org/feature-name`)를 가리키는 하이퍼링크 블록을 자동 생성해 붙여넣습니다.

---

### 3. 사이드바 생성기 (`sidebar_generator.py`)

- **역할**: 생성된 마크다운 파일들의 위치와 `feature_taxonomy.json`을 기반으로 Docusaurus v3 내비게이션 요소인 `sidebar.json`을 만듭니다.

#### [NEW] [sidebar_generator.py](file:///home/bshsqa/Shared/DALi/dali-guide/dali-doc-gen/src/03_render/sidebar_generator.py)
- **계층형 JSON 포맷팅**: `feature_taxonomy.json`의 Tree 구조를 순회하여 부모 카테고리(category) 밑에 자식(doc)들을 매달아 줍니다.
  ```json
  [
    {
      "type": "category",
      "label": "View (Base UI Object)",
      "items": [
        {"type": "doc", "id": "view/index"},
        {"type": "doc", "id": "view/image-view"},
        {"type": "doc", "id": "view/label"}
      ]
    }
  ]
  ```

---

### 4. GitHub Actions 워크플로우 `.github/workflows/`

- **역할**: 주간 단위 `update` 및 필요할 때 수동으로 전체 `full` 생성을 할 수 있는 CI/CD 잡입니다.

#### [NEW] [weekly-update.yml](file:///home/bshsqa/Shared/DALi/dali-guide/dali-doc-gen/.github/workflows/weekly-update.yml)
- 매주 월요일 새벽에 `python src/pipeline.py --mode update --tier all`을 백그라운드에서 실행하고, 결과물을 PR(Pull Request)로 띄웁니다.

#### [NEW] [initial-full-gen.yml](file:///home/bshsqa/Shared/DALi/dali-guide/dali-doc-gen/.github/workflows/initial-full-gen.yml)
- `--tier [app|platform|all]` 파라미터를 받아 수동 트리거(workflow_dispatch)로 전체 생성 파이프라인을 구동합니다.

---

## Verification Plan

### Automated Tests
1. `python src/pipeline.py --mode full --tier app` 실행 후, `output/app-guide/` 하위에 Frontmatter가 포함된 마크다운과 정상적인 `sidebar.json` 패키징이 성공하는지 확인.
2. `diff_detector` 모킹을 통해 Tree 구조가 강제로 변경되었을 때, `pipeline.py --mode update`가 해당 문서를 성공적으로 삭제(Invalidate)하고 다시 생성하는지 확인.

### Manual Verification
해당 코드를 Docusaurus 로컬 인스턴스에 복사하여 `npm run start`를 띄워, 사이드바 메뉴 간의 상하 이동 및 링크 오류가 없는지 직접 확인합니다.
