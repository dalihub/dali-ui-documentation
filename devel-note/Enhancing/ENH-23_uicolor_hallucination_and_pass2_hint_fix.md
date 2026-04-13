# [ENH-23] UiColor 환각 차단 및 Pass 2에 feature_hint 전달 수정

## 개요

두 가지 독립적인 문제를 수정한다.

1. 전체 피처에서 `UiColor::RED` 등 존재하지 않는 프리셋을 사용하는 환각
2. `feature_hint_block`이 Pass 1에만 전달되고 Pass 2 retry에는 전달되지 않던 문제

---

## 항목 1: UiColor 프리셋 환각

### 문제

LLM이 `UiColor::RED`, `UiColor::BLUE` 등의 static 멤버를 사용하는 코드를 생성했으나
실제로 `UiColor`에 존재하는 프리셋은 다음 3개뿐이다.

```
UiColor::PRIMARY
UiColor::BACKGROUND
UiColor::OUTLINE
```

`Dali::Color::RED` 등은 `constexpr Vector4`로 `Dali::Color` 네임스페이스에 존재하며,
`UiColor(const Vector4& color)` 생성자를 통해 암묵적 변환이 가능하다.

```cpp
// 올바른 표현
view.SetBackgroundColor(UiColor(1.0f, 0.0f, 0.0f, 1.0f));  // RGBA 생성자
view.SetBackgroundColor(UiColor(Color::RED));                // Vector4 → UiColor
view.SetBackgroundColor(UiColor::PRIMARY);                   // 시맨틱 프리셋

// 잘못된 표현 (존재하지 않음)
view.SetBackgroundColor(UiColor::RED);   // ❌ 환각
```

이 문제는 view에 국한되지 않고 UiColor 인자를 받는 모든 피처(label, input-field 등)에서
동일하게 발생할 수 있다.

### 해결

Pass 1 (산문 생성)과 Pass 2 (코드 생성) 전역 프롬프트에 각각 UICOLOR RULE 추가.
특정 피처의 `feature_hint`가 아닌 전역 constraint로 처리.

**Pass 1 (single-call)** — `run_two_pass_generation` 내 inline prompt에 `UICOLOR RULE` 삽입  
**Pass 1 (rolling)** — `build_rolling_initial_prompt`에 동일 규칙 삽입  
**Pass 2** — `_build_batch_prompt`에 `CRITICAL CONSTRAINT - UiColor` 블록 추가

---

## 항목 2: feature_hint_block이 Pass 2 retry에 미전달

### 문제

ENH-22에서 `doc_config.yaml`의 `feature_hints`를 통해 피처별 힌트를 주입하는 기능이 있었으나,
이 힌트가 Pass 1 프롬프트에만 전달되고 Pass 2 코드 생성 프롬프트에는 전달되지 않았다.

```
feature_hint_block
  → run_two_pass_generation   → Pass 1 ✅
  → generate_code_blocks_batch            ← feature_hint_block 미전달
    → _build_batch_prompt                 ← feature_hint_block 미전달
      → Pass 2 retry 프롬프트 ❌
```

결과적으로 `absolute-layout`의 `SetLayoutParams` 힌트가 Pass 1에서는 반영됐지만
Pass 2 retry 시 LLM이 힌트를 보지 못해 `SetLayout()` / `SetLayoutParameters()` 환각을
5회 전부 반복했다.

### 해결

`feature_hint_block` 파라미터를 호출 체인 끝까지 전달:

```
generate_code_blocks_batch(... feature_hint_block="")
  → _build_batch_prompt(... feature_hint_block="")
    → f-string 내 {feature_hint_block} 주입 (OUTPUT 직전)

run_two_pass_generation 호출부:
  generate_code_blocks_batch(..., feature_hint_block=feature_hint_block)
```

---

## 영향 범위

| 파일 | 항목 |
|---|---|
| `src/02_llm/stage_c_writer.py` | 1, 2 |
