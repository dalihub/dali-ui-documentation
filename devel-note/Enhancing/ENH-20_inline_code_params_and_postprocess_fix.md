# [ENH-20] 인라인 코드 파라미터 표시 및 postprocess regex 수정

## 개요

두 가지 수정 사항:

- **1**: `_postprocess_markdown` regex — 닫는 `` ``` `` 앞 trailing whitespace 미매칭 버그 수정
- **2**: Pass 2 (inline) 포맷 — 메서드 심볼에 파라미터 타입 표시 (`SetPositionX` → `SetPositionX(float)`)

---

## 작업 상세

### 1. _postprocess_markdown trailing whitespace 수정

**대상**: `stage_c_writer.py` `_postprocess_markdown()`

#### 현재 상태

```python
text = re.sub(
    r'(```(?:cpp|c\+\+)?)\n(.*?)\n```',
    lambda m: _strip_using_ns(m),
    text,
    flags=re.DOTALL | re.IGNORECASE
)
```

닫는 `` ``` `` 앞에 `\n` 만 허용하므로, LLM 출력에 trailing whitespace가 있으면
(`code_line  \n` `` ``` ``) 패턴이 매칭 안 됨.
→ `using namespace Dali` 제거 미적용, 코드블럭 변환 누락.

#### 변경 방법

```python
r'(```(?:cpp|c\+\+)?)\n(.*?)\n\s*```'
#                              ^^^
#                              \n\s* 로 교체 — trailing whitespace/빈줄 허용
```

결과: LLM 출력의 trailing whitespace 유무와 무관하게 안정적으로 매칭.

---

### 2. Pass 2 (inline) 포맷 — 파라미터 타입 포함

**대상**: `stage_c_writer.py` `_build_batch_prompt()`

#### 현재 상태

```
(inline) → output the label followed by a SINGLE LINE of symbol text only.
  No backticks, no code fences, no explanation — just the symbol(s):
  [BLOCK_1]
  SetPositionX, SetPositionY

  [BLOCK_2]
  LoadPolicy::IMMEDIATE
```

심볼 이름만 반환 → 백틱 안이 `SetPositionX` 처럼 너무 단순.

#### 변경 방법

메서드/함수와 기타 심볼을 구분해서 포맷 지시:

```
(inline) → output the label followed by a SINGLE LINE symbol.
  - Method/function: write MethodName(Type1, Type2) — param types only, no variable names, no return type.
    If overloaded, choose the variant that best matches the surrounding prose context.
  - Enum value, property, or class name: write the symbol as-is.
  No backticks, no code fences, no explanation.
  [BLOCK_1]
  SetPositionX(float)

  [BLOCK_2]
  LoadPolicy::IMMEDIATE
```

LLM이 specs(slim_sigs)와 주변 prose 맥락을 동시에 참조하므로 오버로드 선택 가능.

#### 예상 결과

| 이전 | 이후 |
|------|------|
| `SetPositionX` | `SetPositionX(float)` |
| `SetResourceUrl` | `SetResourceUrl(const std::string&)` |
| `LoadPolicy::IMMEDIATE` | `LoadPolicy::IMMEDIATE` (변경 없음) |
| `ImageView` | `ImageView` (변경 없음) |

---

## 작업 순서

```
1 (regex 수정)    ← 독립, 버그픽스
2 (inline 포맷)   ← 독립, 프롬프트 수정
  ↓ 같은 커밋 가능
```
