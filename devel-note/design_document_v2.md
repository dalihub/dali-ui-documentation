# DALi UI 가이드 문서 자동 생성 시스템 — 설계 문서 v2

> **작성 기준:** ENH-24 구현 완료 + 품질 버그 수정 시점  
> **기준 커밋:** `21177ab` [ENH-24] Feature 재구조화 및 Taxonomy Tree 품질 개선  
> **v1 대비 주요 변경:** taxonomy_reviewer 전면 재설계, Stage D 폐기, Stage A/C 정확성 개선

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [요구사항](#2-요구사항)
3. [전체 시스템 구조](#3-전체-시스템-구조)
4. [파이프라인 실행 흐름](#4-파이프라인-실행-흐름)
5. [모듈별 상세 설명](#5-모듈별-상세-설명)
6. [핵심 데이터 파일](#6-핵심-데이터-파일)
7. [LLM 운용 전략](#7-llm-운용-전략)
8. [핵심 설계 결정](#8-핵심-설계-결정)
9. [CI/CD 및 운영](#9-cicd-및-운영)

---

## 1. 프로젝트 개요

DALi(Dynamic Animation Library) C++ 라이브러리를 분석하여, **앱 개발자** 및 **플랫폼 개발자**가 실제 업무에 활용할 수 있는 수준의 가이드 문서를 자동으로 생성·갱신하는 시스템이다.

Doxygen 정적 분석과 LLM을 다단계로 결합하여, 단순한 API 목록 나열이 아닌 **사용 시나리오와 코드 예제가 포함된 심층 가이드**를 생산한다. 생성된 문서는 Docusaurus 기반 사이트에 게재되며, MCP(Model Context Protocol) 서버를 통해 AI 어시스턴트에도 제공된다.

### 1.1 대상 라이브러리

| 패키지 | 역할 | 브랜치 |
|--------|------|--------|
| `dali-core` | 씬 그래프, 렌더링, 애니메이션 기반 엔진 | `tizen` / `master` |
| `dali-adaptor` | 플랫폼 연동 레이어 | `tizen` / `master` |
| `dali-ui` | 앱 개발자용 UI 컴포넌트 (View, Label 등) | `devel` |

### 1.2 문서 출력 타깃

| 출력 | 대상 독자 | API 범위 |
|------|-----------|----------|
| `app-guide/` | 앱 개발자 | `public-api` 전용 |
| `platform-guide/` | 플랫폼/엔진 개발자 | `public-api` + `devel-api` + `integration-api` |

---

## 2. 요구사항

### 2.1 기능 요구사항 (FR)

| ID | 요구사항 |
|----|----------|
| FR-01 | Doxygen XML과 C++ 소스를 분석하여 초기 문서를 자동 생성한다 |
| FR-02 | 주 1회 증분 업데이트로 API 변경 분만 재생성한다 |
| FR-03 | 독자 유형(앱/플랫폼)에 따라 다른 문서를 생산한다 |
| FR-04 | API를 기능 단위(Feature)로 자동 클러스터링한다 |
| FR-05 | 과도하게 큰 Feature를 서브 컴포넌트로 분할하고, 지나치게 작은 Feature를 통합한다 |
| FR-06 | 전체 Feature 목록을 한 번의 LLM 호출로 일관된 Tree 구조로 설계한다 |
| FR-07 | `Dali::Ui::View`를 앱 개발의 1차 UI 객체로 명시한다 (Actor 직접 사용 지양) |
| FR-08 | 내부 LLM(사내 Shuttle API)과 외부 LLM(Gemini)을 설정 변경만으로 전환한다 |
| FR-09 | 각 문서의 클래스 범위를 class_feature_map 기반 정확 매칭으로 결정한다 |
| FR-10 | 구조 변경(Tree↔Flat) 감지 시 해당 Feature 전체를 자동 재생성한다 |
| FR-11 | API 변경만 감지된 경우 기존 문서를 최대 보존하며 패치 방식으로 업데이트한다 |

### 2.2 비기능 요구사항 (NFR)

| ID | 요구사항 |
|----|----------|
| NFR-01 | Doxygen XML 대비 LLM 입력 토큰을 60~70% 절감한다 |
| NFR-02 | CLI 및 GitHub Actions 양쪽에서 독립 실행 가능하다 |
| NFR-03 | Rate limit 초과 시 지수 백오프로 자동 재시도한다 |
| NFR-04 | 구조 변경 여부를 taxonomy JSON 비교로 판단하여 일관성 있게 무효화한다 |
| NFR-05 | 원본 C++ 소스 코드를 수정하지 않는다 |
| NFR-06 | Taxonomy Tree 설계를 단일 LLM 호출로 수행하여 Feature 개수에 독립적인 비용 구조를 달성한다 |

---

## 3. 전체 시스템 구조

### 3.1 디렉토리 레이아웃

```
dali-ui-documentation/
├── dali-doc-gen/               # 파이프라인 본체
│   ├── config/
│   │   ├── repo_config.yaml    # 레포 URL, API 경로, manual_features
│   │   └── doc_config.yaml     # LLM 설정, feature_hints, token_overflow
│   ├── src/
│   │   ├── 00_extract/         # Phase 0: Doxygen 정적 추출
│   │   │   ├── repo_manager.py
│   │   │   ├── doxygen_runner.py
│   │   │   ├── doxygen_parser.py
│   │   │   ├── callgraph_parser.py
│   │   │   └── diff_detector.py
│   │   ├── 01_cluster/         # Phase 1: Feature 클러스터링 & Taxonomy
│   │   │   ├── feature_clusterer.py
│   │   │   └── taxonomy_reviewer.py   ← ENH-24에서 전면 재설계
│   │   ├── 02_llm/             # Phase 2: LLM 문서 생성
│   │   │   ├── llm_client.py
│   │   │   ├── stage_a_classifier.py  ← class_feature_map 재생성 추가
│   │   │   ├── stage_b_mapper.py      ← Fix B 제거
│   │   │   ├── stage_c_writer.py      ← exact match 전환
│   │   │   └── stage_d_validator_deprecated.py  ← 폐기됨
│   │   ├── 03_render/          # Phase 3: Markdown 렌더링
│   │   │   ├── md_renderer.py
│   │   │   ├── sidebar_generator.py
│   │   │   └── index_generator.py
│   │   ├── pipeline.py         # 마스터 오케스트레이터
│   │   ├── config.py
│   │   └── logger.py
│   ├── cache/                  # 런타임 중간 산출물 (git-ignored)
│   │   ├── parsed_doxygen/     # *.json — Doxygen 파싱 결과
│   │   ├── feature_map/        # feature_map.json, feature_map_classified.json,
│   │   │                       # class_feature_map.json
│   │   ├── feature_taxonomy/   # feature_taxonomy.json
│   │   ├── doc_blueprints/     # stage_b_blueprints_app.json, _platform.json
│   │   ├── validated_drafts/   # app/, platform/ — 최종 Markdown 초안
│   │   └── last_run_commits.json
│   └── repos/                  # 클론된 DALi 레포지토리 (git-ignored)
├── app-guide/                  # 최종 출력: 앱 개발자 문서
├── platform-guide/             # 최종 출력: 플랫폼 개발자 문서
└── devel-note/                 # 설계·개발 노트
    ├── Enhancing/              # ENH-01~24 개선 이력
    └── design_document_v2.md   # 본 문서
```

### 3.2 파이프라인 컴포넌트 흐름

```
┌──────────────────────────────────────────────────────────────────────┐
│  소스 저장소: dali-core · dali-adaptor · dali-ui                      │
└─────────────────────────────┬────────────────────────────────────────┘
                              │ git clone / pull
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Phase 0: 정적 분석 (00_extract/)                                     │
│                                                                      │
│  repo_manager → doxygen_runner → doxygen_parser → parsed_doxygen/   │
│                                  callgraph_parser                    │
│                                  diff_detector  (update 모드)        │
└─────────────────────────────┬────────────────────────────────────────┘
                              │ parsed_doxygen/*.json
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Phase 1: Feature 클러스터링 & Taxonomy (01_cluster/)                 │
│                                                                      │
│  feature_clusterer                                                   │
│    · 디렉토리 경로 기반 Feature 자동 분류                              │
│    · oversized 마킹 + split_candidates 계산                           │
│    · manual_features의 merge_mode:full 처리                          │
│    · 초기 class_feature_map.json 생성                                │
│    → feature_map.json                                                │
│                                                                      │
│  taxonomy_reviewer  [LLM Think]                                      │
│    Phase A-1: Oversized Feature 분할 검토 (LLM 1회/feature)           │
│      · split 결정 → feature_map에 sub-feature 추가                    │
│      · 부모 Feature.apis 에서 자식 APIs 제거 (_split_root 마킹)        │
│      · locked_groups 생성                                            │
│    Phase A-2: 소규모 Feature 통합 (LLM 1회 전체)                      │
│      · suppress_doc + merge_into + merge_mode:full 설정              │
│      · target.apis에 source.apis 물리 병합                           │
│    Phase B: 전체 일괄 Tree 설계 (LLM 1회 전체)                        │
│      · 전체 feature 목록 + locked_groups 힌트 → 최대 2뎁스 트리        │
│      · validate: 3뎁스 flatten, duplicate parent, locked group 복원   │
│    → feature_map.json (갱신), feature_taxonomy.json                  │
└─────────────────────────────┬────────────────────────────────────────┘
                              │ feature_map.json, feature_taxonomy.json
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Phase 2: LLM 문서 생성 (02_llm/)                   [tier별 분리 실행] │
│                                                                      │
│  Stage A: stage_a_classifier  [LLM Think]                            │
│    · ambiguous cluster → LLM으로 stable feature에 분류               │
│    · classified 기반 class_feature_map.json 재생성                   │
│    → feature_map_classified.json, class_feature_map.json (갱신)      │
│                                                                      │
│  Stage B: stage_b_mapper  [LLM Think]                                │
│    · Taxonomy 컨텍스트(tree/leaf/flat) 주입                           │
│    · Feature별 TOC + Blueprint 생성                                  │
│    → stage_b_blueprints_{tier}.json                                  │
│                                                                      │
│  Stage C: stage_c_writer  [LLM Instruct]                             │
│    · class_feature_map 기반 exact match로 API 스펙 수집               │
│    · Pass 1: 자연어 섹션 생성                                         │
│    · Pass 2: 코드 블록 + 심볼 검증 (Doxygen DB 대조, 최대 5회 재시도)  │
│    → validated_drafts/{tier}/*.md                                    │
└─────────────────────────────┬────────────────────────────────────────┘
                              │ validated_drafts/*.md
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Phase 3: Markdown 렌더링 (03_render/)              [tier별 분리 실행] │
│                                                                      │
│  md_renderer      — Frontmatter · 내부 링크 삽입                      │
│  sidebar_generator — Docusaurus 사이드바 JSON 생성                    │
│  index_generator  — Feature 인덱스 페이지 생성                        │
└─────────┬────────────────────────────────────┬──────────────────────┘
          ▼                                    ▼
    app-guide/docs/                  platform-guide/docs/
    (public-api 기준)                (public + devel + integration-api)
```

### 3.3 캐시 아티팩트 흐름

```
parsed_doxygen/*.json
    │
    ├─→ [feature_clusterer] ─→ feature_map.json
    │                           class_feature_map.json (초기)
    │
    ├─→ [diff_detector]     ─→ changed_apis.json  (update 모드)
    │
    └─→ [taxonomy_reviewer] ─→ feature_map.json (갱신: split/merge 반영)
                                feature_taxonomy.json

feature_map.json (갱신)
    │
    └─→ [stage_a] ─→ feature_map_classified.json
                      class_feature_map.json (재생성: ambiguous 해소 반영)

feature_map_classified.json + feature_taxonomy.json
    │
    └─→ [stage_b] ─→ stage_b_blueprints_{tier}.json

stage_b_blueprints_{tier}.json + class_feature_map.json
    │
    └─→ [stage_c] ─→ validated_drafts/{tier}/*.md

validated_drafts/{tier}/*.md + feature_taxonomy.json
    │
    └─→ [md_renderer + sidebar_generator + index_generator]
         ─→ {app|platform}-guide/docs/*.md + sidebar.json
```

---

## 4. 파이프라인 실행 흐름

### 4.1 실행 모드 및 주요 플래그

```bash
# 전체 초기 생성
python src/pipeline.py --mode full --tier app

# 증분 업데이트
python src/pipeline.py --mode update --tier all

# 특정 Feature 타깃 (디버그)
python src/pipeline.py --mode full --tier app --features "view,label" --limit 2

# LLM 환경 일시 전환
python src/pipeline.py --mode update --tier app --llm external
```

| 플래그 | 설명 |
|--------|------|
| `--mode full\|update` | 전체 생성 또는 증분 업데이트 |
| `--tier app\|platform\|all` | 문서 독자 타깃 |
| `--features "a,b"` | 처리할 Feature 명시적 지정 |
| `--limit N` | 처리 Feature 수 제한 (테스트용) |
| `--skip-pull` | git pull 생략 (롤백 테스트용) |
| `--llm internal\|external` | LLM 환경 일시 오버라이드 |

### 4.2 Update 모드 증분 처리 흐름

```
pipeline.py --mode update
    │
    ├─ 1. repo_manager: 소스 저장소 pull
    ├─ 2. doxygen_runner + doxygen_parser: 최신 Doxygen JSON 생성
    ├─ 3. diff_detector: *.json.old vs *.json → changed_apis.json
    ├─ 4. feature_clusterer: feature_map.json 갱신
    ├─ 5. taxonomy_reviewer: feature_taxonomy.json 갱신 (--mode update)
    │      (incremental 모드: 기존 taxonomy 컨텍스트로 변경분만 LLM에 요청)
    ├─ 6. taxonomy 비교 (old vs new):
    │      ├─ 신규 Feature / 구조 변경 → needs_regen 마킹
    │      ├─ API 내용만 변경         → needs_patch 마킹
    │      └─ 변경 없음              → 렌더링만 재실행
    ├─ 7. stage_a → stage_b → stage_c (needs_regen/needs_patch만)
    └─ 8. md_renderer + sidebar_generator + index_generator
```

| 분류 | 조건 | 처리 |
|------|------|------|
| `needs_regen` | 신규 Feature 추가 또는 taxonomy 구조 변경 | Stage B + Stage C 전체 재실행 |
| `needs_patch` | API 멤버 변경 (메서드 추가·수정) | Stage C 패치 모드만 실행 |
| 변경 없음 | diff 없음 | LLM 호출 없이 렌더링만 재실행 |

---

## 5. 모듈별 상세 설명

### 5.1 Phase 0 — 정적 추출 (`00_extract/`)

#### `repo_manager.py`

DALi 레포지토리(`dali-core`, `dali-adaptor`, `dali-ui`)를 `repos/` 하위에 clone/pull. `repo_config.yaml`의 `internal_url` / `external_url`을 `llm_environment` 설정에 따라 선택.

#### `doxygen_runner.py`

패키지별 Doxyfile을 동적으로 생성하여 Doxygen을 실행. XML 출력과 콜 그래프(`CALL_GRAPH=YES`)를 함께 생성. 출력: `cache/doxygen_json/`.

#### `doxygen_parser.py`

Doxygen XML → LLM 전달용 경량 JSON 변환. 추출 필드:

| 필드 | 설명 |
|------|------|
| `name` | 클래스·함수 정규화된 이름 |
| `kind` | `class`, `struct`, `function`, `enum` 등 |
| `brief` | 간략 설명 |
| `api_tier` | `public-api`, `devel-api`, `integration-api` |
| `signature` | 함수 시그니처 |
| `params` | 파라미터 목록 |
| `returns` | 반환값 설명 |
| `notes`, `warnings`, `code_examples` | 부가 정보 |
| `derived_classes` | 상속된 자식 클래스 목록 |

내부 ID, 파일 오프셋 등 불필요 정보 제거로 **토큰 60~70% 절감**.  
출력: `cache/parsed_doxygen/{package}.json`

#### `diff_detector.py`

`parsed_doxygen/*.json.old` ↔ `*.json`을 compound·member 레벨로 비교. 파일 레벨 git diff 대신 JSON 내용 비교를 사용하므로 주석·include 변경 등 API 무관 변경을 무시.  
출력: `cache/changed_apis.json`

#### `callgraph_parser.py`

Doxygen 콜 그래프 XML → Python 처리 후 `callgraph_json/`에 저장. LLM에 직접 전달하지 않아 토큰 절약.

---

### 5.2 Phase 1 — Feature 클러스터링 & Taxonomy (`01_cluster/`)

#### `feature_clusterer.py`

헤더 파일의 API 디렉토리 경로를 기준으로 Feature를 자동 분류:

```
dali/public-api/actors/actor.h      →  feature: "actors"
dali-ui-foundation/public-api/label.h  →  feature: "label"
```

주요 처리:

**1. 자동 클러스터링**  
디렉토리 이름을 Feature ID로 사용. 최상위 api_dir 바로 아래 자식 디렉토리가 Feature 단위.

**2. manual_features 적용**  
`repo_config.yaml`의 `manual_features`로 디렉토리 구조와 무관하게 Feature를 강제 정의:

```yaml
manual_features:
  - feature: "actors"
    suppress_doc: true       # 독립 문서 생성 안 함
    merge_into: "view"       # view 문서 생성 시 Actor API를 context로 포함
    merge_mode: "full"       # actors.apis를 view.apis에 물리 병합
```

| 필드 | 설명 |
|------|------|
| `suppress_doc` | `true`이면 독립 문서 생성 안 함 |
| `merge_into` | 이 Feature의 API를 대상 Feature 문서에 통합 |
| `merge_mode: "full"` | source.apis를 target.apis에 물리 병합하여 stage_c에서 완전 통합 |

**3. merge_mode:full 물리 병합**  
`merge_mode: "full"` 설정 시, feature_clusterer가 source.apis를 target.apis에 추가한다. 이렇게 하면 이후 단계에서 target 하나의 Feature로 일관되게 처리된다.

**4. oversized 마킹**  
스펙 수가 `max_specs_per_feature`(기본 2,000)를 초과하면:
- `oversized: true` 마킹
- 네임스페이스 기반 서브그룹 후보를 `split_candidates`로 계산하여 저장

```python
# split_candidates 계산 (feature_clusterer.py)
# 예: Dali::Addon::Manager → key: "addon"
# 같은 2레벨 네임스페이스 아래의 APIs를 그룹화
split_candidates = [
    {"group_name": "addon", "apis": ["Dali::Addon::Manager", ...]},
    {"group_name": "scene",  "apis": ["Dali::SceneHolder", ...]},
    ...
]
```

**5. class_feature_map 초기 생성**  
`{class_name: feature_id}` 매핑 파일. Stage A에서 ambiguous 해소 후 재생성되므로 이 시점의 파일은 임시본이다.

출력:
- `cache/feature_map/feature_map.json`
- `cache/feature_map/class_feature_map.json` (임시)

---

#### `taxonomy_reviewer.py` ← ENH-24에서 전면 재설계

Feature 재구조화와 Tree 설계를 담당. **Phase A**와 **Phase B** 두 단계로 구성된다.

##### Phase A-1: Oversized Feature 분할 검토 (LLM 1회/feature)

대형 Feature를 독립 서브 컴포넌트로 분할할지 결정한다.

```
조건: oversized:true이고 split_candidates가 3개 이상인 Feature
      (이미 taxonomy에 등록된 것은 스킵)

LLM에 전달:
  - feat_name, total_spec_count
  - groups_summary: split_candidates의 group_name + sample_apis

LLM 판단:
  SPLIT → 각 그룹을 독립 문서 페이지로 분리
  SINGLE → 하나의 대형 문서로 유지
```

**SPLIT 결정 시 처리:**

```python
# 1. 자식 Feature 생성 (feature_map에 추가)
new_entry = {
    "feature": child_id,          # LLM이 제안한 slug
    "apis": child_apis,           # split_candidates[i].apis (slug 매칭 후 할당)
    "_taxonomy_split": True,      # 자동 split으로 생성됨
    "_split_parent": feat_name,   # 부모 Feature ID
    ...
}

# 2. 부모 A의 apis에서 자식이 가져간 APIs 제거 (overview만 유지)
feat["apis"] = [a for a in feat["apis"] if a not in all_child_apis]

# 3. 부모 A를 overview 페이지로 마킹
feat["_split_root"] = True   # stage_a의 target_candidates에서 제외

# 4. locked_groups에 등록 (Phase B LLM이 이 관계를 바꾸지 못하도록)
locked_groups.append({"parent": feat_name, "children": child_ids})
```

`_split_root` 마킹의 의미:
- Stage A에서 ambiguous API 분류 target_candidates에서 제외됨 (overview 껍데기이므로)
- Stage C에서 직접 API가 없어도 overview 페이지 생성이 허용됨
- Phase A-2의 small feature 평가에서 제외됨 (merge 대상 아님)

##### Phase A-2: 소규모 Feature 통합 (LLM 1회 전체)

API 스펙 수가 `min_specs_for_standalone` 미만인 Feature를 더 큰 Feature에 통합한다.

```
평가 제외 대상:
  - suppress_doc:true인 Feature
  - ambiguous:true인 Feature
  - _taxonomy_split:true인 Feature (split 자식 → locked_group 제약)
  - _split_root:true인 Feature (split 부모 → overview 페이지)

LLM에 전달:
  - small_summary: 소규모 Feature 목록 (feature_id, display_name, api_count)
  - stable_ids: merge 가능한 안정적인 Feature 목록

LLM 판단:
  MERGE → source를 target에 통합
  KEEP  → 현 상태 유지
```

**MERGE 결정 시 처리:**

```python
# 1. source(B)에 suppress 마킹
feature_map_index[source_id]["suppress_doc"] = True
feature_map_index[source_id]["merge_into"] = target_id
feature_map_index[source_id]["merge_mode"] = "full"   # stage_c 완전 통합 보장

# 2. source.apis를 target.apis에 물리 병합
# (feature_clusterer의 merge_mode:full과 동일한 효과)
new_apis = [a for a in source_apis if a not in existing_apis]
target_feat["apis"] += new_apis
```

`merge_mode:full`을 설정하는 이유:
- stage_c의 `merge_sources` 빌드 조건: `merge_mode != "full"`인 경우만 `merge_sources`에 추가됨
- `merge_mode:full`이 없으면 source가 `merge_sources`에 포함되어 "brief mention"으로만 처리됨
- `merge_mode:full` + 물리 병합 → stage_c가 target의 apis를 조회할 때 source APIs가 자동 포함됨 → 완전 문서화

##### Phase A-3: 변경된 feature_map.json 저장

split/merge 결과가 반영된 feature_map.json을 저장. class_feature_map 재생성은 stage_a의 책임.

##### Phase B: 전체 일괄 Tree 설계 (LLM 1회)

Feature 개수와 무관하게 **단 1회의 LLM 호출**로 전체 Tree 구조를 설계한다.

```
LLM에 전달:
  - feature_summaries: suppress_doc/autogen 제외한 전체 active feature 목록
    (feature_id, display_name, brief, api_count)
  - locked_groups: Phase A-1에서 결정된 split 관계 (변경 금지)

LLM이 결정:
  - "tree": 이 feature가 parent (children 목록 포함)
  - "flat": 이 feature가 독립 단일 문서
  ※ children이 없으면 "flat"으로 자동 다운그레이드

증분 모드 (--mode update):
  - 기존 taxonomy를 컨텍스트로 제공
  - 변경된 feature만 포함하여 LLM에 요청
  - 응답에 없는 기존 항목은 그대로 유지
```

**validate_and_build_taxonomy — LLM 응답 후처리:**

```
검증 1: children에 없는 feature_id 제거
검증 2: locked group 위반 복원
         - locked parent가 다른 feature의 child가 되면 제거
         - locked child가 잘못된 parent 아래 있으면 이동
           (잘못된 parent의 children 목록에서도 제거)
검증 3: 3뎁스 탐지 → grandchild를 parent 레벨로 flatten
검증 4: tree인데 children 없음 → flat으로 다운그레이드
```

출력:
- `cache/feature_map/feature_map.json` (갱신: split/merge 반영)
- `cache/feature_taxonomy/feature_taxonomy.json`

---

### 5.3 Phase 2 — LLM 문서 생성 (`02_llm/`)

#### Stage 개요

```
Stage A (Classifier, Think)
  ↓ feature_map_classified.json
  ↓ class_feature_map.json (재생성)
Stage B (Mapper, Think)
  ↓ stage_b_blueprints_{tier}.json
Stage C (Writer, Instruct)
  ↓ validated_drafts/{tier}/*.md
```

Stage D (`stage_d_validator_deprecated.py`)는 **폐기**되었다. 심볼 검증은 Stage C 내 Pass 2의 Doxygen DB 대조로 처리된다.

---

#### `stage_a_classifier.py` ← class_feature_map 재생성 추가

모호한(ambiguous) Feature 경계를 LLM으로 해소한다.

**입력:** `feature_map.json` (taxonomy_reviewer가 갱신한 버전)

**주요 처리:**

**1. ambiguous/stable 분리**
```python
for cluster in feature_list:
    if cluster.get("ambiguous") == True:
        ambiguous_clusters.append(cluster)
    else:
        stable_clusters.append(cluster)
```

**2. target_candidates 구성**
```python
# _split_root feature는 제외 (apis가 비워진 overview 껍데기)
# ambiguous API가 overview 페이지로 분류되면 안 됨
target_candidates = [
    c["feature"] for c in stable_clusters
    if not c.get("_split_root")
]
```

**3. LLM 분류 (1회/ambiguous cluster)**
```
각 ambiguous cluster의 APIs 샘플 15개를 target_candidates와 함께 LLM에 전달
→ 가장 적합한 target feature 1개 반환
→ stable_dict[target].apis에 ambiguous.apis 병합
```
분류 실패 시 `unclassified_isolation_{original_name}`으로 독립 Feature 생성.

**4. class_feature_map 재생성** ← ENH-24 추가

```python
# ambiguous cluster가 없어도 반드시 실행 (taxonomy_reviewer의 split/merge가 반영돼야 하므로)
def _rebuild_class_feature_map(final_classified_map, out_map_path):
    # 1차: classified map 기반 정상 mapping
    class_feature_map = {}
    for feat in final_classified_map:
        if feat.get("suppress_doc"):
            continue   # suppress된 feature는 건너뜀
        for cls_name in feat.get("apis", []):
            if cls_name not in class_feature_map:
                class_feature_map[cls_name] = feat["feature"]

    # 2차: suppress_doc feature의 클래스는 merge_into target으로 재매핑
    # feature_map.json을 다시 읽어서 suppress_doc + merge_into 조합 처리
    for feat in raw_feature_map:
        if feat.get("suppress_doc") and feat.get("merge_into"):
            target = feat["merge_into"]
            for cls_name in feat.get("apis", []):
                class_feature_map[cls_name] = target  # 덮어씀 (target 우선)
```

이 처리 덕분에:
- merge_mode:full로 통합된 B/C의 클래스 → D로 매핑
- split으로 생성된 A1/A2/A3의 클래스 → 각각 A1/A2/A3으로 매핑
- ambiguous 해소 후 재배치된 클래스 → 올바른 feature로 매핑

출력:
- `cache/feature_map/feature_map_classified.json`
- `cache/feature_map/class_feature_map.json` (재생성)

---

#### `stage_b_mapper.py` ← Fix B 제거

Feature별 TOC(목차)와 Blueprint를 생성한다.

**Fix B 제거 배경:**  
이전에는 taxonomy의 child feature를 stage_b가 런타임에 feature_list에 주입하고 class_feature_map을 직접 수정(`update_class_feature_map_for_children`)했다. ENH-24 이후 taxonomy_reviewer가 split 결과를 feature_map.json에 직접 반영하고, stage_a가 class_feature_map을 재생성하므로 이 런타임 패치가 불필요해졌다.

**주요 처리:**

**Tier 필터링:**
```python
allowed_tiers = {"public-api"} if args.tier == "app" else None
# filter_apis_by_tier()로 tier에 맞지 않는 클래스 제외
```

**API 보완 (enrich_apis_with_members):**
feature_clusterer는 compound name(클래스)만 apis에 등록하므로, 메서드 항목이 없는 경우 parsed_doxygen에서 function 멤버를 보완하여 LLM이 실제 메서드를 참조할 수 있게 한다.

**Taxonomy 컨텍스트 주입:**
```python
if tree_decision == "tree" and children:
    taxonomy_context = """
    DOCUMENT STRUCTURE CONTEXT:
    This feature is a PARENT document in a tree hierarchy.
    It should serve as an OVERVIEW page...
    """
elif tree_decision == "leaf" and parent:
    taxonomy_context = """
    DOCUMENT STRUCTURE CONTEXT:
    This feature is a CHILD component of '{parent}'.
    Focus on what makes this specific component unique...
    """
```

**샘플링 (`sample_apis`):**
최대 50개 제한. 클래스 선언을 우선하고 메서드는 균등 간격으로 샘플링.

출력: `cache/doc_blueprints/stage_b_blueprints_{tier}.json`

---

#### `stage_c_writer.py` ← class_feature_map 기반 exact match 전환

핵심 Markdown 생성 모듈.

##### get_api_specs() — 클래스 스펙 수집

```python
def get_api_specs(pkg_names, api_names_list, allowed_tiers=None,
                  owning_feature=None, class_feature_map=None):
```

**Primary: class_feature_map exact match** ← ENH-24에서 변경

```python
# class_feature_map이 있으면 exact match 우선
class_keys_set = {cls for cls, fid in class_feature_map.items()
                  if fid == owning_feature}

if class_keys_set:
    is_class_match = c_name in class_keys_set   # 정확한 소속 클래스만
```

**Fallback: api_names_list 기반 substring 매칭**

```python
else:
    # class_feature_map이 없을 때만 사용 (보조 조회 등)
    is_class_match = any(a in c_name for a in api_names_list) or ...
    # 이 경우 class_feature_map으로 다른 feature 소속 클래스는 foreign으로 분리
```

exact match 전환 이유: 이전 substring 매칭은 `"view"` → `ImageView`, `ScrollView`, `TextView` 등을 모두 포함시키는 false positive를 유발했다. class_feature_map이 stage_a에서 ambiguous 해소 후 정확히 재생성되므로, 이를 primary lookup으로 사용하는 것이 가장 정확하다.

##### suppress_doc / merge 처리

```python
# suppress_doc feature는 스킵
if fm_entry.get("suppress_doc"):
    continue

# merge_sources: merge_mode != "full"인 suppress_doc feature만 포함
# (merge_mode:full은 target.apis에 이미 물리 병합되어 있으므로 제외)
merge_sources = {}
for f in feature_map_list:
    target = f.get("merge_into")
    if target and f.get("suppress_doc") and f.get("merge_mode") != "full":
        merge_sources.setdefault(target, []).append(f)
```

| merge 종류 | 처리 방식 |
|-----------|---------|
| `merge_mode:full` (manual or 자동) | target.apis에 물리 병합 → get_api_specs(target)에서 자동 포함, merge_sources 제외 |
| merge_mode 없음 | merge_sources → inherited_context (brief mention만) |

##### split_root overview 페이지 처리

```python
# split_root 부모(A)는 직접 API가 없어도 overview 페이지 생성 허용
is_split_root_overview = (
    fm_entry.get("_split_root") and
    tree_decision == "tree" and
    bool(children)
)
if not specs and not is_split_root_overview:
    # .notier 마커만 쓰고 스킵
    continue
```

overview 페이지용 컨텍스트: taxonomy_context에서 child 목록을 제공하고, 각 child의 메서드 힌트도 수집하여 LLM이 overview 내용을 작성할 수 있게 한다.

##### 2-Pass 생성 및 심볼 검증

```
Pass 1: 자연어 섹션 생성
  - outline(Blueprint)의 각 섹션별 설명 작성
  - 코드 블록은 포함하지 않음
  - Doxygen spec JSON을 참조 자료로 제공

Pass 2: 코드 블록 생성
  - Pass 1 결과를 기반으로 코드 예제 추가
  - 사용 가능한 심볼을 permitted_method_list로 제한
  - 생성 후 Doxygen DB 대조 심볼 검증
  - 검증 실패 시 최대 5회 재생성

검증 기준:
  - 코드 블록 내 모든 심볼(클래스, 메서드, enum)을 Doxygen DB와 대조
  - 매칭률 < 60%이면 재생성
  - 패스 시 validated_drafts/{tier}/ 에 저장
```

##### 롤링 정제 (대형 Feature)

스펙 토큰 추정치가 `spec_token_threshold`(기본 60,000)를 초과하면:
1. `chunk_specs_by_class()`로 클래스 단위 청크 분할
2. 청크별로 Pass 1을 순차적으로 실행 (이전 결과 보존 + 새 청크 보강)
3. 미처리 섹션은 `<!-- PENDING -->` 마커로 표시
4. 최종 Pass에서 PENDING 마커 제거 및 Summary 섹션 추가

---

### 5.4 Phase 3 — 렌더링 (`03_render/`)

#### `md_renderer.py`

- Jinja2 템플릿으로 Frontmatter 주입:
  ```yaml
  ---
  id: view
  title: "View (Base UI Object)"
  sidebar_label: "View (Base UI Object)"
  ---
  ```
- taxonomy의 `display_name`을 기준으로 본문 내 Feature 이름을 자동 상호 링크로 변환

#### `sidebar_generator.py`

taxonomy의 tree/flat 결정에 따라 Docusaurus v3 호환 `sidebar.json` 생성. Tree Feature는 Category + Children 형태로 중첩.

#### `index_generator.py`

모든 Feature를 나열하는 인덱스 페이지를 자동 생성.

---

### 5.5 할루시네이션 방어 계층

```
Layer 1: 프롬프트 제약
  - "provided JSON 이외의 클래스·메서드 사용 금지" 명시
  - permitted_method_list로 허용 심볼 제한

Layer 2: Pass 2 심볼 검증
  - 생성된 코드 블록의 모든 심볼을 Doxygen DB 대조
  - 매칭률 < 60%이면 최대 5회 재생성

Layer 3: class_feature_map exact match
  - 다른 feature 소속 클래스가 잘못 포함되지 않도록 정확한 소속 판단

Layer 4: 휴먼 리뷰
  - GitHub PR 머지 게이트
```

> **참고:** Stage D(별도 할루시네이션 검증 단계)는 폐기되었다. 검증은 Stage C 내 Pass 2에 통합되어 있다.

---

## 6. 핵심 데이터 파일

### 6.1 `feature_map.json`

Feature 클러스터 정보의 원본. feature_clusterer가 생성하고 taxonomy_reviewer가 갱신한다.

```json
[
  {
    "feature": "view",
    "display_name": "View",
    "packages": ["dali-ui"],
    "api_tiers": ["public-api"],
    "apis": ["Dali::Ui::View", "Dali::Ui::View::Property", ...],
    "ambiguous": false,
    "oversized": false,
    "suppress_doc": false
  },
  {
    "feature": "actors",
    "suppress_doc": true,
    "merge_into": "view",
    "merge_mode": "full",
    "apis": ["Dali::Actor", ...]
  },
  {
    "feature": "image-view-animated",
    "_taxonomy_split": true,
    "_split_parent": "image-view",
    "apis": ["Dali::Ui::AnimatedImageView", ...]
  },
  {
    "feature": "image-view",
    "_split_root": true,
    "apis": []   // 자식들이 가져가 비어있음
  }
]
```

**주요 플래그:**

| 플래그 | 생성 위치 | 의미 |
|--------|----------|------|
| `ambiguous` | feature_clusterer | 여러 패키지에 걸쳐 분류 불명확 |
| `oversized` | feature_clusterer | 스펙 수 초과, split 후보 |
| `split_candidates` | feature_clusterer | namespace 기반 분할 후보 그룹 |
| `suppress_doc` | manual_features / taxonomy_reviewer | 독립 문서 미생성 |
| `merge_into` | manual_features / taxonomy_reviewer | 통합 대상 feature |
| `merge_mode: "full"` | manual_features / taxonomy_reviewer | apis 물리 병합 |
| `_split_root` | taxonomy_reviewer | split 부모, overview 페이지 |
| `_taxonomy_split` | taxonomy_reviewer | split으로 생성된 자식 |
| `_split_parent` | taxonomy_reviewer | 자식의 원본 부모 ID |

### 6.2 `feature_map_classified.json`

stage_a가 ambiguous 해소 후 생성하는 최종 feature 목록. suppress_doc feature도 포함되어 있다. stage_b/c의 입력 파일.

### 6.3 `class_feature_map.json`

`{class_name → feature_id}` 역매핑. stage_a가 classified 기반으로 재생성한다.

```json
{
  "Dali::Ui::View": "view",
  "Dali::Actor":    "view",   // merge_mode:full로 view에 통합된 actors 소속
  "Dali::Ui::AnimatedImageView": "image-view-animated",
  "Dali::Ui::Label": "label"
}
```

이 파일이 stage_c의 `get_api_specs()` primary lookup 기준이다.

### 6.4 `feature_taxonomy.json`

```json
{
  "view": {
    "display_name": "View (Base UI Object)",
    "parent": null,
    "children": ["image-view", "label", "scroll-view"],
    "doc_file": "view.md",
    "tree_decision": "tree",
    "decision_reason": "Has child components"
  },
  "image-view": {
    "display_name": "Image View",
    "parent": "view",
    "children": ["image-view-animated", "image-view-lottie"],
    "doc_file": "image-view.md",
    "tree_decision": "tree",
    "decision_reason": "Has child components"
  }
}
```

`tree_decision` 값:

| 값 | 의미 |
|----|------|
| `"tree"` | children을 가진 parent 페이지 |
| `"leaf"` | parent 아래에 있는 자식 페이지 |
| `"flat"` | 독립 단일 페이지 |

---

## 7. LLM 운용 전략

### 7.1 내부/외부 LLM 전환

`doc_config.yaml`의 `llm_environment` 값 하나로 전환:

| 항목 | 내부 (Shuttle) | 외부 (Gemini) |
|------|---------------|---------------|
| Think 모델 | `gauss2.3-37b-think` | `gemini-3.1-flash-lite-preview` |
| Instruct 모델 | `gauss2.3-37b` | `gemini-3.1-flash-lite-preview` |
| 인증 | Basic Auth (Base64) | API Key |
| Rate Limit 대기 | 4초/요청 (20 RPM) | 슬라이딩 윈도우 250k tok/min |
| 재시도 횟수 | 최대 10회 | 최대 10회 |

### 7.2 LLM 호출 지점 및 횟수

| 단계 | 모델 | 호출 횟수 | 메모 |
|------|------|-----------|------|
| taxonomy_reviewer Phase A-1 | Think | 1회/oversized feature | split/single 판단 |
| taxonomy_reviewer Phase A-2 | Think | 1회 전체 | 소규모 feature merge 판단 |
| taxonomy_reviewer Phase B | Think | 1회 전체 | **전체 tree 일괄 설계** |
| stage_a | Think | 1회/ambiguous cluster | feature 경계 분류 |
| stage_b | Think | 1회/feature | TOC + Blueprint |
| stage_c Pass 1 | Instruct | 1회/feature | 자연어 섹션 |
| stage_c Pass 2 | Instruct | 1~5회/feature | 코드 블록 + 검증 |

> **taxonomy Phase B의 비용 구조:**  
> Feature 수 N에 관계없이 Phase B는 항상 1회만 호출된다. 이는 v1 대비 가장 큰 비용 절감 포인트다. (v1: N회 → v2: 1회)

### 7.3 토큰 최적화 전략

| 전략 | 절감 효과 |
|------|----------|
| Doxygen XML → 경량 JSON 필터링 | 60~70% 절감 |
| Feature 단위 분할 생성 | 20만 토큰 단일 프롬프트 방지 |
| Stage B 샘플링 (최대 50개) | B 단계 입력 토큰 최소화 |
| 소규모 feature merge | LLM 호출 수 감소 |
| 증분 업데이트 (변경 Feature만) | 업데이트 시 O(변경 feature 수) 호출 |
| 롤링 정제 (대형 Feature 분할 처리) | 컨텍스트 한도 우회 |
| exact match (불필요 spec 제외) | stage_c 입력 토큰 절감 |

---

## 8. 핵심 설계 결정

### D-1. class_feature_map: Ambiguous 해소 후 재생성

**문제:** feature_clusterer가 초기에 생성하는 class_feature_map은 ambiguous cluster의 클래스를 `uncategorized_ambiguous_root`에 매핑한다. 이 상태로 stage_c가 exact match를 수행하면 ambiguous 클래스가 어느 feature 문서에도 포함되지 않는다.

**해결:** stage_a가 ambiguous를 해소한 후 classified 기반으로 class_feature_map을 재생성한다. 이 시점에는:
- ambiguous 클래스 → 배정된 stable feature로 매핑
- suppress_doc 클래스 → merge_into target으로 재매핑
- split 자식 클래스 → 각 자식 feature로 정확히 매핑

### D-2. merge_mode:full: 완전 통합 보장

**문제:** `suppress_doc + merge_into`만 설정하면 stage_c가 source를 `merge_sources`로 처리하여 "brief mention"만 포함한다. 두 feature가 하나의 문서로 완전히 통합되지 않는다.

**해결:** `merge_mode: "full"` + 물리적 apis 병합:
- stage_c의 `merge_sources` 빌드 조건에서 `merge_mode:full`이 제외됨
- target.apis에 source.apis가 이미 포함되어 있으므로 `get_api_specs(target)`에서 자동으로 완전 수집됨
- 결과: 두 feature의 모든 API가 target 문서에 완전히 문서화됨

### D-3. Taxonomy Tree: 개별 판단 → 전체 일괄 판단

**문제 (v1):** 각 Feature를 개별 LLM 호출로 flat/tree 결정할 때 전역 맥락이 없어 충돌이 발생했다 (Feature A가 B를 child라 하고, B가 동시에 C를 child라 하면 3뎁스 발생). 별도 Fix D 후처리로 교정해야 했다.

**해결 (v2):** 전체 feature 목록을 한 번에 LLM에 제공하고, locked_groups 힌트로 split 관계를 명시한다. LLM이 전체 맥락을 보고 일관된 구조를 설계하므로 충돌이 근본적으로 줄어든다. `validate_and_build_taxonomy`가 나머지 구조적 오류를 후처리로 교정한다.

### D-4. _split_root: Overview 페이지의 독립적 처리

**문제:** oversized feature를 분할하면 부모 A의 apis가 모두 자식에게 배분되어 A.apis = []가 된다. stage_c는 스펙이 없으면 `.notier` 마커로 스킵하므로 overview 페이지가 생성되지 않는다.

**해결:**
- taxonomy_reviewer가 split 시 부모에 `_split_root: True` 마킹
- stage_c에서 `_split_root + tree_decision:tree + children 존재` 조건이면 스펙 없이도 overview 페이지 생성 허용
- 이때 LLM은 children 목록과 각 child의 메서드 힌트를 기반으로 overview를 작성

### D-5. Stage D 폐기

Stage D는 생성된 Markdown에서 심볼을 추출하여 Doxygen DB와 대조하고 실패 시 재생성하는 단계였다. ENH-22 이후 Stage C의 Pass 2에 심볼 검증과 재생성이 통합되어 Stage D가 중복이 되었다. 현재는 deprecated 파일로만 존재한다.

### D-6. Tier 분리: 생성 시점 적용

"앱 가이드에서 devel-api 내용 제거"는 사후 필터링이 불가능하다. Stage B와 Stage C가 tier에 맞는 스펙만 수신하도록 `allowed_tiers` 파라미터를 생성 시점에 적용하여 격리한다.

### D-7. API 변경 감지: JSON 비교

초기 설계에서는 git diff 파일 레벨로 변경을 감지했으나, 라이선스 헤더나 `#include` 변경도 감지되는 문제가 있었다. 현재는 `parsed_doxygen/*.json.old` ↔ `*.json` 비교로 실제 API 내용(signature, brief, params 등) 변경만 추적한다.

---

## 9. CI/CD 및 운영

### 9.1 GitHub Actions 워크플로

| 워크플로 | 트리거 | Runner | 출력 |
|----------|--------|--------|------|
| `initial-full-gen.yml` | 수동 (`workflow_dispatch`) | code-large | `docs/initial-full-{tier}` PR |
| `weekly-update.yml` | Cron `0 0 * * 1` + 수동 | code-large | `docs/weekly-update` PR |
| `e2e-update-test.yml` | 수동 | code-large | 비교 아티팩트 업로드 |

### 9.2 전체 실행 흐름 (CI)

```
최초 도입 또는 전체 재생성
  → [수동] initial-full-gen 실행
      pipeline.py --mode full
      → 생성된 문서를 새 브랜치에 커밋 → PR 자동 생성 → 리뷰 후 머지

이후 정기 운영
  → [자동] weekly-update  (매주 월요일 UTC 00:00)
      최신 소스 pull → 변경 API 감지 → 증분 재생성
      → PR 자동 생성 → 리뷰 후 머지
```

### 9.3 E2E 테스트 시나리오

1. 대상 레포를 `HEAD~N` (기본 30커밋)으로 롤백
2. `--mode full --skip-pull`로 과거 시점 문서 생성
3. 레포를 최신으로 복원
4. `--mode update`로 증분 업데이트 실행
5. 두 결과를 아티팩트로 업로드하여 비교

### 9.4 설정 파일

#### `config/repo_config.yaml`

```yaml
repos:
  dali-ui:
    internal_url: "git@github.sec.samsung.net:NUI/dali-ui.git"
    external_url: "https://github.com/dalihub/dali-ui.git"
    path: "repos/dali-ui"
    internal_branch: "devel"
    external_branch: "devel"
    api_dirs:
      - "dali-ui-foundation/public-api"
      - "dali-ui-foundation/devel-api"
      - "dali-ui-components/public-api"

manual_features:
  - feature: "actors"
    display_name: "Actor (Scene Graph Node)"
    source_package: "dali-core"
    suppress_doc: true
    merge_into: "view"
    merge_mode: "full"   # actors.apis → view.apis 물리 병합
```

#### `config/doc_config.yaml`

```yaml
llm_environment: "external"   # "internal" 또는 "external"

feature_hints:
  view:
    extra_context: |
      View supports Fluent API through method chaining...

token_overflow:
  max_specs_per_feature: 2000       # 이 스펙 수 초과 → oversized 마킹
  min_specs_for_standalone: 10      # 이 스펙 수 미만 → merge 검토 (0이면 비활성화)
  spec_token_threshold: 60000       # 이 토큰 수 초과 → 롤링 정제 모드
  context_limit: 120000             # 사내 LLM 컨텍스트 한도
  prompt_overhead: 4000             # 프롬프트 고정 텍스트 추정 토큰
```

### 9.5 운영 체크리스트

- **GitHub Secrets:** `GEMINI_API_KEY`, `INTERNAL_API_KEY`, `GITHUB_TOKEN`
- **GitHub Variables:** `DEFAULT_ENVIRONMENT` (scheduled 실행의 LLM 환경 기본값)
- **Runner:** `code-large` (self-hosted, 내부 LLM 사용 시 필요)
- **의존:** Python 3.12+, Doxygen 1.9+

---

## 부록 A. v1 → v2 주요 변경 사항

| 구성 요소 | v1 | v2 |
|-----------|----|----|
| taxonomy_reviewer | feature 개별 LLM 판단 (N회) | Phase A/B 구조화; tree는 1회 전체 LLM |
| Feature 재구조화 | 없음 | oversized split + small merge |
| class_feature_map 생성 시점 | feature_clusterer (ambiguous 해소 전) | stage_a (ambiguous 해소 후) |
| stage_c class 수집 방식 | substring 매칭 (false positive 가능) | exact match via class_feature_map |
| stage_b Fix B | 런타임 child injection + class_feature_map 수정 | 제거 (taxonomy_reviewer가 feature_map 직접 갱신) |
| Stage D | 별도 할루시네이션 검증 단계 | 폐기 (Stage C Pass 2에 통합) |
| merge 처리 | manual_features만 지원 | manual + 자동 (taxonomy_reviewer Phase A-2) |
| split parent 문서 | 없음 | _split_root overview 페이지 생성 |
