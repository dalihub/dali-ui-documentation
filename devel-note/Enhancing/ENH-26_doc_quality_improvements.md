# [ENH-26] 문서 퀄리티 향상 — TOC 개선, 주의사항 제약, 시그널/코드 패턴, Merge 품질

## 개요

5가지 독립적인 개선을 수행한다.

1. **taxonomy_reviewer Phase A-2: stable feature에 brief 추가** — merge target 선택 시 LLM에 feature ID만 전달하던 것을 brief 포함 요약으로 교체
2. **stage_b TOC 프롬프트 개선** — API 나열 대신 실제 UI 개발 주제 단위 카테고리 구성 유도
3. **stage_b feature_hints `typical_use_cases` 지원** — doc_config에 use case 힌트를 추가하면 TOC 설계에 반영, 없으면 기존 동작 유지
4. **stage_c 주의사항 섹션 Doxygen 기반 제약** — `warnings[]`/`notes[]` 에 근거한 내용만 허용
5. **stage_c view_context 시그널 패턴 + doc_config `code_patterns` 지원** — DALi 관용 패턴을 명시적으로 제공하여 코드 문법 정확도 향상

---

## 작업 1: Phase A-2 stable feature brief 추가 (`taxonomy_reviewer.py`)

### 문제

`apply_small_feature_merges()` 내에서 merge 대상 후보(stable features)를 LLM에 전달할 때 feature ID 문자열만 보낸다.

```python
# 현재
stable_ids = [f["feature"] for f in stable_feats]
```

LLM이 feature 이름만으로 merge 적합성을 판단해야 하므로, 이름이 모호하면 잘못된 target을 선택할 수 있다.

### 해결

stable_summary로 교체하여 `display_name`과 `brief`를 함께 전달한다.

```python
# 변경 후
stable_summary = [
    {
        "feature_id": f["feature"],
        "display_name": f.get("display_name", f["feature"]),
        "brief": f.get("description", ""),
    }
    for f in stable_feats
]
```

프롬프트 내 `stable_ids` 참조도 `stable_summary`로 교체한다.

또한 `small_summary`에서 `api_count`를 제거한다. 이 값은 이미 임계값 미만임이 보장된 상태에서 전달되므로 LLM 판단에 불필요하다.

### 영향 범위

| 파일 | 변경 내용 |
|---|---|
| `src/01_cluster/taxonomy_reviewer.py` | `stable_ids` → `stable_summary` (brief 포함), `small_summary`에서 `api_count` 제거, 프롬프트 수정 |

---

## 작업 2: stage_b TOC 프롬프트 개선 (`stage_b_mapper.py`)

### 문제

현재 TOC 설계 프롬프트가 "Design a logical Table of Contents"라는 일반적인 지시만 주어 LLM이 API를 클래스나 메서드 그룹별로 나열하는 방식으로 흐르기 쉽다.

### 해결

UI 개발자가 실제로 찾는 주제 단위로 섹션을 구성하도록 유도하는 지시를 추가한다.

**변경 전 (line ~332):**
```
Design a logical Table of Contents (TOC) layout for the feature module '{feat_name}'.
```

**변경 후:**
```
Design a Table of Contents (TOC) layout for the feature module '{feat_name}'.
Organize sections around meaningful UI development topics
(e.g., "Layout & Sizing", "Event Handling", "Visual Configuration", "Loading & Lifecycle")
that reflect how developers actually use this feature in real applications.
Do NOT enumerate APIs alphabetically or group sections by class name.
Each section should represent a distinct developer task or concern,
not a list of methods that happen to share a class.
```

### 영향 범위

| 파일 | 변경 내용 |
|---|---|
| `src/02_llm/stage_b_mapper.py` | TOC 프롬프트 첫 지시문 수정 |

---

## 작업 3: stage_b `typical_use_cases` 지원 (`stage_b_mapper.py`, `doc_config.yaml`)

### 목적

특정 피처에 대해 개발자가 실제로 쓰는 시나리오를 TOC 설계 힌트로 제공하면, 섹션 구성이 더 실용적으로 만들어진다. 없으면 기존 동작을 그대로 유지한다.

### doc_config.yaml 스키마 (추가 예시)

```yaml
feature_hints:
  image-view:
    extra_context: "..."
    typical_use_cases:
      - "정적 이미지를 지정된 크기 영역에 맞게 표시"
      - "URL 기반 비동기 이미지 로딩 및 로딩 상태 처리"
      - "FittingMode/SamplingMode로 이미지 스케일 정책 제어"
  animated-image-view:
    extra_context: "..."
    typical_use_cases:
      - "GIF 또는 프레임 시퀀스 기반 반복 애니메이션 표시"
      - "재생/정지/속도 제어"
```

### stage_b 변경

```python
# 기존 hint_extra 추출 이후에 추가
typical_use_cases = feature_hints.get(feat_name, {}).get("typical_use_cases", [])
use_cases_block = ""
if typical_use_cases:
    use_cases_str = "\n".join(f"  - {uc}" for uc in typical_use_cases)
    use_cases_block = f"""
TYPICAL USE CASES — Ensure the TOC covers these developer workflows:
{use_cases_str}
"""
```

이 블록을 프롬프트의 `feature_hint_block` 바로 다음에 주입한다.

### 영향 범위

| 파일 | 변경 내용 |
|---|---|
| `src/02_llm/stage_b_mapper.py` | `typical_use_cases` 추출 및 프롬프트 주입 추가 |
| `config/doc_config.yaml` | 기존 feature_hints 항목에 `typical_use_cases` 필드 추가 (선택적) |

---

## 작업 4: stage_c 주의사항 섹션 Doxygen 기반 제약 (`stage_c_writer.py`)

### 문제

현재 WRITING STANDARD의 Notes/Warnings 항목이 다음과 같다:

```
4. NOTES AND WARNINGS: Use blockquotes (> Note: or > Warning:) for non-obvious behavior.
```

LLM이 API 문서에 없는 주의사항을 창작할 수 있어 할루시네이션 위험이 있다.

### 해결

Doxygen에서 파싱된 `warnings[]`, `notes[]` 필드에 근거한 내용만 허용하도록 제약을 추가한다.

**변경 후:**
```
4. NOTES AND WARNINGS: Use blockquotes (> Note: or > Warning:) ONLY for behaviors
   explicitly documented in the warnings[] or notes[] fields of the API specs provided below.
   Do NOT invent pitfalls, edge cases, or caveats that are not grounded in the provided
   API documentation.
```

### 영향 범위

| 파일 | 변경 내용 |
|---|---|
| `src/02_llm/stage_c_writer.py` | Pass 1 프롬프트 WRITING STANDARD 항목 4 수정 |

---

## 작업 5: view_context 시그널 패턴 + code_patterns 지원 (`stage_c_writer.py`, `doc_config.yaml`)

### 5-A: view_context 시그널 연결 패턴 추가

현재 view_context는 View/Actor 계층 사용 규칙만 담고 있다. DALi 시그널 연결 문법을 추가하여 LLM이 잘못된 패턴(Qt-style 등)을 쓰지 않도록 한다.

기존 view_context 블록 끝에 추가:

```python
- Signal connection patterns (두 스타일 중 문맥에 맞는 것을 사용):
    Style 1 — 멤버 함수:  view.SignalName().Connect(this, &MyClass::OnHandler);
    Style 2 — 자유 함수:  view.SignalName().Connect(&OnHandler);
  시그널은 전용 접근자 메서드를 통해 획득한다 (예: TouchedSignal(), KeyEventSignal()).
  NEVER use lowercase connect() or Qt-style SIGNAL/SLOT macros.
```

> **TODO**: 실제 DALi UI 시그널 접근자 이름을 확인하여 예시를 교체할 것. → `devel-note/TODO.md` 참고

### 5-B: doc_config `code_patterns` 필드 및 stage_c 주입

doc_config.yaml에 `code_patterns` 최상위 필드를 추가한다.

```yaml
code_patterns: |
  // ── Animation (property 기반 값 변경) ──────────────────────────────
  Dali::Animation anim = Dali::Animation::New(1.0f);  // duration in seconds
  anim.AnimateTo(Dali::Property(view, Dali::Actor::Property::POSITION),
                 Dali::Vector3(200.0f, 0.0f, 0.0f));
  anim.Play();

  // ── Property 설정 (전용 setter 우선, SetProperty는 fallback) ─────────
  // Preferred: 전용 setter 사용
  imageView.SetProperty(Dali::Ui::ImageView::Property::RESOURCE_URL, url);
  // Fallback: 전용 setter가 없는 경우에만
  view.SetProperty(Dali::Actor::Property::SIZE, Dali::Vector2(width, height));
```

> **TODO**: 각 패턴의 API 이름/네임스페이스를 실제 DALi 헤더 기준으로 검토. → `devel-note/TODO.md` 참고

stage_c에서 doc_config 로드 시 `code_patterns`를 읽어 Pass 1 프롬프트에 주입한다.

```python
# doc_config 로드 후
code_patterns = doc_config.get("code_patterns", "")
code_patterns_block = f"""
DALi COMMON CODE PATTERNS — use these idioms in code examples where applicable:
{code_patterns}
""" if code_patterns else ""
```

Pass 1 프롬프트의 `{code_example_strategy}` 바로 앞에 `{code_patterns_block}`을 삽입한다.

### 영향 범위

| 파일 | 변경 내용 |
|---|---|
| `src/02_llm/stage_c_writer.py` | view_context에 시그널 패턴 추가, `code_patterns_block` 생성 및 Pass 1 프롬프트 주입 |
| `config/doc_config.yaml` | `code_patterns` 최상위 필드 추가 |

---

## 전체 영향 범위 요약

| 파일 | 작업 |
|---|---|
| `src/01_cluster/taxonomy_reviewer.py` | 1 |
| `src/02_llm/stage_b_mapper.py` | 2, 3 |
| `src/02_llm/stage_c_writer.py` | 4, 5 |
| `config/doc_config.yaml` | 3 (optional), 5 |

## 작업 순서

작업 1 → 작업 2, 3 (병렬 가능) → 작업 4, 5 (병렬 가능)

- 작업 3의 doc_config 스키마 변경은 stage_b 코드 변경과 함께 진행
- 작업 5의 TODO 항목은 코드 구현 후 사용자가 직접 검토하여 수정
