# DALi Documentation Generator

DALi C++ 그래픽 라이브러리(`dali-core`, `dali-adaptor`, `dali-ui`)의 API 소스에서
Docusaurus용 Markdown 가이드 문서를 자동으로 생성하는 파이프라인.

---

## 환경 준비

```bash
cd dali-doc-gen
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

LLM API 키 설정 (둘 중 하나):

```bash
export GEMINI_API_KEY=<your-key>
# 또는
export INTERNAL_API_KEY=<your-key>
```

---

## 전체 파이프라인 실행 (빠른 시작)

```bash
# 전체 새로 생성 (app-guide + platform-guide)
python src/pipeline.py --mode full --tier all

# 특정 티어만
python src/pipeline.py --mode full --tier app

# 일부 feature만 (디버깅용)
python src/pipeline.py --mode full --tier app --features "view,image-view"

# 주간 증분 업데이트
python src/pipeline.py --mode update --tier app
```

옵션 요약:

| 옵션 | 값 | 설명 |
|------|----|------|
| `--mode` | `full` / `update` | 전체 생성 또는 증분 업데이트 |
| `--tier` | `app` / `platform` / `all` | 출력 대상 독자 티어 |
| `--features` | `"feat1,feat2"` | 처리할 feature를 직접 지정 (디버깅용) |
| `--limit` | 숫자 | Stage B/C에서 처리할 feature 수 제한 (디버깅용) |
| `--skip-pull` | - | repo_manager git pull 생략 (로컬 테스트용) |

---

## 스크립트 단계별 직접 실행

파이프라인을 처음부터 단계별로 검증하거나 특정 단계만 재실행할 때 사용.
**모든 명령은 `dali-doc-gen/` 디렉토리에서 실행.**

### Phase 0 — 코드 추출 및 정적 분석

#### Step 1: 저장소 클론/업데이트

```bash
python src/00_extract/repo_manager.py
```

- `config/repo_config.yaml`에 정의된 3개 저장소를 `repos/` 아래에 clone 또는 pull.
- 출력: `repos/dali-core/`, `repos/dali-adaptor/`, `repos/dali-ui/`

---

#### Step 2: Doxygen XML 생성

패키지 3개를 각각 실행:

```bash
python src/00_extract/doxygen_runner.py --package dali-core
python src/00_extract/doxygen_runner.py --package dali-adaptor
python src/00_extract/doxygen_runner.py --package dali-ui
```

- 각 패키지의 헤더 파일에서 Doxygen XML을 생성 (`CALL_GRAPH=YES` 포함).
- `doxygen` 바이너리가 PATH에 있어야 함.
- 출력: `cache/doxygen_json/<package>/xml/`

---

#### Step 3: Doxygen XML → 경량 JSON 변환

```bash
python src/00_extract/doxygen_parser.py
```

- `cache/doxygen_json/` 하위의 XML을 파싱하여 토큰 절약형 JSON으로 변환.
- private 멤버, 내부 구현 클래스 등은 필터링.
- 출력: `cache/parsed_doxygen/dali-core.json`, `dali-adaptor.json`, `dali-ui.json`

---

#### Step 4: Call Graph 파싱

```bash
python src/00_extract/callgraph_parser.py
```

- Doxygen XML에서 함수 호출 관계를 추출.
- 출력: `cache/callgraph_json/`

---

#### Step 5: 변경 API 감지 (update 모드 전용)

```bash
# 기본: 최근 5커밋 기준
python src/00_extract/diff_detector.py

# 커밋 범위 지정
python src/00_extract/diff_detector.py --from-commit v1.0.0 --to-commit HEAD

# 특정 패키지만
python src/00_extract/diff_detector.py --from-commit HEAD~3 --to-commit HEAD --package dali-core
```

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--from-commit` | `HEAD~5` | 비교 시작 커밋 또는 태그 |
| `--to-commit` | `HEAD` | 비교 끝 커밋 또는 태그 |
| `--package` | (전체) | 특정 패키지만 검사 |

- `cache/parsed_doxygen/*.json`이 미리 생성되어 있어야 함 (Step 3 선행 필요).
- 출력: `cache/changed_apis.json`
- **주의**: `pipeline.py`는 이 스크립트를 자동으로 호출하지 않음. `--mode update` 전에 수동으로 실행 필요.

---

### Phase 1 — Feature 클러스터링 및 Taxonomy 설계

#### Step 6: Feature 클러스터링

```bash
python src/01_cluster/feature_clusterer.py
```

- `cache/parsed_doxygen/` + `cache/callgraph_json/`을 읽어 API들을 Feature 단위로 묶음.
- 1차: 디렉토리/네임스페이스 기반 그룹화
- 2차: Call Graph 밀도 기반 병합
- `config/repo_config.yaml`의 `manual_features` 오버라이드 적용.
- 출력: `cache/feature_map/feature_map.json`

---

#### Step 7: Taxonomy 설계 (LLM Think 모델 사용)

```bash
# 증분 모드 (기본): 기존 taxonomy 보존, 신규/변경 Feature만 재검토
python src/01_cluster/taxonomy_reviewer.py

# 전체 재검토 모드: 기존 taxonomy 무시하고 처음부터
python src/01_cluster/taxonomy_reviewer.py --full
```

- 상속 계층을 분석하여 Tree 구조(부모-자식 문서) vs Flat(단일 문서) 결정.
- 판단 기준: 독립 사용 가능한 서브클래스가 3개 이상이면 Tree.
- 출력: `cache/feature_taxonomy/feature_taxonomy.json`

---

### Phase 2 — LLM 문서 생성 (4단계)

#### Step 8: Stage A — Feature 분류 보정 (LLM Think)

```bash
python src/02_llm/stage_a_classifier.py
```

- `cache/feature_map/feature_map.json`을 읽어 모호한 API-Feature 경계를 LLM으로 정리.
- 출력: `cache/feature_map/feature_map_classified.json`

---

#### Step 9: Stage B — TOC 설계 (LLM Think)

```bash
# 전체 feature
python src/02_llm/stage_b_mapper.py

# 특정 feature만
python src/02_llm/stage_b_mapper.py --features "view,image-view"

# 처음 N개만 처리 (디버깅)
python src/02_llm/stage_b_mapper.py --limit 3
```

| 옵션 | 설명 |
|------|------|
| `--features` | 처리할 feature 이름 (쉼표 구분) |
| `--limit` | 처리할 최대 feature 수 |

- 각 Feature의 문서 구조(섹션, 학습 순서)를 설계.
- 출력: `cache/doc_blueprints/stage_b_blueprints.json`
- **주의**: `--features`로 일부만 실행하면 blueprints.json이 해당 feature만으로 덮어써짐. Stage C도 동일 `--features`로 실행할 것.

---

#### Step 10: Stage C — Markdown 초안 작성 (LLM Instruct)

```bash
# 전체 feature 새로 작성
python src/02_llm/stage_c_writer.py

# 특정 feature만
python src/02_llm/stage_c_writer.py --features "view,image-view"

# 처음 N개만 처리 (디버깅)
python src/02_llm/stage_c_writer.py --limit 3

# 패치 모드: 기존 문서 유지 + 변경 API 부분만 업데이트
python src/02_llm/stage_c_writer.py --patch --patch-features "view,image-view"
```

| 옵션 | 설명 |
|------|------|
| `--features` | 전체 생성 모드에서 처리할 feature 지정 |
| `--limit` | 처리할 최대 feature 수 |
| `--patch` | 패치 모드 활성화 |
| `--patch-features` | 패치 모드에서 처리할 feature 지정 (`--patch`와 함께 사용) |

- Stage B blueprints를 읽어 Doxygen API spec을 참조하며 Markdown 작성.
- 패치 모드는 `cache/validated_drafts/<feat>.md`가 존재해야 동작.
- 출력: `cache/markdown_drafts/<feature>.md`

---

#### Step 11: Stage D — 할루시네이션 검증 (LLM Think)

```bash
# 기본 실행
python src/02_llm/stage_d_validator.py

# LLM 검토 없이 정적 검증만
python src/02_llm/stage_d_validator.py --no-llm

# 자동 재생성 없이 검증만
python src/02_llm/stage_d_validator.py --no-retry
```

| 옵션 | 설명 |
|------|------|
| `--no-llm` | FAIL 문서 LLM 재검토 생략 |
| `--no-retry` | FAIL 문서 자동 재생성 루프 생략 |

- `cache/markdown_drafts/*.md` 전체를 Doxygen DB와 심볼 대조.
- 판정: PASS(≥60%), WARN(≥35%), FAIL(<35%)
- FAIL은 최대 2회 자동 재생성 후 재판정.
- 출력: `cache/validated_drafts/`, `cache/validation_report/stage_d_report.json`

---

### Phase 3 — Markdown 렌더링

#### Step 12: Frontmatter 및 링크 렌더링

```bash
python src/03_render/md_renderer.py --tier app
python src/03_render/md_renderer.py --tier platform
```

- `cache/validated_drafts/`의 문서에 YAML Frontmatter, 내부 링크, SEO 메타데이터 추가.
- 출력: `output/app-guide/docs/` 또는 `output/platform-guide/docs/`

---

#### Step 13: Docusaurus 사이드바 생성

```bash
python src/03_render/sidebar_generator.py --tier app
python src/03_render/sidebar_generator.py --tier platform
```

- taxonomy 구조를 기반으로 Docusaurus 네비게이션 JSON 생성.
- 출력: `output/app-guide/sidebar.json` 또는 `output/platform-guide/sidebar.json`

---

## 캐시 디렉토리 구조

```
cache/
├── doxygen_json/          # Step 2 출력: Doxygen raw XML
├── parsed_doxygen/        # Step 3 출력: 경량 JSON (dali-core.json 등)
├── callgraph_json/        # Step 4 출력: 함수 호출 관계
├── changed_apis.json      # Step 5 출력: 변경 API 목록
├── feature_map/
│   ├── feature_map.json           # Step 6 출력
│   └── feature_map_classified.json # Step 8 출력
├── feature_taxonomy/
│   ├── feature_taxonomy.json      # Step 7 출력
│   └── feature_taxonomy.json.old  # update 모드 시 자동 백업
├── doc_blueprints/
│   └── stage_b_blueprints.json    # Step 9 출력
├── markdown_drafts/       # Step 10 출력: LLM 초안 (*.md)
├── validated_drafts/      # Step 11 출력: 검증 완료 초안 (*.md)
└── validation_report/
    └── stage_d_report.json        # Step 11 검증 리포트
```

---

## 단계별 테스트 예시

### Phase 0만 빠르게 검증

```bash
# Step 1~4를 순서대로 실행
python src/00_extract/repo_manager.py
python src/00_extract/doxygen_runner.py --package dali-core
python src/00_extract/doxygen_parser.py
python src/00_extract/callgraph_parser.py

# JSON 출력 확인
ls cache/parsed_doxygen/
```

### 특정 feature 2개로 전체 파이프라인 검증

```bash
# Phase 0~1
python src/00_extract/repo_manager.py
python src/00_extract/doxygen_runner.py --package dali-core
python src/00_extract/doxygen_runner.py --package dali-adaptor
python src/00_extract/doxygen_runner.py --package dali-ui
python src/00_extract/doxygen_parser.py
python src/00_extract/callgraph_parser.py
python src/01_cluster/feature_clusterer.py
python src/01_cluster/taxonomy_reviewer.py

# Phase 2 (view, image-view 2개만)
python src/02_llm/stage_a_classifier.py
python src/02_llm/stage_b_mapper.py --features "view,image-view"
python src/02_llm/stage_c_writer.py --features "view,image-view"
python src/02_llm/stage_d_validator.py --no-retry

# Phase 3
python src/03_render/md_renderer.py --tier app
python src/03_render/sidebar_generator.py --tier app
```

### LLM 비용 없이 Stage D만 재실행

```bash
python src/02_llm/stage_d_validator.py --no-llm --no-retry
```

---

## 알려진 주의사항

- **`diff_detector.py`는 `pipeline.py`에서 자동 호출되지 않음.** `--mode update` 실행 전에 수동으로 실행해야 `changed_apis.json`이 생성되어 패치 모드가 동작함.
- **`--mode full`은 캐시를 재사용하지 않음.** Phase 0부터 모든 단계를 처음부터 재실행함.
- **Stage B를 `--features`로 일부만 실행하면 blueprints.json이 해당 feature만으로 덮어써짐.** 이후 Stage C도 반드시 동일한 `--features` 옵션으로 실행할 것.
