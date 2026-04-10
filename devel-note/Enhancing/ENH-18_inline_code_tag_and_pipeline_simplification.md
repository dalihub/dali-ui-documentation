# [ENH-18] 인라인 코드 태그 시스템 및 파이프라인 단순화

## 개요

코드블럭 생성 품질 개선(프롬프트/후처리)과 백틱 심볼을 Pass 2로 통합,
그리고 stage_d를 stage_c로 흡수하여 파이프라인을 단순화한다.

---

## 작업 목록

### 1. SCREAMING_SNAKE_CASE 규칙 추가
**대상**: `build_permitted_method_list()` 또는 `_build_batch_prompt()` 프롬프트

DALi enum 값은 항상 `SCREAMING_SNAKE_CASE`로 작성한다. LLM이
`None`, `Default`, `ScaleToFit` 같은 Pascal case로 쓰는 습관을 방지.

```
- All DALi enum values are written in SCREAMING_SNAKE_CASE.
  NEVER use Pascal case (None, ScaleToFit) or lower case for enum values.
  CORRECT: NONE, SCALE_TO_FIT, POSITION_PROPORTIONAL
  WRONG:   None, ScaleToFit, positionProportional
```

---

### 2. `using namespace` 후처리 제거
**대상**: `run_two_pass_generation()` 마지막 단계

생성된 코드블럭마다 `using namespace Dali;` / `using namespace Dali::Ui;`가
반복되면 지저분하다. LLM은 여전히 short name 기준으로 생성하되,
출력에서만 해당 줄을 strip한다.

```python
def _strip_using_namespace(md_text: str) -> str:
    """코드블럭 내 using namespace Dali 계열 줄 제거."""
    def strip_block(m):
        lines = m.group(1).splitlines()
        lines = [l for l in lines if not re.match(
            r'\s*using namespace Dali(::Ui)?;\s*$', l)]
        return f"```cpp\n{chr(10).join(lines)}\n```"
    return re.sub(r'```cpp\n(.*?)\n```', strip_block, md_text, flags=re.DOTALL)
```

---

### 3. 코드블럭 줄바꿈 강제
**대상**: 후처리 + Pass 2 프롬프트

일부 LLM이 산문 뒤에 바로 ` ```cpp `를 붙이는 경우가 있다.
후처리로 강제 삽입하고, 프롬프트에도 명시한다.

```python
# 후처리: ``` 앞에 줄바꿈 없으면 강제 삽입
text = re.sub(r'([^\n])(```)', r'\1\n\2', text)
```

프롬프트 추가:
```
- Every code fence (``` or ```cpp) MUST start on its own line.
```

---

### 4. 코드 의존적 산문 금지
**대상**: Pass 1 프롬프트

산문이 코드 존재를 전제로 작성되면 코드블럭 제거 시 문서가 어색해진다.

```
- Do NOT write phrases that reference upcoming code:
  WRONG: "as shown below", "see the following example",
         "the code below demonstrates", "refer to the snippet"
- Each sentence must be self-contained and meaningful without any code block.
  Code blocks are supplementary illustrations, not part of the explanation.
```

---

### 5. INLINE_CODE 태그 시스템
**대상**: Pass 1, Pass 2, `run_two_pass_generation()`

백틱 심볼을 Pass 2에서 생성·검증하여 할루시네이션을 방지한다.

#### Pass 1 변경

LLM이 백틱을 직접 쓰는 대신 `<!-- INLINE_CODE: 설명 -->` 태그를 사용한다.

규칙:
- 태그는 **문장 끝에만** 위치 (마침표 뒤)
- 태그를 제거해도 문장이 완전해야 함
- 심볼이 문장의 주어/목적어가 되어서는 안 됨

```
GOOD: "The position of a View can be controlled independently per axis.<!-- INLINE_CODE: SetPositionX, SetPositionY -->"
BAD:  "Use <!-- INLINE_CODE: SetPositionX --> to set the x position."
BAD:  "<!-- INLINE_CODE: SetPositionX --> sets the x position."
```

프롬프트 추가:
```
- Do NOT use backticks directly. Instead, place <!-- INLINE_CODE: description -->
  at the END of the sentence (after the period).
- The sentence MUST be complete and meaningful if the tag is removed entirely.
- Do NOT make the symbol the grammatical subject or object of the sentence.
```

#### Pass 2 변경

SAMPLE_CODE 태그와 함께 INLINE_CODE 태그도 배치로 처리한다.

```
[BLOCK_0] (code block) Create an ImageView with URL and fitting mode
[BLOCK_1] (inline) methods to set x and y position independently
[BLOCK_2] (inline) enum value for immediate image loading
```

INLINE_CODE 생성 규칙:
- 한 줄짜리 표현식만 생성
- 백틱, 코드 펜싱 없이 심볼 텍스트만 출력
- 여러 심볼은 쉼표로 구분: `SetPositionX, SetPositionY`

#### 치환 결과

- 성공: `문장.(SetPositionX, SetPositionY)`
- 실패: 태그만 제거 → `문장.` (문장 유지)

#### 검증

INLINE_CODE 생성 심볼도 Permitted List / full_names DB 기준으로 검증.
실패해도 문장이 살아남으므로 코드블럭처럼 retry 5회 적용.

---

### 6. stage_d 제거 및 stage_c 흡수
**대상**: `stage_c_writer.py`, `stage_d_validator.py`, 파이프라인 스크립트

stage_c가 생성과 검증을 모두 담당하게 되면 stage_d의 역할이 중복된다.

#### stage_d에서 stage_c로 이전할 것

| 기능 | 현재 위치 | 이전 후 |
|------|----------|---------|
| 코드블럭/인라인 심볼 검증 | stage_d | stage_c (이미 있음, INLINE_CODE로 확장) |
| validated_drafts/ 복사 | stage_d | stage_c 생성 완료 후 즉시 복사 |
| validation report JSON | stage_d | stage_c code_block_results 기반으로 생성 |

#### stage_d에서 제거할 것

- 문서 전체 재생성 retry loop (stage_c의 Pass 2 retry로 충분)
- 심볼 검증 로직 (stage_c로 이전)

#### stage_d_validator.py 처리

- 파일 삭제 또는 `_deprecated` 접미사로 보존
- 파이프라인 실행 스크립트에서 stage_d 호출 제거

---

### 7. `using` typedef alias DB 등록 (별도 추적)
**대상**: stage_a Doxygen 파서

`using FontWeight = Dali::TextAbstraction::FontWeight::Type` 같은 선언을
파서가 읽어 alias compound를 생성한다.

- `Text::FontWeight::BOLD` 같은 경로가 full_names에 등록되어 검증 통과
- stage_a 파서 수정이므로 1~6과 별도 작업

---

## 작업 순서

```
1~4 (프롬프트/후처리 즉시 적용)
  ↓
5 (INLINE_CODE 태그 시스템)
  ↓
6 (stage_d 제거 — 5 완료 후 진행)
  ↓
7 (typedef alias — 별도 추적)
```

1~4는 같은 커밋으로 묶어 처리 가능.
5와 6은 INLINE_CODE 시스템이 완성돼야 stage_d 제거가 의미 있으므로 순서를 지킨다.
