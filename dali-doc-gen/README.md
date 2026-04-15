# DALi Documentation Generator

`dali-doc-gen`은 DALi C++ 그래픽 라이브러리(`dali-core`, `dali-adaptor`, `dali-ui`)의 소스코드를
정적 분석하고 LLM을 이용해 **앱 개발자 및 플랫폼 개발자용 가이드 문서를 자동으로 생성·유지**하는
파이프라인 도구다.

---

## 목차

1. [목적과 배경](#목적과-배경)
2. [전체 아키텍처](#전체-아키텍처)
3. [디렉토리 구조](#디렉토리-구조)
4. [GitHub Actions — 자동화 워크플로](#github-actions--자동화-워크플로)
5. [환경 준비](#환경-준비)
6. [설정 파일](#설정-파일)
7. [전체 파이프라인 실행](#전체-파이프라인-실행)
8. [모듈별 단독 실행](#모듈별-단독-실행)
9. [캐시 디렉토리 구조](#캐시-디렉토리-구조)
10. [출력 문서 구조](#출력-문서-구조)
11. [주요 설계 결정](#주요-설계-결정)
12. [알려진 주의사항](#알려진-주의사항)

---

## 목적과 배경

DALi는 `dali-core`, `dali-adaptor`, `dali-ui`에 걸쳐 수천 개의 C++ 클래스와 메서드를 제공한다.
이 라이브러리를 사용하는 **앱 개발자**(dali-ui 공개 API만 사용)와 **플랫폼 개발자**(내부 API까지 접근)는
서로 다른 수준의 문서가 필요하다.

이 도구는 다음 문제를 해결하기 위해 설계되었다:

- **소스에서 직접 추출**: Doxygen 주석을 기반으로 API 명세를 자동으로 수집한다.
  사람이 직접 API를 나열하거나 정리할 필요가 없다.
- **독자 맞춤 문서**: `--tier app` / `--tier platform` 플래그 하나로 독자층에 맞는
  API 범위와 서술 방식으로 문서를 생성한다.
- **할루시네이션 방지**: LLM이 생성한 코드 예제의 모든 심볼(클래스명, 메서드명, enum 값)을
  Doxygen에서 구축한 심볼 DB와 대조하여 검증한다. 검증 실패 시 최대 5회 재생성을 시도한다.
- **증분 업데이트**: 소스 변경이 발생한 Feature만 선별적으로 재생성하거나 패치한다.
  변경 없는 문서는 LLM 호출 없이 그대로 유지된다.
- **자동화 운영**: GitHub Actions 워크플로를 통해 최초 전체 생성(수동)과 주간 증분 업데이트(자동)가
  사람의 개입 없이 실행된다. 소스 저장소에 API 변경이 생기면 매주 문서가 자동으로 갱신되고
  PR이 생성된다.

생성된 문서는 Markdown 형식이며, Docusaurus[^1] 사이드바 JSON을 함께 출력한다.
하지만 Markdown 자체는 Docusaurus에 종속되지 않으므로 다른 문서 사이트나 MCP 제공용으로도 활용할 수 있다.

[^1]: **Docusaurus**: Meta(구 Facebook)가 개발한 정적 사이트 생성기(Static Site Generator).
Markdown 파일을 입력으로 받아 검색·버전 관리·사이드바 탐색 기능이 포함된 문서 사이트를 빌드한다.

---

## 전체 아키텍처

```
┌───────────────────────────────────────────────────────────────────────┐
│                          소스 저장소                                    │
│          dali-core  ·  dali-adaptor  ·  dali-ui                       │
└──────────────────────────────┬────────────────────────────────────────┘
                               │ git clone / pull
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Phase 0: 정적 분석 (00_extract/)                                      │
│                                                                        │
│  repo_manager ──→ doxygen_runner ──→ doxygen_parser                   │
│                                           │                            │
│                   callgraph_parser ◄──────┘                           │
│                   diff_detector  (update 모드 전용)                    │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ parsed_doxygen/*.json
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Phase 1: Feature 분류 · Taxonomy 설계 (01_cluster/)                   │
│                                                                        │
│  feature_clusterer ──→ taxonomy_reviewer (LLM Think)                  │
│                                                                        │
│  · API를 "Feature" 단위로 그룹화                                        │
│  · 상속 계층 분석: Tree 구조 vs Flat 문서 결정                           │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ feature_taxonomy.json
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Phase 2: LLM 문서 생성 (02_llm/)                   [tier별 분리 실행] │
│                                                                        │
│  Stage A: stage_a_classifier  — Feature 경계 보정 (LLM Think)          │
│  Stage B: stage_b_mapper      — TOC 설계·Blueprint 생성 (LLM Think)    │
│  Stage C: stage_c_writer      — Markdown 초안 작성 (LLM Instruct)      │
│                ├── Pass 1: 자연어 섹션 생성                             │
│                └── Pass 2: 코드 블록 생성 + 심볼 검증 (최대 5회 재시도) │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ validated_drafts/*.md
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Phase 3: Markdown 렌더링 (03_render/)              [tier별 분리 실행] │
│                                                                        │
│  md_renderer      — Frontmatter · 내부 링크 삽입                       │
│  sidebar_generator — 네비게이션 JSON 생성                               │
│  index_generator  — 인덱스 페이지 생성                                  │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
             ┌─────────────────┴──────────────────┐
             ▼                                    ▼
       app-guide/docs/                  platform-guide/docs/
       (public-api 기준)                (public + devel + integration-api)
```

### API Tier 분리

| Tier | 독자 | 포함 API | 출력 디렉토리 |
|------|------|----------|---------------|
| `app` | 앱 개발자 | `public-api` | `app-guide/` |
| `platform` | 플랫폼 개발자 | `public-api` + `devel-api` + `integration-api` | `platform-guide/` |

Stage B에서 `--tier` 값에 따라 Blueprint(`stage_b_blueprints_app.json` / `stage_b_blueprints_platform.json`)를
별도로 생성한다. 이후 Stage C / 렌더링 단계도 동일 tier 파일을 참조한다.

---

## 디렉토리 구조

```
dali-doc-gen/
├── config/
│   ├── repo_config.yaml          # 저장소 URL·경로·API 디렉토리 정의
│   └── doc_config.yaml           # LLM 모델·feature_hints·토큰 제한 설정
├── src/
│   ├── pipeline.py               # 전체 파이프라인 오케스트레이터
│   ├── config.py                 # 설정 로드 헬퍼
│   ├── logger.py                 # 로깅 유틸리티
│   ├── 00_extract/               # Phase 0: 정적 분석
│   │   ├── repo_manager.py       # 저장소 clone / pull
│   │   ├── doxygen_runner.py     # Doxygen XML 생성
│   │   ├── doxygen_parser.py     # XML → 경량 JSON 변환
│   │   ├── callgraph_parser.py   # 함수 호출 관계 추출
│   │   └── diff_detector.py      # API 변경 감지 (update 모드)
│   ├── 01_cluster/               # Phase 1: Feature 분류
│   │   ├── feature_clusterer.py  # API → Feature 그룹화
│   │   └── taxonomy_reviewer.py  # 상속 계층 Taxonomy 설계 (LLM)
│   ├── 02_llm/                   # Phase 2: LLM 문서 생성
│   │   ├── llm_client.py         # LLM API 클라이언트 (내부/외부 통합)
│   │   ├── stage_a_classifier.py # Stage A: Feature 경계 보정
│   │   ├── stage_b_mapper.py     # Stage B: TOC · Blueprint 설계
│   │   └── stage_c_writer.py     # Stage C: Markdown 생성 + 심볼 검증
│   └── 03_render/                # Phase 3: 출력 렌더링
│       ├── md_renderer.py        # Frontmatter · 링크 삽입
│       ├── sidebar_generator.py  # 사이드바 JSON 생성
│       └── index_generator.py    # 인덱스 페이지 생성
├── cache/                        # 파이프라인 중간 산출물 (git-ignored)
├── repos/                        # 분석 대상 저장소 (git-ignored)
├── requirements.txt
└── pyproject.toml
```

---

## GitHub Actions — 자동화 워크플로

저장소에는 GitHub Actions 워크플로(`.github/workflows/`)가 정의되어 있어,
문서 생성과 주간 업데이트가 사람의 개입 없이 자동으로 실행된다.

### 워크플로 구성

| 파일 | 트리거 | 용도 |
|------|--------|------|
| `initial-full-gen.yml` | 수동(workflow_dispatch) | 최초 전체 문서 생성 |
| `weekly-update.yml` | 매주 자동 + 수동 | 주간 증분 업데이트 |

### CI/CD 흐름

```
최초 도입 또는 전체 재생성이 필요할 때
  → [수동] initial-full-gen 실행
      전체 파이프라인(--mode full) 실행
      → 생성된 문서를 새 브랜치에 커밋 → PR 자동 생성 → 리뷰 후 머지

이후 정기 운영
  → [자동] weekly-update  (매주 월요일 UTC 00:00)
      최신 소스 pull → 변경된 API 감지 → 증분 재생성(--mode update)
      → 변경된 문서를 브랜치에 커밋 → PR 자동 생성 → 리뷰 후 머지
```

---

### `initial-full-gen.yml` — 최초 전체 생성

프로젝트 초기 또는 문서를 완전히 새로 생성해야 할 때 수동으로 실행한다.

**실행 흐름**:
1. 저장소 체크아웃
2. Python 3.12 및 Doxygen 설치
3. `doc_config.yaml`의 `llm_environment` 값을 입력 파라미터로 교체
4. `pipeline.py --mode full --tier <선택> --limit <선택>` 실행
5. 생성된 `app-guide/` · `platform-guide/` 를 새 브랜치(`docs/initial-full-<tier>`)에 커밋
6. GitHub PR을 자동 생성

**입력 파라미터**:

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `tier` | `all` | `app` / `platform` / `all` |
| `environment` | `internal` | `internal` / `external` (LLM 선택) |
| `limit` | `0` | 0이면 제한 없음, 테스트 시 `3` 등으로 지정 |

**Secrets 필요**:
- `GEMINI_API_KEY` — external LLM 사용 시
- `INTERNAL_API_KEY` — internal LLM 사용 시
- `GITHUB_TOKEN` — PR 자동 생성 (기본 제공)

---

### `weekly-update.yml` — 주간 자동 업데이트

소스 저장소의 API 변경을 주기적으로 감지하여 문서를 최신 상태로 유지한다.

**트리거**:
- **자동**: 매주 월요일 00:00 UTC (cron: `0 0 * * 1`)
- **수동**: GitHub Actions 탭에서 즉시 실행 가능

**실행 흐름**:
1. 저장소 체크아웃
2. Python 3.12 및 Doxygen 설치
3. `pipeline.py --mode update --tier <선택>` 실행
   - 3개 소스 저장소를 최신으로 pull
   - 이전 실행(`last_run_commits.json`) 대비 변경된 API 감지
   - 변경 Feature만 선택적 재생성 또는 패치
   - 변경 없으면 LLM 호출 없이 렌더링만 재실행
4. 결과를 `docs/weekly-update` 브랜치에 커밋
5. GitHub PR 자동 생성 (이미 PR이 있으면 브랜치 force-push로 갱신)

**입력 파라미터** (수동 실행 시):

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `tier` | `all` | `app` / `platform` / `all` |
| `environment` | `internal` | LLM 선택. 자동 실행 시 Repository Variable `DEFAULT_ENVIRONMENT`를 참조 |

> **Repository Variable 설정**: 자동 실행(schedule) 시에는 `workflow_dispatch` 입력값이 없으므로
> GitHub 저장소의 `Settings → Secrets and variables → Variables` 에서
> `DEFAULT_ENVIRONMENT` 변수를 설정해야 한다 (예: `external`).
> 미설정 시 `external`로 fallback된다.

---

## 환경 준비

### Python 패키지 설치

`pipeline.py`는 venv가 없을 경우 자동으로 생성하고 `requirements.txt`를 설치한다.
수동으로 준비할 경우:

```bash
cd dali-doc-gen
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Doxygen 설치

Phase 0의 `doxygen_runner.py`가 `doxygen` 바이너리를 직접 호출한다.
시스템에 Doxygen 1.9 이상이 설치되어 있어야 한다.

```bash
# Ubuntu / Debian
sudo apt install doxygen

# macOS
brew install doxygen
```

### LLM API 키 설정

`doc_config.yaml`의 `llm_environment` 값에 따라 사용할 API가 결정된다.

```bash
# 외부 LLM (Gemini) 사용 시
export GEMINI_API_KEY=<your-gemini-api-key>

# 사내 LLM 사용 시
export INTERNAL_API_KEY=<base64-encoded-access-key:secret-key>
```

또는 `dali-doc-gen/` 디렉토리에 `.env` 파일을 생성해 키를 저장할 수 있다
(`.env.example` 참고).

---

## 설정 파일

### `config/repo_config.yaml`

분석 대상 저장소 및 Feature 재정의를 설정한다.

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
      - "dali-ui-foundation/integration-api"
      - "dali-ui-components/public-api"
      - "dali-ui-components/integration-api"
```

**`manual_features` 섹션**: 디렉토리 기반 자동 분류 결과를 오버라이드한다.

| 필드 | 설명 |
|------|------|
| `feature` | Feature ID (파일명 기준) |
| `display_name` | 문서에 표시할 이름 |
| `suppress_doc` | `true`이면 이 Feature의 독립 문서를 생성하지 않음 |
| `merge_into` | 다른 Feature 문서 생성 시 이 Feature의 API를 context로 포함 |
| `merge_mode` | `"full"` — permitted list·slim_sigs에 완전 통합 |
| `force_tree_review` | `true`이면 `taxonomy_reviewer`가 반드시 Tree 구조 여부를 검토 |

예시 — `actors` Feature를 `view` 문서에 통합하고 독립 문서 억제:

```yaml
manual_features:
  - feature: "actors"
    display_name: "Actor (Scene Graph Node)"
    source_package: "dali-core"
    suppress_doc: true        # actors.md 생성 안 함
    merge_into: "view"        # view 문서 생성 시 Actor API를 inherited context로 포함
```

---

### `config/doc_config.yaml`

LLM 모델 선택, 토큰 제한, Feature별 힌트를 설정한다.

#### LLM 환경 전환

```yaml
llm_environment: "external"   # "internal" 또는 "external"
```

- `internal`: 사내 LLM API (Gauss2) 사용
- `external`: Google Gemini API 사용

실행 시 `--llm` 플래그로 임시 오버라이드도 가능하다:

```bash
python src/pipeline.py --mode full --tier app --llm external
```

#### `feature_hints` — Feature별 프롬프트 힌트

특정 Feature에 대해 LLM에게 추가 지시사항을 주입할 수 있다.
Stage B(TOC 설계)와 Stage C(문서 작성) 모두에 반영된다.

```yaml
feature_hints:
  view:
    extra_context: |
      View supports Fluent API through method chaining. All property setters return
      View& so they can be chained together. Include a dedicated section explaining
      the method chaining pattern.

  absolute-layout:
    extra_context: |
      CRITICAL: To apply layout parameters to a View, use 'parentView.SetLayoutParams(params)'
      NOT SetLayout(), SetLayoutMode(), or SetLayoutParameters().
```

힌트는 Pass 1(자연어 섹션)과 Pass 2(코드 블록) retry 모두에 전달된다.

#### `token_overflow` — 대형 Feature 토큰 제어

```yaml
token_overflow:
  max_specs_per_feature: 2000      # 이 스펙 수 초과 시 oversized 마킹
  spec_token_threshold: 60000      # 이 토큰 수 초과 시 롤링 정제 모드 전환
  context_limit: 120000            # 사내 LLM 컨텍스트 한도 (안전 마진 적용)
  prompt_overhead: 4000            # 프롬프트 고정 텍스트 추정 토큰
```

스펙이 `spec_token_threshold`를 초과하면 Stage C가 자동으로 **롤링 정제 모드**로 전환된다.
전체 스펙을 한 번에 보내는 대신, 섹션 단위로 나누어 여러 번 호출한다.

---

## 전체 파이프라인 실행

모든 명령은 `dali-doc-gen/` 디렉토리에서 실행한다.

### 전체 새로 생성 (Full 모드)

```bash
# 앱 개발자용 문서만 생성
python src/pipeline.py --mode full --tier app

# 플랫폼 개발자용 문서만 생성
python src/pipeline.py --mode full --tier platform

# 두 종류 모두 생성
python src/pipeline.py --mode full --tier all
```

### 증분 업데이트 (Update 모드)

소스 저장소에 변경이 생겼을 때, 변경된 Feature만 선택적으로 재생성한다.
이전 실행의 `last_run_commits.json`을 기준으로 diff를 계산한다.

```bash
python src/pipeline.py --mode update --tier app
```

Update 모드의 내부 분류 기준:

| 분류 | 조건 | 처리 |
|------|------|------|
| `needs_regen` | 신규 Feature 추가 또는 taxonomy 구조 변경 | Stage B + Stage C 전체 재실행 |
| `needs_patch` | API 멤버 변경(메서드 추가·수정) | Stage C 패치 모드만 실행 |
| 변경 없음 | diff 없음 | LLM 호출 없이 렌더링만 재실행 |

### 공통 옵션

| 옵션 | 값 | 설명 |
|------|----|------|
| `--mode` | `full` / `update` | 전체 생성 또는 증분 업데이트 |
| `--tier` | `app` / `platform` / `all` | 출력 대상 독자 tier |
| `--features` | `"feat1,feat2"` | 처리할 Feature를 직접 지정 (디버깅용) |
| `--limit` | 숫자 | Stage B/C에서 처리할 Feature 수 상한 (디버깅용) |
| `--skip-pull` | — | `repo_manager`의 git pull 생략 (로컬 테스트용) |
| `--llm` | `internal` / `external` | LLM 환경 임시 오버라이드 |

### 실행 예시

```bash
# 특정 Feature 2개만 디버깅
python src/pipeline.py --mode full --tier app --features "view,image-view"

# Feature 수 3개로 제한하여 파이프라인 빠르게 검증
python src/pipeline.py --mode full --tier app --limit 3

# 외부 LLM으로 강제 전환하여 전체 생성
python src/pipeline.py --mode full --tier all --llm external

# git pull 없이 캐시된 소스로만 재생성
python src/pipeline.py --mode full --tier app --skip-pull
```

---

## 모듈별 단독 실행

파이프라인의 특정 단계만 재실행하거나 디버깅할 때 사용한다.
**모든 명령은 `dali-doc-gen/` 디렉토리에서 실행해야 한다.**

---

### Phase 0 — 정적 분석

#### `repo_manager.py` — 저장소 클론/업데이트

```bash
python src/00_extract/repo_manager.py
```

- `config/repo_config.yaml`에 정의된 3개 저장소를 `repos/` 아래 clone 또는 pull.
- 저장소가 이미 있으면 현재 브랜치를 pull하고, 없으면 새로 clone한다.
- **출력**: `repos/dali-core/`, `repos/dali-adaptor/`, `repos/dali-ui/`

---

#### `doxygen_runner.py` — Doxygen XML 생성

```bash
# 패키지별로 각각 실행
python src/00_extract/doxygen_runner.py --package dali-core
python src/00_extract/doxygen_runner.py --package dali-adaptor
python src/00_extract/doxygen_runner.py --package dali-ui
```

| 옵션 | 설명 |
|------|------|
| `--package` | 처리할 패키지 이름 (`dali-core`, `dali-adaptor`, `dali-ui` 중 하나) |

- `repos/` 하위 소스코드에 Doxygen을 실행한다.
- `CALL_GRAPH=YES` 옵션으로 함수 호출 그래프도 함께 생성한다.
- `doxygen` 바이너리가 PATH에 있어야 한다.
- **출력**: `cache/doxygen_json/<package>/xml/`

---

#### `doxygen_parser.py` — XML → JSON 변환

```bash
python src/00_extract/doxygen_parser.py
```

- `cache/doxygen_json/` 하위의 Doxygen XML을 파싱하여 LLM 입력에 적합한 경량 JSON으로 변환한다.
- private 멤버, 내부 구현 클래스, 빈 compound 등을 필터링해 토큰 낭비를 줄인다.
- namespace compound 안의 enum class를 synthetic compound로 추출하여 독립 Feature로 분류될 수 있게 한다.
- struct 내 익명 enum 값(예: `Actor::Property`의 익명 enum)도 DB에 등록한다.
- **출력**: `cache/parsed_doxygen/dali-core.json`, `dali-adaptor.json`, `dali-ui.json`

---

#### `callgraph_parser.py` — 호출 관계 추출

```bash
python src/00_extract/callgraph_parser.py
```

- Doxygen XML에서 함수 간 호출 관계(call graph)를 추출한다.
- Feature 클러스터링 단계에서 밀접하게 연관된 API 그룹을 병합하는 데 활용된다.
- **출력**: `cache/callgraph_json/dali-core.json`, `dali-adaptor.json`, `dali-ui.json`

---

#### `diff_detector.py` — API 변경 감지 (Update 모드 전용)

```bash
# 기본: parsed_doxygen/*.json vs *.json.old 비교
python src/00_extract/diff_detector.py

# 커밋 범위 지정
python src/00_extract/diff_detector.py --from-commit v1.0.0 --to-commit HEAD

# 특정 패키지만
python src/00_extract/diff_detector.py --from-commit HEAD~3 --to-commit HEAD --package dali-ui
```

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--from-commit` | `HEAD~5` | 비교 시작 커밋 또는 태그 |
| `--to-commit` | `HEAD` | 비교 끝 커밋 또는 태그 |
| `--package` | (전체) | 특정 패키지만 검사 |

- `pipeline.py --mode update` 실행 시 자동으로 호출된다.
- 단독 실행 시에는 `parsed_doxygen/*.json`이 미리 생성되어 있어야 한다.
- **출력**: `cache/changed_apis.json`

---

### Phase 1 — Feature 분류 · Taxonomy 설계

#### `feature_clusterer.py` — API → Feature 그룹화

```bash
python src/01_cluster/feature_clusterer.py
```

- `parsed_doxygen/` + `callgraph_json/`을 읽어 C++ 클래스·함수를 "Feature" 단위로 묶는다.
- 1차: 소스 파일의 디렉토리 경로와 네임스페이스 기반으로 그룹화한다.
- 2차: Call Graph 밀도를 기반으로 연관성이 높은 그룹을 병합한다.
- `repo_config.yaml`의 `manual_features` 오버라이드를 적용한다.
  - `suppress_doc: true` Feature는 feature_map에서 마킹되어 문서 생성 대상에서 제외된다.
  - `merge_into` Feature는 지정된 Feature의 API context에 통합된다.
- **출력**: `cache/feature_map/feature_map.json`

---

#### `taxonomy_reviewer.py` — Taxonomy 설계 (LLM Think)

```bash
# 증분 모드 (기본): 기존 taxonomy 보존, 신규·변경 Feature만 재검토
python src/01_cluster/taxonomy_reviewer.py

# 전체 재검토 모드: 기존 taxonomy를 무시하고 처음부터 재설계
python src/01_cluster/taxonomy_reviewer.py --full
```

| 옵션 | 설명 |
|------|------|
| `--full` | 기존 taxonomy 무시하고 전체 Feature를 LLM으로 재검토 |

- `feature_map.json`과 `parsed_doxygen`의 상속 관계(`base_classes`, `derived_classes`)를 분석한다.
- LLM(Think 모델)이 각 상속 계층에 대해 Tree 구조 vs Flat 문서를 결정한다.
  - **Tree**: 독립적으로 사용 가능한 하위 클래스가 3개 이상 → 부모 문서 + 자식 문서 분리
  - **Flat**: 단일 문서로 충분한 경우
- 후처리 패스로 tree_decision과 children/parent 간 불일치를 자동 교정한다.
  - `tree_decision="tree"`인데 `children=[]`이면 `flat` 또는 `leaf`로 다운그레이드
  - `decision_reason`과 실제 `parent` 불일치 시 자동 교정
- **출력**: `cache/feature_taxonomy/feature_taxonomy.json`

---

### Phase 2 — LLM 문서 생성

#### `stage_a_classifier.py` — Feature 경계 보정 (LLM Think)

```bash
python src/02_llm/stage_a_classifier.py
```

- `feature_map.json`을 읽어 모호한 API-Feature 경계를 LLM으로 보정한다.
- 어떤 API가 어떤 Feature에 속하는지 명확하지 않은 경우를 분류한다.
- **출력**: `cache/feature_map/feature_map_classified.json`

---

#### `stage_b_mapper.py` — TOC 설계 · Blueprint 생성 (LLM Think)

```bash
# 전체 Feature (tier 지정 필수)
python src/02_llm/stage_b_mapper.py --tier app

# 특정 Feature만
python src/02_llm/stage_b_mapper.py --tier app --features "view,image-view"

# 처음 N개만 처리 (디버깅)
python src/02_llm/stage_b_mapper.py --tier app --limit 3
```

| 옵션 | 설명 |
|------|------|
| `--tier` | `app` 또는 `platform` (필수) |
| `--features` | 처리할 Feature 이름 (쉼표 구분) |
| `--limit` | 처리할 최대 Feature 수 |

- 각 Feature의 문서 구조(섹션 목록, 학습 순서, TOC)를 Blueprint로 설계한다.
- `--tier`에 따라 허용 API 범위를 필터링한다 (app: public-api만, platform: 전체).
- taxonomy의 Tree 구조 정보를 주입하여 부모·자식 관계를 반영한 TOC를 생성한다.
- `doc_config.yaml`의 `feature_hints.extra_context`가 있으면 프롬프트에 주입한다.
- **출력**: `cache/doc_blueprints/stage_b_blueprints_app.json`
  또는 `stage_b_blueprints_platform.json`

> **주의**: `--features`로 일부 Feature만 실행하면 blueprints 파일이 해당 Feature만으로
> 덮어써진다. 이후 Stage C도 반드시 동일한 `--features` 옵션으로 실행해야 한다.

---

#### `stage_c_writer.py` — Markdown 생성 + 심볼 검증 (LLM Instruct)

```bash
# 전체 Feature 새로 작성
python src/02_llm/stage_c_writer.py --tier app

# 특정 Feature만
python src/02_llm/stage_c_writer.py --tier app --features "view,image-view"

# 처음 N개만 처리 (디버깅)
python src/02_llm/stage_c_writer.py --tier app --limit 3

# 패치 모드: 기존 문서 유지, 변경 API 부분만 업데이트
python src/02_llm/stage_c_writer.py --tier app --patch --patch-features "view"
```

| 옵션 | 설명 |
|------|------|
| `--tier` | `app` 또는 `platform` (필수) |
| `--features` | 처리할 Feature 이름 (쉼표 구분) |
| `--limit` | 처리할 최대 Feature 수 |
| `--patch` | 패치 모드 활성화 |
| `--patch-features` | 패치 모드에서 처리할 Feature 지정 (`--patch`와 함께 사용) |

- Stage B Blueprint를 읽어 Doxygen API 명세를 참조하며 Markdown을 작성한다.
- **2-Pass 생성 방식**으로 할루시네이션을 제어한다:
  - **Pass 1**: 전체 자연어 섹션 생성. 코드 블록이 들어갈 자리에 `[BLOCK_N]` 태그 삽입.
  - **Pass 2**: `[BLOCK_N]` 태그를 배치(batch)로 처리하여 코드 블록 또는 인라인 심볼 생성.
    생성된 모든 심볼을 Doxygen 기반 심볼 DB와 대조 검증.
    검증 실패 시 해당 블록만 최대 5회 재생성한다.
- **심볼 검증 규칙**:
  - 완전 네임스페이스(`Dali::Ui::View::SetPositionX`) 또는 단축형(`View::SetPositionX`) 모두 검증
  - 일반 enum의 값은 outer class scope 노출 형태(`AlphaFunction::EASE_IN_OUT`)도 허용
  - 완전형(`AlphaFunction::BuiltinFunction::EASE_IN_OUT`)도 DB에 함께 등록
  - 상속 메서드(`View::Add`, `ImageView::Add` 등 Actor에서 상속)도 alias로 등록
  - 5회 모두 FAIL 시 해당 코드 블록 태그를 제거하고 다음 블록을 처리 (문서 자체는 보존)
- Enum 값은 항상 `SCREAMING_SNAKE_CASE`로 작성하도록 강제한다.
- **출력**: `cache/validated_drafts/<tier>/<feature>.md`
  + `cache/code_block_results/<tier>/<feature>.json` (블록별 검증 결과)

---

### Phase 3 — 렌더링

#### `md_renderer.py` — Frontmatter · 링크 삽입

```bash
python src/03_render/md_renderer.py --tier app
python src/03_render/md_renderer.py --tier platform
```

| 옵션 | 설명 |
|------|------|
| `--tier` | `app` 또는 `platform` (필수) |

- `validated_drafts/<tier>/` 하위 파일에 YAML Frontmatter(`id`, `title`, `sidebar_label`)를 삽입한다.
- 본문 내 Feature 이름을 감지하여 taxonomy 기반 내부 링크로 변환한다.
- **출력**: `../app-guide/docs/` 또는 `../platform-guide/docs/`

---

#### `sidebar_generator.py` — 사이드바 JSON 생성

```bash
python src/03_render/sidebar_generator.py --tier app
python src/03_render/sidebar_generator.py --tier platform
```

| 옵션 | 설명 |
|------|------|
| `--tier` | `app` 또는 `platform` (필수) |

- taxonomy의 Tree / Flat / Leaf 구조를 반영한 중첩 네비게이션 JSON을 생성한다.
- 실제로 생성된 `.md` 파일에 대응하는 항목만 포함한다(orphan 링크 방지).
- 출력 형식은 Docusaurus v3 사이드바 포맷이지만, 다른 도구에서도 참조 가능한 표준 JSON이다.
- **출력**: `../app-guide/sidebar.json` 또는 `../platform-guide/sidebar.json`

---

#### `index_generator.py` — 인덱스 페이지 생성

```bash
python src/03_render/index_generator.py --tier app
python src/03_render/index_generator.py --tier platform
```

| 옵션 | 설명 |
|------|------|
| `--tier` | `app` 또는 `platform` (필수) |

- 전체 Feature 목록을 포함한 `index.md`를 생성한다.
- **출력**: `../app-guide/docs/index.md` 또는 `../platform-guide/docs/index.md`

---

## 캐시 디렉토리 구조

```
cache/
├── doxygen_json/                  # doxygen_runner.py 출력: Doxygen raw XML
│   ├── dali-core/xml/
│   ├── dali-adaptor/xml/
│   └── dali-ui/xml/
├── parsed_doxygen/                # doxygen_parser.py 출력: 경량 JSON
│   ├── dali-core.json
│   ├── dali-adaptor.json
│   ├── dali-ui.json
│   └── *.json.old                 # update 모드에서 diff 기준점으로 사용
├── callgraph_json/                # callgraph_parser.py 출력
│   ├── dali-core.json
│   ├── dali-adaptor.json
│   └── dali-ui.json
├── changed_apis.json              # diff_detector.py 출력: 변경 API 목록
├── feature_map/
│   ├── feature_map.json           # feature_clusterer.py 출력
│   ├── feature_map_classified.json # stage_a_classifier.py 출력
│   └── class_feature_map.json     # 클래스 → Feature 역방향 매핑
├── feature_taxonomy/
│   ├── feature_taxonomy.json      # taxonomy_reviewer.py 출력
│   └── feature_taxonomy.json.old  # update 모드 시 자동 백업
├── doc_blueprints/
│   ├── stage_b_blueprints_app.json      # Stage B 출력 (app tier)
│   └── stage_b_blueprints_platform.json # Stage B 출력 (platform tier)
├── validated_drafts/              # Stage C 출력: 검증 완료 초안
│   ├── app/
│   │   └── <feature>.md
│   └── platform/
│       └── <feature>.md
├── code_block_results/            # Stage C 코드 블록별 검증 결과
│   ├── app/
│   │   └── <feature>.json
│   └── platform/
│       └── <feature>.json
├── last_run_commits.json          # 마지막 실행 시 각 저장소의 HEAD 커밋 해시
└── llm_session_stats.json         # 실행 세션의 LLM 요청 수 · 입력 토큰 집계
```

---

## 출력 문서 구조

파이프라인 실행 완료 후 `dali-doc-gen/`의 상위 디렉토리에 문서가 생성된다.

```
dali-ui-documentation/
├── app-guide/
│   ├── docs/
│   │   ├── index.md               # 전체 Feature 목록
│   │   ├── view.md
│   │   ├── image-view.md
│   │   ├── label.md
│   │   └── ...
│   └── sidebar.json               # 사이드바 네비게이션 JSON
└── platform-guide/
    ├── docs/
    │   └── ...
    └── sidebar.json
```

각 문서의 구성:

```markdown
---
id: view
title: "View (Base UI Object)"
sidebar_label: "View (Base UI Object)"
---

# View (Base UI Object)

## 개요
...자연어 설명...

## 기본 사용법
    ```cpp
    View view = View::New();
    // 검증된 실제 API만 포함된 코드 예제
    ```

## 메서드 체이닝
...

## 관련 항목
- [ImageView](image-view)
- [Label](label)
```

---

## 주요 설계 결정

### 1. 심볼 검증 기반 할루시네이션 방지

LLM이 생성한 코드 예제의 모든 심볼(클래스, 메서드, enum 값)을 Doxygen에서 구축한
심볼 DB와 정확히 대조한다.

검증 단계:
1. 완전 네임스페이스(`Dali::Ui::ImageView::SetResourceUrl`)로 exact match 시도
2. 접두사 제거 후 단축형(`ImageView::SetResourceUrl`)으로 재시도
3. 변수 타입 추론(`ImageView img = ...` → `img.SetResourceUrl()`)으로 Class::Method 쌍 검증

검증 실패 시 해당 블록만 LLM에 재전송하며, 이전 실패 이유와 올바른 메서드 목록을 힌트로 함께 전달한다.

### 2. 2-Pass 코드 생성 분리

자연어 섹션(Pass 1)과 코드 블록(Pass 2)을 별도 LLM 호출로 분리한다.
이 방식의 장점:

- Pass 2에서 코드 블록만 집중적으로 검증·재생성할 수 있다.
- 자연어 품질에 영향을 주지 않고 코드만 교체할 수 있다.
- 배치(batch) 처리로 여러 블록을 한 번의 호출에 처리한다.

### 3. Tier 기반 Blueprint 분리

Stage B에서 `--tier` 값에 따라 별도의 Blueprint 파일을 생성한다.
app tier Blueprint에는 `public-api`만 포함되므로 `devel-api`·`integration-api` 클래스가
app 문서에 혼입될 가능성이 원천 차단된다.

### 4. 증분 업데이트 3단계 분류

Update 모드에서 taxonomy 구조 변경과 API 변경을 분리하여 최소한의 LLM 호출로 문서를 최신화한다:

- **needs_regen**: taxonomy 구조가 바뀐 경우 (부모·자식 관계 변경, 신규 Feature 추가)
  → 문서의 TOC 자체가 달라지므로 Stage B부터 전체 재실행
- **needs_patch**: API 멤버만 추가·변경된 경우
  → 기존 TOC 유지, Stage C 패치 모드로 변경된 섹션만 업데이트
- **변경 없음**: LLM 호출 없이 렌더링만 재실행

부모 Feature의 자식이 변경되면 부모도 `needs_regen`에 연쇄 포함(cascade invalidation)한다.

### 5. venv 자동 관리

`pipeline.py`를 어떤 Python 인터프리터로 실행해도 내부에서 자동으로 venv를 감지하거나 생성하고,
venv Python으로 재실행(`os.execv`)한다. 별도의 `source venv/bin/activate` 없이도 동작한다.

---

## 알려진 주의사항

- **`diff_detector.py`는 단독 실행 시 `pipeline.py`의 자동 백업 로직이 없다.**
  수동으로 `diff_detector.py`를 실행하려면 `parsed_doxygen/*.json.old` 파일이 존재해야
  `changed_apis.json`이 의미있는 결과를 생성한다.

- **`--mode full`은 이전 캐시를 재사용하지 않는다.**
  Phase 0부터 모든 단계를 처음부터 재실행한다. 소스 변경 없이 특정 단계만 재실행하고 싶다면
  해당 모듈을 직접 실행하는 것이 효율적이다.

- **Stage B를 `--features`로 일부만 실행하면 blueprints 파일이 해당 Feature만으로 덮어써진다.**
  이후 Stage C도 반드시 동일한 `--features` 옵션으로 실행해야 한다.
  전체 Feature로 되돌리려면 Stage B를 `--features` 없이 재실행한다.

- **Stage B의 `--tier` 옵션은 필수다.**
  생략하면 blueprint 파일이 올바른 tier suffix 없이 저장되어 Stage C가 잘못된 파일을 참조할 수 있다.

- **LLM 세션 통계**는 파이프라인 완료 후 터미널에 출력된다.
  `cache/llm_session_stats.json`에도 저장된다.

- **Enum 값 검증**: 일반 enum(`enum BuiltinFunction`)은 outer class scope에 노출되므로
  `AlphaFunction::EASE_IN_OUT` 형태가 유효하다. 반면 struct 내 익명 enum 값
  (`Actor::Property::SIZE`)은 outer scope에 노출되지 않는다.
  심볼 DB는 이 차이를 반영하여 구축된다.
