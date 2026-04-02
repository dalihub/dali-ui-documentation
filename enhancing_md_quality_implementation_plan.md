# 마크다운 품질 개선 구현 계획

## 개요

DALi 문서 생성 파이프라인의 품질 및 정확성을 개선하기 위한 모든 수정 사항을 기술한다.
이슈는 논의 순서에 따라 0~5번으로 번호를 부여했다.
가장 큰 구조적 변경은 FIX-1(티어 인식 드래프트 아키텍처)로, 거의 모든 스테이지에 영향을
미치므로 가장 먼저 구현해야 한다.

---

## 이슈 요약

| # | 문제 | 근본 원인 | 주요 파일 |
|---|------|-----------|-----------|
| 0 | taxonomy children 중복 (`image-view` x3) | LLM이 child 슬러그를 추론하지 못할 때 parent 슬러그를 반복 | `taxonomy_reviewer.py` |
| 1 | app-guide 문서에 integration/devel-api 내용 포함 | 드래프트가 티어 비인식 상태로 작성됨 | Stage B, C, D, E 전체 |
| 2 | 패치 모드에서 "API Updates" 섹션 추가 | 패치 프롬프트에 changelog 금지 규칙 없음 | `stage_c_writer.py` |
| 3 | 문서가 부모/형제/integration 영역으로 벗어남 | 프롬프트에 범위 집중 규칙 없음 | `stage_b_mapper.py`, `stage_c_writer.py` |
| 4 | API 사용 설명이 너무 부실함 | 작성 가이드라인이 너무 추상적 | `stage_c_writer.py` |
| 5 | 서브섹션이 너무 얕게 작성됨 | 4번과 동일 | `stage_c_writer.py` |

---

## FIX-0: Taxonomy Children 중복 제거 및 검증

### 근본 원인 분석

`taxonomy_reviewer.py`에서 LLM에게 child 컴포넌트에 대한 feature 슬러그 할당을 요청한다.
LLM이 올바른 슬러그를 결정하지 못할 경우 parent의 슬러그를 반복 사용하는 문제가 있다.
`image-view`의 경우 LLM은 3개의 child 컴포넌트(ImageView, AnimatedImageView,
LottieAnimationView)를 정확히 인식했지만 `["image-view", "image-view", "image-view"]`를
출력했다.

### 수정 방법: 코드 후처리 + 프롬프트 제약 추가

**수정 A — `taxonomy_reviewer.py`에 `sanitize_children()` 후처리 함수 추가:**

LLM 응답 파싱 후, taxonomy에 기록하기 전에 호출한다.

```python
def sanitize_children(parent_key, children):
    seen = set()
    valid = []
    for c in children:
        feature_key = c.get("feature", "")
        if not feature_key:
            continue
        if feature_key == parent_key:       # 자기 참조 제거
            continue
        if feature_key in seen:             # 중복 제거
            continue
        seen.add(feature_key)
        valid.append(c)
    return valid
```

sanitize 후 `len(valid) == 0`이면 decision을 자동으로 `"flat"`으로 다운그레이드한다.

**수정 B — LLM 프롬프트에 제약 조건 추가:**

```
IMPORTANT: Each child `feature` slug in the `children` array must be unique and must
NOT equal the parent feature name `{feat_name}`. Use lowercase-hyphenated slugs that
describe what makes each child component distinct (e.g. "animated-image-view", not
"image-view" again).
```

---

## FIX-1: 티어 인식 드래프트 아키텍처 (대규모 구조 변경)

### 배경

현재 드래프트는 티어 구분 없이 단일 디렉토리에 작성된다.

```
cache/markdown_drafts/*.md     ← 티어 구분 없음
cache/validated_drafts/*.md
```

최종 출력 단계에서 `app-guide/`와 `platform-guide/`로 복사하지만, 그 시점에는 이미
LLM이 integration-api 내용을 산문으로 작성해버린 상태라 필터링이 불가능하다.
티어 구분은 Stage B(TOC 설계)와 Stage C(작성) 단계에서 LLM에게 올바른 API 스펙과
범위 규칙을 제공할 때 이루어져야 한다.

### 새로운 캐시 디렉토리 구조

```
cache/
  markdown_drafts/
    app/          ← Stage C --tier app 출력
    platform/     ← Stage C --tier platform 출력
  validated_drafts/
    app/          ← Stage D --tier app 출력
    platform/     ← Stage D --tier platform 출력
```

### API 티어 규칙

| 티어 | 허용 `api_tier` 값 (parsed_doxygen 기준) |
|------|------------------------------------------|
| app | `public-api` 만 |
| platform | `public-api`, `devel-api`, `integration-api` 모두 |

### 파일별 변경 사항

#### `stage_b_mapper.py`

- `--tier` 인자 추가 (choices: `app`, `platform`, default: `app`)
- TOC 생성 프롬프트에 티어별 지침 주입:
  - app: `"Design TOC for app developers. Do NOT include sections related to internal engine lifecycle, integration hooks, or platform extension. Focus on public-api usage."`
  - platform: `"Design TOC for platform/engine developers. Include internal architecture, lifecycle, thread safety, and integration API sections where relevant."`
- 블루프린트 자체는 티어 무관 (prompt만 달라짐). cache 경로 변경 없음.

#### `stage_c_writer.py`

- `--tier` 인자 추가 (choices: `app`, `platform`, default: `app`)
- `get_api_specs(pkg_names, api_names_list, allowed_tiers)`:
  - `allowed_tiers` 파라미터 추가
  - compound 필터링: `if allowed_tiers and comp.get("api_tier") not in allowed_tiers: continue`
  - app: `allowed_tiers = {"public-api"}`
  - platform: `allowed_tiers = None` (필터링 없음)
- 드래프트 출력 디렉토리 변경:
  - `OUT_DRAFTS_DIR = CACHE_DIR / "markdown_drafts" / tier`
- 전체 생성 프롬프트에 티어별 제약 추가:
  - app: `"TIER CONSTRAINT: This is app-guide documentation. ONLY reference and describe public-api classes and methods. Do NOT mention devel-api, integration-api, engine internals, or platform extension points. If a concept requires devel-api, note it briefly as 'platform-level detail' and refer to the platform guide."`
  - platform: `"TIER CONSTRAINT: This is platform-guide documentation. Reference public-api, devel-api, and integration-api as needed. Explain engine internals, thread safety, lifecycle, and extension points in detail."`

#### `stage_d_validator.py`

- `--tier` 인자 추가
- 드래프트 읽기 경로: `cache/markdown_drafts/{tier}/`
- 검증 완료 파일 저장: `cache/validated_drafts/{tier}/`

#### `md_renderer.py`

- `--tier` 인자 추가 (이미 출력 디렉토리 로직 존재; 읽기 경로만 업데이트)
- 읽기 경로: `cache/validated_drafts/{tier}/` (없으면 `markdown_drafts/{tier}/`로 fallback)

#### `index_generator.py`, `sidebar_generator.py`

- 읽기 경로도 `{tier}/` 서브디렉토리를 참조하도록 변경

#### `pipeline.py`

- Stage B, C, D, E 서브프로세스 호출 시 `--tier {args.tier}` 전달
- 기본값은 `app`

#### `scripts/run_extract_all.sh`

- `FULL_ARGS`와 `UPDATE_ARGS`에 `--tier app` 추가

---

## FIX-2: 패치 모드 — "API Updates" 섹션 생성 금지

### 문제

API 변경 후 문서를 패치할 때 LLM이 "API Updates", "Recent Changes", "What's New" 같은
섹션을 새로 추가하는 경우가 있다. 이는 changelog처럼 읽혀 기술 가이드 형식을 깨뜨린다.

### 수정

`stage_c_writer.py`의 `build_patch_prompt()` STRICT PATCHING RULES에 추가:

```
- Do NOT add any 'API Updates', 'Changelog', 'Recent Changes', 'What's New', or
  'Migration Guide' section. Update the existing document content naturally — as if
  the document was always written to reflect the current API state.
- A reader should not be able to tell that the document was updated; it should read
  as a single, coherent technical guide.
```

---

## FIX-3: Feature 범위 집중 규칙

### 문제

문서가 다른 페이지에 속해야 할 내용을 포함한다.
- `image-view.md`에 "View-Based Architecture" 설명 (`view.md`에 있어야 함)
- `image-view.md`에 "Extending AnimatedImageView" 섹션 (`animated-image-view.md`에 있어야 함)
- app-guide 문서에 integration-api 패턴 설명

### Stage B 수정 (`stage_b_mapper.py`) — TOC 프롬프트에 범위 규칙 추가

```
SCOPE RULES for TOC design:
- Design sections ONLY for the '{feat_name}' feature. Do not design sections that
  primarily explain the parent class '{parent}' or sibling components.
- The first section must be an introduction to '{feat_name}' specifically — not a
  general overview of the parent category.
- Do not design sections for extending or subclassing '{feat_name}' unless the feature
  itself is designed as a base class for app developers to subclass.
- Do not include sections about integration, engine internals, or platform extension
  for app-guide documentation.
```

### Stage C 수정 (`stage_c_writer.py`) — 작성 프롬프트에 집중 규칙 추가

```
FOCUS AND SCOPE RULES:
- Write ONLY about '{feat_name}'. Stay strictly within its feature boundary.
- If you mention a parent class (e.g. View, Actor), do so only to show how
  '{feat_name}' inherits or extends it — 1-2 sentences maximum.
- If you mention a sibling component (e.g. AnimatedImageView in image-view.md), write
  1 sentence and add '→ See: [SiblingName]' — do not write its API details here.
- Begin the document with a 1–2 paragraph overview that specifically answers:
  "What is {feat_name}?", "When should I use it?", and "What makes it distinct?"
- Do NOT include integration, extension, or platform-level sections in app-guide docs.
```

---

## FIX-4 & FIX-5: API 상세 설명 및 서브섹션 깊이 강화

### 문제

- API 메서드 설명이 너무 간략함 (메서드 이름을 재서술하는 수준)
- 서브섹션에 예제나 맥락 설명이 부족함
- 가이드만 읽어서는 동작하는 앱을 작성할 수 없음

### Stage C 수정 (`stage_c_writer.py`) — 작성 기준 강화

현재 작성 가이드라인을 아래 기준으로 교체:

```
WRITING STANDARD — each section and subsection must meet ALL of these:

1. INTRODUCTION PARAGRAPH: Every section starts with 1-2 sentences explaining
   the overall purpose of that section in practical terms.

2. API METHOD COVERAGE: For every non-trivial API method in this feature:
   - WHAT: What does this method do? (1 sentence)
   - WHY: When and why would a developer call this? (1-2 sentences)
   - HOW: Explain each parameter by name, type, and meaning. Explain the return value.
     Note any important side effects, preconditions, or error conditions.
   - CODE: A complete, compilable C++ code snippet showing a realistic usage scenario.
     Code must use only the API signatures provided in the spec above.

3. SUBSECTION DEPTH: Each ### subsection must be self-contained. A developer
   reading only that subsection should be able to use that specific API correctly
   without needing to read the rest of the document.

4. CODE EXAMPLES: Every section must contain at least one realistic code example.
   Examples must show typical usage patterns, not trivial one-liners.
   Show the full context: create the object, configure it, add it to the scene, etc.

5. NOTES AND WARNINGS: Use blockquotes (> Note: or > Warning:) for:
   - Non-obvious behavior or gotchas
   - Performance implications
   - Thread-safety constraints
   - Deprecated APIs

6. COMPLETENESS GOAL: A developer who reads only this document should be able
   to write a basic working application that uses the '{feat_name}' feature.
   Do not omit important APIs because they seem "obvious".
```

---

## 구현 순서

수정 사항 간 의존성이 있으므로 아래 순서로 구현한다.

```
FIX-0   taxonomy_reviewer.py 후처리 함수 + 프롬프트 제약 추가
  │
FIX-1   티어 인식 파이프라인 (Stage B → C → D → E → pipeline.py → run_extract_all.sh)
  │         (FIX-3의 티어별 API 필터링은 FIX-1이 선행되어야 의미가 있음)
  │
  ├── FIX-2   build_patch_prompt() 규칙 추가        (FIX-1과 병행 가능)
  ├── FIX-3   Stage B, C 범위 집중 규칙             (FIX-1과 병행 가능)
  └── FIX-4/5 Stage C 작성 기준 강화               (FIX-1과 병행 가능)
```

FIX-2, FIX-3, FIX-4/5는 모두 Stage C 프롬프트를 수정하므로 한 번에 적용한다.

---

## 변경 파일 요약

| 파일 | 변경 내용 |
|------|-----------|
| `src/01_cluster/taxonomy_reviewer.py` | `sanitize_children()` 추가 + 프롬프트 제약 |
| `src/02_llm/stage_b_mapper.py` | `--tier` 추가, 티어별 TOC 프롬프트 + 범위 규칙 |
| `src/02_llm/stage_c_writer.py` | `--tier` 추가, 티어 필터링 `get_api_specs()`, 티어·범위·상세 작성 규칙, changelog 금지 |
| `src/02_llm/stage_d_validator.py` | `--tier` 추가, 티어별 드래프트 디렉토리 읽기/쓰기 |
| `src/03_render/md_renderer.py` | `--tier` 추가, `validated_drafts/{tier}/` 읽기 |
| `src/03_render/index_generator.py` | 드래프트 경로 `{tier}/` 서브디렉토리 참조 |
| `src/03_render/sidebar_generator.py` | 동일 |
| `pipeline.py` | 모든 스테이지 호출 시 `--tier` 전달 |
| `scripts/run_extract_all.sh` | `--tier app` 추가 |

총 9개 파일 수정.

---

## 하위 호환성 참고

- 기존 `cache/markdown_drafts/*.md` (flat)는 새 코드에서 읽히지 않는다.
  마이그레이션은 불필요하며, `--tier app`으로 Stage C를 재실행하면 된다.
- `validated_drafts/`도 동일하게 재구성된다. Stage C 실행 후 Stage D를 재실행한다.
- `--tier` 기본값이 `app`이므로, 기존 스크립트에서 `--tier`를 지정하지 않아도
  app 가이드 동작은 그대로 유지된다.
