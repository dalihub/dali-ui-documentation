# [ENH-22] 검증 정확도 및 Pass 1 태그 준수 개선

## 개요

테스트 실행 로그 분석에서 발견된 4가지 문제.
검증 실패 / 환각 / Pass 1 태그 우회가 원인이며 독립적으로 수정 가능하다.

---

## 항목 1: named enum 완전형 미등록으로 인한 검증 실패

### 문제

```
BLOCK_8 [SAMPLE_CODE]: FAIL (unverified: ['AlphaFunction::BOUNCE']) — attempt 1
BLOCK_8 [SAMPLE_CODE]: FAIL (unverified: ['AlphaFunction::EASE_IN_OUT_SINE']) — attempt 2
BLOCK_8 [SAMPLE_CODE]: FAIL (unverified: ['AlphaFunction::EASE_IN_OUT']) — attempt 4
→ 5회 소진 후 tag 삭제
```

ENH-21에서 `AlphaFunction::BOUNCE` (단축형) 은 등록했으나
`AlphaFunction::BuiltinFunction::BOUNCE` (완전형) 은 등록하지 않았다.

LLM이 완전형으로 쓸 경우 매 시도마다 다른 enum 값으로 바꿔쓰면서 5회를 소진한다.
실제 DALi C++에서 두 형태 모두 유효하므로 둘 다 DB에 있어야 한다.

### 현재 등록 상태

| 심볼 | 역할 | 등록 여부 |
|---|---|---|
| `Dali::AlphaFunction::BuiltinFunction` | enum 타입 이름 (변수 선언) | ✅ 1129번 줄 (일반 멤버) |
| `Dali::AlphaFunction::BOUNCE` | 단축형 값 참조 | ✅ ENH-21 shortcut |
| `Dali::AlphaFunction::BuiltinFunction::BOUNCE` | 완전형 값 참조 | ❌ 미등록 |

### 해결

DB 빌드 루프에서 shortcut과 함께 완전형도 등록:

```python
# stage_c_writer.py — DB build loop (inline + client cached)
if mb.get("kind") == "enum" and mn:
    for ev in mb.get("enumvalues", []):
        ev_name = ev.get("name", "")
        if ev_name:
            shortcut = f"{cn}::{ev_name}"           # AlphaFunction::BOUNCE
            fullpath = f"{cn}::{mn}::{ev_name}"     # AlphaFunction::BuiltinFunction::BOUNCE
            for sym in (shortcut, fullpath):
                _full_names.add(sym)
                _full_names.update(_symbol_aliases(sym))
            _simple_names.add(ev_name)
```

두 곳 모두 적용:
- `run_two_pass_generation` 내부 inline DB 빌드 (현재 `_full_names` / `_simple_names`)
- `client._dali_full_names` 캐시 빌드 (1756~1784번 줄)

---

## 항목 2: absolute-layout에서 View::SetLayout 환각

### 문제

```
BLOCK_0 [SAMPLE_CODE]: FAIL (unverified: ['View::SetLayout']) — attempt 1~4
BLOCK_0 [SAMPLE_CODE]: FAIL (unverified: ['View::SetLayoutParameters']) — attempt 5
→ 5회 소진 후 tag 삭제
```

AbsoluteLayout 사용 시 레이아웃 파라미터를 View에 적용하려면 `View::SetLayoutParams(params)`가
올바른 메서드명이다. 그러나:
- `View`는 absolute-layout의 foreign class → specs에 없음 → permitted list에 없음
- LLM이 맥락상 자연스러운 `SetLayout()` / `SetLayoutParameters()`를 창작
- 5회 retry 전부 실패 → 코드 블록 강제 제거 → 문서에 구멍 발생

cross-feature API injection은 아키텍처를 복잡하게 만들고 오염 위험이 있으므로
`feature_hints.extra_context`로 올바른 메서드명을 명시하는 것이 적절하다.

### 해결

`doc_config.yaml`의 `absolute-layout` extra_context에 추가:

```yaml
absolute-layout:
  extra_context: |
    (기존 내용)
    CRITICAL: To apply layout parameters to a View, use `parentView.SetLayoutParams(params)` —
    NOT SetLayout(), SetLayoutMode(), or SetLayoutParameters().
    The exact method name on View is 'SetLayoutParams'. Any other name will cause a fatal
    validation failure.
```

---

## 항목 3: Pass 1에서 INLINE_CODE 태그 우회

### 문제

```
view: 4 SAMPLE_CODE + 0 INLINE_CODE
(다른 피처: label 5+24, input-field 7+13, animation 9+18)
```

view.md를 확인하면 `SetBackgroundColor`, `EnsureInteractiveTrait`, `Children` 등
메서드명이 일반 마크다운 백틱(`` ` ``)으로 직접 작성됐다.

`INLINE_CODE` 태그를 써야 하는 자리에 LLM이 직접 백틱을 쓰면:
- Pass 2 배치 생성 대상에서 제외됨
- Doxygen DB validation을 전혀 거치지 않음
- 환각 메서드명이 검증 없이 문서에 포함될 수 있음

view가 특히 심한 이유는 `tree` taxonomy로 인해 `taxonomy_context`에
"Sub-Components Overview 개요 페이지" 지시가 들어가고, LLM이 아키텍처 산문
중심으로 작성하면서 태그 규칙을 따르지 않기 때문이다.

### 해결

Pass 1 프롬프트에서 `INLINE_CODE` 태그 사용 강제 규칙을 강화:

```
현재:
  "For inline symbol references, use INLINE_CODE tag"

강화:
  "MANDATORY: Every single method name, property name, or class name that appears
   as an inline reference in prose MUST be written as [INLINE_CODE: SymbolName],
   NOT as backtick code. Writing `MethodName` directly bypasses validation and is
   STRICTLY FORBIDDEN. Use [INLINE_CODE: ...] exclusively."
```

---

## 항목 4: 사용자 정의 콜백 클래스로 인한 불필요한 retry

### 문제

```
view:               BLOCK_3 FAIL (unverified: ['MyClass::OnClicked']) — 4회 retry
animated-image-view: BLOCK_11 FAIL (unverified: ['MyClass::OnResourceReady']) — 2회 retry
```

예제 코드에서 앱 개발자가 직접 정의하는 콜백 핸들러 클래스(`MyClass`)가
Doxygen DB에 없어서 validator가 DALi API 환각으로 오탐한다.

`MyClass::OnClicked`는 DALi API가 아닌 사용자 구현 코드이므로 검증 대상이 아니다.
validator의 목적은 DALi API 심볼 환각을 잡는 것이지, 사용자 정의 클래스를 잡는 것이 아니다.

완전히 자유로운 예외를 허용하면 DALi 클래스명 오탐도 놓칠 수 있으므로
프롬프트로 LLM 행동을 `My` 접두사로 고정하고, validator는 그 약속을 신뢰하는 구조를 취한다.

### 해결

**프롬프트**: Pass 2 배치 프롬프트에 규칙 추가:
```
When writing example code that requires a user-defined class
(e.g. a callback handler), ALWAYS name it with a 'My' prefix
(e.g. MyApp, MyHandler, MyView). Never use other names for
user-defined classes in code examples.
```

**validator**: `My` 접두사 클래스 심볼 스킵:
```python
# verify_code_block() — symbols 처리 전
symbols = {
    s for s in symbols
    if not s.split("::")[0].startswith("My")
}
```

프롬프트를 어겨서 다른 접두사를 쓴 경우엔 여전히 retry가 발생하지만
이는 지금과 동일한 상황이므로 손해 없음.
프롬프트가 준수되는 대부분의 케이스에서 불필요한 retry가 제거됨.

---

## 영향 범위

| 파일 | 항목 |
|---|---|
| `src/02_llm/stage_c_writer.py` | 1, 3, 4 |
| `config/doc_config.yaml` | 2 |

항목 2는 `absolute-layout` 외에 `layouts`, `flex-layout`, `grid-layout`에도 동일하게 적용한다.
`SetLayoutParams`를 반드시 쓰라는 강제가 아니라, 쓸 일이 있을 때 올바른 메서드명을 알려주는 방식.
글로벌 context로 넣으면 다른 피처에 오염이 생기므로 각 피처 hint에 개별 적용한다.

## 우선순위

1 > 4 > 3 > 2 순으로 영향도가 크다.
1은 코드 블록 강제 제거를 직접 유발, 4는 불필요한 retry 소모, 3은 전체 피처 품질 보증 구멍, 2는 특정 피처 한정.
