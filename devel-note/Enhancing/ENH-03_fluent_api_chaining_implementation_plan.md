# Fluent API Method Chaining 문서화 지원 구현 계획

## 1. 목표

dali-ui 컴포넌트(View 및 그 하위 클래스)가 지원하는 Fluent API(Method Chaining) 패턴이
생성 문서의 코드 예제에 자연스럽게 반영되도록 한다. 동시에 체이닝을 지원하지 않는
dali-core 클래스(Actor 등)의 예제에는 체이닝 스타일이 잘못 들어가지 않도록 보호한다.

---

## 2. 배경

### 2.1 View의 Fluent API 구조

`Dali::Ui::View`(및 하위 클래스 `Label`, `Button`, `InputField` 등)는 모든 property setter가
`View&` (또는 구체 타입 `&`)를 반환한다. 이를 통해 선언적 초기화가 가능하다.

```cpp
// dali-ui: 체이닝 가능
auto label = Label::New()
  .SetText("Hello")
  .SetFontSize(20)
  .SetTextColor(UiColor::WHITE);

// dali-core: 체이닝 불가 (void 반환)
auto actor = Actor::New();
actor.SetPosition(Vector3(0, 0, 0));
actor.SetSize(Vector3(100, 100, 0));
```

View에는 체이닝 전용 헬퍼도 제공된다:
- `Children({...})` — 자식 계층 선언적 구성
- `AsInteractive(lambda)` — Trait 연결 + 설정을 체인 안에서 처리
- `AsSelectable(lambda)` — SelectableTrait 연결
- `With(lambda)` — 체인을 끊지 않고 임의 로직 삽입
- `As(View& self)` — 체인 중간에 외부 변수 캡처

### 2.2 API 구분 기준

Doxygen 파싱 결과의 `type` 필드(반환 타입)로 판별 가능하다:

| 반환 타입 예시 | 체이닝 가능 여부 |
|---|---|
| `"Label &"`, `"View &"`, `"Button &"` | ✅ chainable |
| `"void"`, `"bool"`, `"int"`, `"float"` | ❌ not chainable |
| `"const Label &"` (const ref getter) | ❌ not chainable |
| `"Actor &"` operator= | ❌ not chainable (operator 제외) |
| `"TouchEventSignalType &"` TouchedSignal | ❌ not chainable (Signal 제외) |

판별 조건:
- `type`이 `&`로 끝나고
- `const`로 시작하지 않으며
- 메서드 이름이 `operator`로 시작하지 않고
- 메서드 이름이 `Signal`로 끝나지 않는 경우

---

## 3. 영향 파일 및 변경 범위

| 파일 | 변경 유형 | 비고 |
|---|---|---|
| `config/doc_config.yaml` | 설정 추가 | `feature_hints` 섹션 신설 |
| `src/02_llm/stage_c_writer.py` | 기능 추가 | `get_api_specs()` + 프롬프트 2곳 + rolling 시그니처 |
| `src/02_llm/stage_b_mapper.py` | 기능 추가 | `load_doc_config()` + TOC 프롬프트 |
| `src/02_llm/stage_a_classifier.py` | **변경 없음** | 코드 예제 미생성 |
| `src/01_cluster/feature_clusterer.py` | **변경 없음** | 구조 분류만 담당 |
| `src/01_cluster/taxonomy_reviewer.py` | **변경 없음** | tree/leaf 판단만 담당 |
| `src/pipeline.py` | **변경 없음** | 자동 반영 |

---

## 4. 상세 구현 계획

### 4.1 `config/doc_config.yaml` — `feature_hints` 섹션 추가

feature별로 Stage B(TOC 설계)와 Stage C(문서 생성) 양쪽에 주입할 추가 컨텍스트를 정의한다.

```yaml
feature_hints:
  view:
    extra_context: |
      View supports Fluent API through method chaining. All property setters return
      View& (or the concrete subclass &) so they can be chained together.
      IMPORTANT: Include a dedicated section explaining the method chaining pattern.
      Show declarative UI tree construction using Children({...}), AsInteractive(lambda),
      AsSelectable(lambda), With(lambda), and As(view&) methods.
      Always prefer chained initialization style over separate-statement style in examples.
```

이 섹션은 Stage B와 Stage C 양쪽에서 읽혀 TOC 설계 및 문서 생성에 반영된다.
다른 feature에도 동일한 방식으로 커스텀 지시를 추가할 수 있는 확장 포인트가 된다.

---

### 4.2 `stage_c_writer.py` — 변경 1: `get_api_specs()`에 `chainable` 플래그 추가

**수정 위치:** `get_api_specs()` 내 멤버 스펙 조립 블록

멤버의 반환 타입을 검사하여 체이닝 가능 여부를 `"chainable": true` 필드로 표시한다.

```python
# 추가: chainable 플래그 (Fluent API setter 판별)
ret_type = mb.get("type", "")
mb_name = mb.get("name", "")
if (ret_type.endswith("&")
        and not ret_type.startswith("const")
        and not mb_name.startswith("operator")
        and not mb_name.endswith("Signal")):
    mb_spec["chainable"] = True
```

**영향 분석:**
- `chainable` 필드가 없는 스펙은 기존과 동일하게 처리됨
- 토큰 증가량: `"chainable": true` per 해당 메서드 — 미미함
- dali-core Actor: `operator=`는 operator 제외, `TouchedSignal` 등은 Signal 제외 → 플래그 미부착
- dali-ui Label: `SetText`, `SetFontSize` 등 28개 Set* 메서드에 플래그 부착

---

### 4.3 `stage_c_writer.py` — 변경 2: 프롬프트에 chaining 스타일 지시 + feature_hints 주입

**수정 위치:** `main()` 내 full 생성 모드 — `foreign_context` 조립 직후

**① `feature_hints` 로드:**

`load_doc_config()`가 이미 `main()` 상단에서 호출되고 있으므로, 결과에서 추출한다.

```python
feature_hints = doc_config.get("feature_hints", {})
```

**② chaining 스타일 지시 조립 (specs 수집 후):**

```python
has_chaining = any(s.get("chainable") for s in specs)
if has_chaining:
    chaining_context = """
CODE EXAMPLE STYLE — METHOD CHAINING:
This feature's setter methods return a reference to the object (marked "chainable": true).
ALWAYS prefer the chained initialization style in code examples:
    auto view = ComponentName::New()
      .SetProperty1(value1)
      .SetProperty2(value2);
Do NOT use separate-statement style for chainable setters unless showing a specific
multi-step workflow where intermediate state must be captured.
"""
else:
    chaining_context = """
CODE EXAMPLE STYLE:
This feature's setters return void. Use separate statements for each setter call.
Do NOT attempt to chain setter calls on this feature's objects.
"""
```

**③ feature_hints extra_context 조립:**

```python
hint_extra = feature_hints.get(feat_name, {}).get("extra_context", "")
feature_hint_block = f"""
FEATURE-SPECIFIC GUIDANCE:
{hint_extra}
""" if hint_extra else ""
```

**④ 표준 프롬프트에 주입:**

```
{view_context}
{tier_context}
{taxonomy_context}
{foreign_context}
{chaining_context}      ← 신규
{feature_hint_block}    ← 신규
```

**rolling 정제 경로 대응:**

`run_rolling_refinement()` 및 `build_rolling_initial_prompt()` 시그니처에
`chaining_context=""`, `feature_hint_block=""` 인자 추가 후 Pass 1 프롬프트에 전달.

---

### 4.4 `stage_b_mapper.py` — `feature_hints` 로드 및 TOC 프롬프트 주입

Stage B는 현재 `doc_config.yaml`을 로드하지 않는다.

**① `yaml` import 및 `load_doc_config()` 추가:**

```python
import yaml
DOC_CONFIG_PATH = PROJECT_ROOT / "config" / "doc_config.yaml"

def load_doc_config():
    if not DOC_CONFIG_PATH.exists():
        return {}
    with open(DOC_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
```

**② `main()` 상단에서 로드:**

```python
doc_config = load_doc_config()
feature_hints = doc_config.get("feature_hints", {})
```

**③ feature 루프 내에서 TOC 프롬프트에 주입:**

taxonomy_context 조립 직후:

```python
hint_extra = feature_hints.get(feat_name, {}).get("extra_context", "")
feature_hint_block = f"""
FEATURE-SPECIFIC GUIDANCE FOR TOC DESIGN:
{hint_extra}
""" if hint_extra else ""
```

TOC 프롬프트의 `{taxonomy_context}` 다음에 `{feature_hint_block}` 삽입.

---

## 5. 사이드 이펙트 점검

### 5.1 Stage A — 영향 없음

Stage A는 `feature_map.json`의 ambiguous cluster를 stable category로 병합한다. 코드
예제를 생성하지 않으므로 `chainable` 플래그나 `feature_hints`와 무관하다.

### 5.2 Stage B — TOC 구조 변화

`view` feature의 TOC에 "Method Chaining" 또는 "Fluent API" 섹션이 추가된다.
이는 Stage C가 해당 섹션의 내용을 채워야 함을 의미하므로 **의도된 변화**다.
다른 feature는 `feature_hints`에 등록되지 않으면 기존과 동일하다.

### 5.3 Stage C — 표준 경로

- `chainable` 플래그가 있는 스펙: dali-ui 컴포넌트들 → 체이닝 스타일 지시 활성화
- `chainable` 플래그가 없는 스펙: dali-core 클래스들 → "void 반환, 체이닝 금지" 지시 활성화
- `feature_hint_block`이 비어있는 feature: 기존 프롬프트와 사실상 동일

### 5.4 Stage C — rolling 정제 경로

`run_rolling_refinement()` 시그니처 변경이 필요하므로 호출부도 함께 수정.
현재 호출 위치는 `main()` 내 단 한 곳이므로 범위가 제한적이다.

### 5.5 `--patch` 모드

패치 모드는 `build_patch_prompt()`를 사용하며, 기존 문서 스타일 보존이 원칙이므로
chaining 스타일 지시를 패치 프롬프트에 추가하지 않는다.

### 5.6 토큰 예산 영향

`chainable: true` 필드 추가로 인한 토큰 증가는 메서드당 약 3~4 토큰으로 미미하다.
`feature_hint_block` 크기는 `view`의 경우 약 100토큰 수준으로 `SPEC_TOKEN_THRESHOLD`에
영향을 줄 수 없다.

---

## 6. 구현 단계

| 단계 | 작업 | 파일 | 상태 |
|---|---|---|---|
| Step 1 | `doc_config.yaml`에 `feature_hints.view.extra_context` 추가 | `config/doc_config.yaml` | ✅ 완료 |
| Step 2 | `get_api_specs()`에 `chainable` 플래그 검출 로직 추가 | `stage_c_writer.py` | ✅ 완료 |
| Step 3 | `main()`에서 `feature_hints` 로드, `chaining_context` + `feature_hint_block` 조립 | `stage_c_writer.py` | ✅ 완료 |
| Step 4 | 표준 프롬프트에 두 블록 주입 | `stage_c_writer.py` | ✅ 완료 |
| Step 5 | `run_rolling_refinement()` 시그니처 + `build_rolling_initial_prompt()` 수정 | `stage_c_writer.py` | ✅ 완료 |
| Step 6 | `stage_b_mapper.py`에 `load_doc_config()` 추가 및 TOC 프롬프트 주입 | `stage_b_mapper.py` | ✅ 완료 |

---

## 7. 검증 기준

- [ ] `view.md` 재생성 시 "Method Chaining" 또는 "Fluent API" 전용 섹션이 포함됨
- [ ] `view.md`의 코드 예제가 `View::New().SetX(...).SetY(...)` 체이닝 스타일을 사용함
- [ ] `label.md`의 코드 예제가 `Label::New().SetText(...).SetFontSize(...)` 스타일을 사용함
- [ ] dali-core feature(`animation`, `actors` 등) 문서의 코드 예제에 체이닝이 없음
- [ ] `--patch` 모드 실행 시 기존 문서 스타일 변경 없음
- [ ] rolling 정제 모드(`actors` 등 oversized feature) 정상 동작 유지
