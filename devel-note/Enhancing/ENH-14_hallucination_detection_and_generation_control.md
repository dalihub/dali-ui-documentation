# [ENH] 할루시네이션 탐지 정확도 개선 및 생성 단계 제어 강화

## 개요

Stage D 검증기의 구조적 결함 2건과 Stage C 생성기의 프롬프트 제어 부족을 동시에 수정한다.
검증에서 놓치는 할루시네이션을 줄이고, 검증에서 발견된 할루시네이션을 저비용으로 수정하며,
생성 단계에서 애초에 할루시네이션이 덜 만들어지도록 개선한다.

### 배경

실제 생성된 문서에서 두 종류의 할루시네이션이 확인되었다.

- `ImageView::New().SetUrl("icon.png")` — 실제 API는 `SetResourceUrl()`. Stage D가 PASS 처리함
- `component.SetAccessibilityRole(role)` — `SetAccessibilityRole`은 View에 존재하지 않는 API. Stage D가 감지조차 못 함

원인 분석 결과 Stage D에 구조적 결함 2건, Stage C에 생성 제어 부족 2건이 있었다.

---

## 변경 1 — Stage D: dot-call 심볼 감지 추가

**파일:** `src/02_llm/stage_d_validator.py` — `extract_symbols_from_markdown()`

**문제**

```python
# 기존: :: 패턴만 추출
found = re.findall(r'(?:Dali|Ui|Dali::Ui)::[A-Za-z:]+', block)
found2 = re.findall(r'[A-Z][a-zA-Z0-9]+::[A-Za-z][a-zA-Z0-9_]+', block)
```

`component.SetAccessibilityRole(role)` 처럼 `.`으로 호출하는 메서드는 위 패턴에 매칭되지 않아
심볼 목록에 올라가지 않는다. 검증 대상에 없으므로 할루시네이션이 있어도 점수에 영향을 주지 않는다.

**수정**

코드 블록 내에서 `변수명.메서드명(` 패턴을 추가로 추출하여 simple name으로 등록한다.
C++ 예약어 및 소문자로 시작하는 일반 변수의 메서드 호출도 대상이 된다.

```python
# 추가: dot-call 패턴 (variable.MethodName()
dot_calls = re.findall(
    r'\b[a-z_][a-zA-Z0-9_]*\.([A-Z][a-zA-Z0-9_]+)\s*\(',
    block
)
symbols.update(dot_calls)
```

---

## 변경 2 — Stage D: 클래스-메서드 쌍 검증 강화

**파일:** `src/02_llm/stage_d_validator.py` — `build_doxygen_symbol_set()` + `verify_symbols()`

**문제**

기존 `verify_symbols()`는 `ImageView::SetUrl` 검증 시:
1. "ImageView"가 simple_names에 있는가? → YES
2. "SetUrl"이 simple_names 어딘가에 있는가? → YES (다른 클래스에 SetUrl이 있다면)

두 이름이 각각 존재하면 verified 처리한다. 실제로 `ImageView`가 `SetUrl`을 가지는지는 확인하지 않는다.

**수정**

`build_doxygen_symbol_set()` 에서 `(클래스 simple name)::(메서드 simple name)` 쌍 집합을 추가로 구축한다.
`verify_symbols()`는 `ClassName::Method` 패턴에 대해 이 쌍 집합을 우선 조회한다.

```python
# build_doxygen_symbol_set()에 pair_names 추가
pair_names = set()  # "ImageView::SetResourceUrl" 형태
for comp in compounds:
    comp_simple = comp_name.split("::")[-1]
    for mb in comp.get("members", []):
        pair_names.add(f"{comp_simple}::{mb.get('name', '')}")

# verify_symbols()에서 ClassName::Method 쌍 검증
if len(parts) >= 2:
    pair_key = f"{parts[-2]}::{parts[-1]}"
    if pair_key in pair_names:
        verified.append(sym)
    else:
        unverified.append(sym)
    continue
```

`ImageView::SetUrl` → `pair_names`에 없음 → unverified ✓
`ImageView::SetResourceUrl` → `pair_names`에 있음 → verified ✓

---

## 변경 3 — Stage D: Surgical Patch (블록 단위 재생성)

**파일:** `src/02_llm/stage_d_validator.py`

**문제**

현재 FAIL 판정 시 `regenerate_failed_document()`가 문서 전체를 재생성한다 (토큰 100% 재소비).
WARN은 아무 처리 없이 그냥 통과시켜 할루시네이션이 최종 문서에 잔존한다.

**수정**

오염된 코드 블록만 교체하는 surgical patch 방식을 도입한다.

```
extract_hallucinated_blocks(md_text, unverified_symbols)
  → unverified 심볼이 포함된 코드 블록 + 직전 섹션 헤더를 추출

surgical_patch_document(feat_name, md_text, unverified_symbols, specs, client)
  → 각 오염 블록에 대해 블록+헤더+허용 메서드 목록만 LLM에 전달 → 블록만 재생성 → 원본에 교체
```

**처리 흐름 변경**

| 판정 | 기존 | 변경 후 |
|------|------|---------|
| PASS | validated_drafts/ 복사 | 동일 |
| WARN | 그냥 복사 (할루시네이션 잔존) | surgical patch → 재검증 → 복사 |
| FAIL | 전체 문서 재생성 → 재검증 | surgical patch → 재검증 → 복사 또는 전체 재생성으로 escalate |
| LOW_CONTENT | 복사 | 동일 |

**토큰 변화**

| 상황 | 기존 | 변경 후 |
|------|------|---------|
| FAIL 1건 재생성 | 문서 전체 (3,000~8,000 tok) | 오염 블록만 (~200~500 tok) |
| WARN 처리 | 추가 없음 | 소량 추가 (블록 수정) |
| 전체 retry 비용 | 기준 100% | 약 10~20% 수준 |

---

## 변경 4 — Stage C: 허용 메서드 목록 기반 생성 제어

**파일:** `src/02_llm/stage_c_writer.py`

**문제**

기존 ANTI-HALLUCINATION 규칙은 부정형 지시다:
```
Do NOT invent non-existent APIs or parameters.
Only call methods whose exact name appears in the API specs list below.
```

LLM은 아래 JSON 덩어리에서 메서드 이름을 직접 참조하지 않고,
"이 feature라면 이런 메서드가 있을 것 같다"는 추론으로 이름을 만들어낸다.

**수정**

specs에서 호출 가능한 메서드 이름만 뽑아 허용 목록(permitted list)을 생성하고,
이를 프롬프트에 별도 블록으로 주입한다.

```python
def build_permitted_method_list(specs):
    methods = sorted({
        s["name"].split("::")[-1]
        for s in specs
        if s.get("kind") == "function"
        and not s["name"].split("::")[-1].startswith("operator")
        and not s["name"].split("::")[-1].startswith("~")
    })
    if not methods:
        return ""
    return (
        "PERMITTED API CALLS — complete list of callable methods for this feature.\n"
        "Call ONLY methods from this list in ALL code examples:\n"
        + "\n".join(f"  - {m}" for m in methods)
    )
```

---

## 변경 5 — Stage C: Enum-only feature 코드 예제 억제

**파일:** `src/02_llm/stage_c_writer.py`

**문제**

`view-accessibility-enums` 같은 feature는 specs에 enum/struct 정의만 있고 호출 가능한 함수가 없다.
LLM에게 "코드 예제를 포함하라"는 지시가 있으면 없는 setter를 창작한다.

ENH-11이 upstream(Doxygen 파서)에서 enum 구조를 올바르게 추출하는 수정이라면,
본 변경은 생성 단계에서 코드 예제 자체를 억제하는 제어다. 두 수정은 독립적으로 효과가 있다.

**수정**

specs에 `kind == "function"` 항목이 없으면 enum-only feature로 판단하고,
코드 예제 없이 타입과 값의 의미만 설명하도록 지시한다.

```python
def is_enum_only_feature(specs):
    return not any(s.get("kind") == "function" for s in specs)
```

```
# 프롬프트 내 CODE EXAMPLE STRATEGY 블록 (enum-only 시)
TYPE DEFINITIONS ONLY — This feature provides enum/struct type definitions.
There are NO callable methods in the specs.
- Do NOT write any code block calling SetXxx(), GetXxx(), or any method.
- Describe each enum value and its semantic meaning in prose.
- If a type declaration is needed, show only: TypeName var = TypeName::VALUE;
- Do NOT show integration with View or other classes via method calls.
```

---

## 변경 6 — Stage C: Parent 페이지 child 메서드 최소 주입

**파일:** `src/02_llm/stage_c_writer.py`

**문제**

`view` 같은 parent 페이지 생성 시 taxonomy_context가 child 이름(ImageView, Label 등)을 LLM에 알려주고,
feature_hints가 `Children({...})` 예제 작성을 유도한다.
그러나 child 클래스의 API 스펙은 LLM에 전달되지 않는다.
LLM이 이름만 알고 메서드를 추론 → `SetUrl`, `SetAccessibilityRole` 등 창작.

**수정**

`tree_decision == "tree"` 페이지 생성 시 각 child 클래스의 메서드 이름 목록을 최소한으로 추출하여
taxonomy_context에 함께 주입한다. 변경 4의 허용 목록에도 child 메서드를 포함시킨다.

```python
# parent 페이지 생성 시 child 메서드 수집 (메서드명만, 상세 스펙 없음)
if tree_decision == "tree" and children:
    child_method_lines = []
    for child_name in children:
        child_bp = blueprints_index.get(child_name, {})
        child_specs_raw, _ = get_api_specs(
            child_bp.get("packages", []),
            child_bp.get("apis", []),
            allowed_tiers
        )
        child_methods = sorted({
            s["name"].split("::")[-1]
            for s in child_specs_raw
            if s.get("kind") == "function"
            and not s["name"].split("::")[-1].startswith(("operator", "~"))
        })[:8]
        if child_methods:
            display = taxonomy.get(child_name, {}).get("display_name", child_name)
            child_method_lines.append(f"  {display}: [{', '.join(child_methods)}]")
```

변경 4와 함께 적용해야 한다. child 메서드를 알려주면서 허용 목록으로 범위를 제한하지 않으면
LLM의 창작 범위가 오히려 넓어진다.

---

## 변경 간 의존 관계

```
변경 4 (허용 목록)  ──┐
변경 5 (enum-only)   ├──→ 생성 단계 할루시네이션 억제
변경 6 (child 주입)  ──┘  (변경 6은 변경 4 없이 단독 적용 금지)

변경 1 (dot-call)   ──┐
변경 2 (쌍 검증)    ──┤──→ 남은 할루시네이션 정확히 탐지
변경 3 (surgical)   ──┘  (변경 3은 변경 1+2 정확도에 의존)
```

변경 6은 반드시 변경 4와 함께 적용한다.
변경 3은 변경 1+2가 적용된 후에 의미가 있다 (탐지 정확도가 높아야 surgical patch 대상이 정확함).

---

## 수정 파일 목록

| 파일 | 변경 내용 |
|------|-----------|
| `src/02_llm/stage_d_validator.py` | 변경 1, 2, 3 |
| `src/02_llm/stage_c_writer.py` | 변경 4, 5, 6 |

---

## 수정 후 파이프라인 효과

| 항목 | 수정 전 | 수정 후 |
|------|---------|---------|
| dot-call 할루시네이션 탐지 | 불가 (0%) | 탐지됨 |
| Class::Method 쌍 검증 | 각각 존재하면 verified | 쌍이 Doxygen에 있어야 verified |
| WARN 문서 처리 | 할루시네이션 그대로 통과 | surgical patch 후 통과 |
| FAIL 재생성 비용 | 전체 문서 100% | 오염 블록만 ~10~20% |
| Enum-only feature 예제 | 없는 setter 창작 | 코드 예제 없음, 타입 설명만 |
| Parent 페이지 child 예제 | child 메서드 추론 → 오류 | child 허용 메서드 목록 기반 정확한 예제 |

---

## 구현 체크리스트

- [x] `stage_d_validator.py` — `build_doxygen_symbol_set()`: `pair_names` 집합 추가 반환
- [x] `stage_d_validator.py` — `extract_symbols_from_markdown()`: dot-call 패턴 추출 추가
- [x] `stage_d_validator.py` — `verify_symbols()`: `pair_names` 기반 쌍 검증으로 교체
- [x] `stage_d_validator.py` — `extract_hallucinated_blocks()`: 새 함수 추가
- [x] `stage_d_validator.py` — `surgical_patch_document()`: 새 함수 추가
- [x] `stage_d_validator.py` — `main()`: WARN/FAIL 처리 흐름에 surgical patch 적용
- [x] `stage_c_writer.py` — `build_permitted_method_list()`: 새 함수 추가
- [x] `stage_c_writer.py` — `is_enum_only_feature()`: 새 함수 추가
- [x] `stage_c_writer.py` — `main()`: blueprints_index 구축, child 메서드 수집, 프롬프트 블록 주입
