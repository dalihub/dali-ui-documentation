# [ENH-19] 프롬프트 토큰 및 코드 효율 개선

## 개요

코드 리뷰를 통해 발견된 네 가지 효율 문제를 수정한다.

- **1**: `re.compile()` 을 함수 내부에서 매 호출마다 수행 → 모듈 상수로 이전
- **2**: LLM 프롬프트에 불필요한 spec 필드 포함 → `brief` + `signature` 만 전달
- **3**: `TERMINOLOGY OVERRIDE` 블록을 View/Actor 무관 feature에도 전송 → 조건부 포함
- **4**: `_build_typedef_aliases()` 에서 alias_leaf(`FontWeight` 단독) 등록 → 제거

---

## 작업 상세

### 1. Regex 모듈 상수화

**대상**: `stage_c_writer.py`

현재 `get_api_specs()`, `build_permitted_method_list()`, `_parse_block_responses()`,
`_verify_code_block()` 내부에서 `re.compile()` 이 함수 호출마다 실행된다.
피처 50개 파이프라인이면 같은 패턴을 50회 컴파일하는 꼴.

대상 패턴:

| 현재 위치 | 패턴 |
|-----------|------|
| `get_api_specs()` ~line 524 | `r'\b(?:Ui::)?([A-Z][A-Za-z0-9_]+)(?:::Type)?\b'` |
| `build_permitted_method_list()` ~line 613 | `r'\b([A-Z][A-Za-z0-9_]+)(?:::Type\|::Filter\|::Mode)?\b'` |
| `_parse_block_responses()` ~line 749 | `r'\[BLOCK_(\d+)\]'` |
| `_verify_code_block()` ~line 778 | scope_sym, var_decl, dot_call 세 패턴 |

**변경 방법**: 모듈 상단 상수로 이동.

```python
# 모듈 상단
_RE_SIG_TYPE    = re.compile(r'\b(?:Ui::)?([A-Z][A-Za-z0-9_]+)(?:::Type)?\b')
_RE_ENUM_PARAM  = re.compile(r'\b([A-Z][A-Za-z0-9_]+)(?:::Type|::Filter|::Mode)?\b')
_RE_BLOCK_LABEL = re.compile(r'\[BLOCK_(\d+)\]', re.IGNORECASE)
_RE_SCOPE_SYM   = re.compile(r'\b(?:Dali::Ui::|Dali::)?[A-Z][A-Za-z0-9_]*(?:::[A-Za-z0-9_]+)+')
_RE_VAR_DECL    = re.compile(
    r'((?:Dali::Ui::|Dali::)?[A-Z][A-Za-z0-9_]*(?:::[A-Za-z0-9_]+)*)\s*&?\s+'
    r'([a-z_][a-zA-Z0-9_]*)\s*[=;{(,)]'
)
_RE_DOT_CALL    = re.compile(r'\b([a-z_][a-zA-Z0-9_]*)\.([A-Z][a-zA-Z0-9_]+)\s*\(')
```

결과: 동일 출력, CPU 연산 감소.

---

### 2. Spec 필드 정리

**대상**: `stage_c_writer.py` `get_api_specs()` 반환값 → Pass 1 / Pass 2 프롬프트

#### 현재 상태

`get_api_specs()` 가 반환하는 spec dict:

```python
{
  "name": ...,
  "kind": ...,
  "brief": ...,
  "signature": ...,
  "params": [...],          # 파라미터 설명
  "returns": ...,           # 반환값 설명
  "notes": [...],           # @note 태그
  "warnings": [...],        # @warning 태그
  "code_examples": [...],   # @code 블록 (Doxygen 원문)
  "detailed": ...,          # 상세 설명 전체
}
```

이 딕트가 `json.dumps(specs, indent=2)` 로 Pass 1, Pass 2 프롬프트에 그대로 들어간다.

#### 문제

- `code_examples`: Doxygen 원문 예제는 옛 API 스타일(전체 네임스페이스, Actor 직접 사용 등)을
  담고 있어 우리 코드 스타일 규칙과 충돌할 수 있다. 오히려 역효과.
- `params` / `returns` / `notes` / `warnings` / `detailed`: Pass 1 prose 생성에 불필요.
  Pass 2 코드 생성도 `signature` 만으로 충분하다.
- Pass 1 rolling 모드에서는 청크당 spec JSON 크기가 클수록 토큰 한도 초과 빈도가 높아진다.

#### 변경 방법

```python
# 변경 전
mb_spec = {
    "name": f"{c_name}::{mb.get('name', '')}",
    "kind": mb.get("kind"),
    "brief": mb.get("brief", ""),
    "signature": mb.get("signature", ""),
    "params": mb.get("params"),
    "returns": mb.get("returns"),
    "notes": mb.get("notes"),
    "warnings": mb.get("warnings"),
    "code_examples": mb.get("code_examples"),
}

# 변경 후
mb_spec = {
    "name": f"{c_name}::{mb.get('name', '')}",
    "kind": mb.get("kind"),
    "brief": mb.get("brief", ""),
    "signature": mb.get("signature", ""),
}
```

compound 자체 엔트리(`c_name`)도 동일하게 `name`, `kind`, `brief` 만 남긴다.

#### 예상 효과

feature당 spec JSON 크기 30~50% 감소. Pass 1 rolling 청크 수 감소 가능.
Pass 2 프롬프트도 작아져 배치 한도 안에 더 많은 블록이 들어간다.

#### 주의사항

`build_permitted_method_list()` 는 `specs` 에서 `signature` 를 직접 파싱하므로
이 필드는 반드시 유지해야 한다.

---

### 3. TERMINOLOGY OVERRIDE 조건부 포함

**대상**: `stage_c_writer.py` `build_permitted_method_list()`

#### 현재 상태

```
TERMINOLOGY OVERRIDE (ACTOR -> VIEW) 블록 (~300 토큰)
→ permitted_method_block 에 무조건 포함
→ Pass 1 프롬프트 + Pass 2 프롬프트 둘 다에 전달
```

animation, shader 계열처럼 View/Actor 와 무관한 feature에도 동일 블록이 전달된다.

#### 변경 방법

`build_permitted_method_list(specs)` 에서 specs 안에 `View` 또는 `Actor` 가
class/function 이름에 포함된 항목이 하나라도 있을 때만 포함.

```python
has_view_or_actor = any(
    ("View" in s["name"] or "Actor" in s["name"])
    for s in specs
    if s.get("kind") in ("class", "function", "enumvalue")
)

terminology_block = (
    "        CRITICAL CONSTRAINT - TERMINOLOGY OVERRIDE (ACTOR -> VIEW):\n"
    "        ..."
    if has_view_or_actor else ""
)
```

#### Rolling 모드 일관성

`permitted_method_block` 은 전체 specs 기준으로 1회 생성된 뒤
모든 Pass 1 청크와 Pass 2 배치에 동일하게 전달된다.
조건 판단도 전체 specs 기준 1회라 청크 간 불일치가 없다.

---

### 4. typedef alias_leaf 제거

**대상**: `stage_c_writer.py` `_build_typedef_aliases()`

#### 현재 상태

`using FontWeight = Dali::TextAbstraction::FontWeight::Type` 처리 시
다음 세 형태를 `full_names` 에 등록한다:

```
"Dali::Ui::Text::FontWeight::BOLD"   ← alias_full
"Text::FontWeight::BOLD"             ← alias_short
"FontWeight::BOLD"                   ← alias_leaf  ← 문제
```

#### 문제

`FontWeight::BOLD` 형태가 코드에 등장하려면 LLM이 암묵적으로
`using namespace Dali::Ui::Text;` 를 가정해야 한다.
우리 프롬프트는 `using namespace Dali;` / `using namespace Dali::Ui;` 까지만 가정하므로
이 형태가 나오면 오히려 잘못 쓴 코드다.

등록하면 두 가지 역효과가 생긴다:

1. LLM이 `Text::` 를 빼먹은 틀린 코드가 검증을 통과함
2. 다른 패키지에 같은 leaf 이름(`FontSlant` 등)이 있을 경우 오탐 가능성

#### 변경 방법

```python
# 변경 전
for prefix in (alias_full, alias_short, alias_leaf):
    sym = f"{prefix}::{child_name}"
    alias_set.add(sym)
    ...

# 변경 후 — alias_leaf 제거
for prefix in (alias_full, alias_short):
    sym = f"{prefix}::{child_name}"
    alias_set.add(sym)
    ...
```

alias 타입 자체 등록 부분도 동일하게 `(alias_full, alias_short)` 만 유지.

---

## 작업 순서

```
1 (Regex 상수화)       ← 독립
4 (alias_leaf 제거)    ← 독립
  ↓ 위 두 개는 같은 커밋 가능
2 (Spec 필드 정리)     ← get_api_specs() 구조 변경, 별도 커밋 권장
3 (TERMINOLOGY 조건부) ← 독립, 2와 같은 커밋 또는 별도
```

---

## 배제 항목

| 항목 | 이유 |
|------|------|
| #4 enum inline hint 중복 | 할루시네이션 억제 효과가 있어 유지 |
| #5 class_feature_map write | 재확인 결과 함수 내부에서 이미 read 1회 / write 1회. 오탐 |
| #7 block history 정리 | `_write_validation_report()` 가 읽으므로 완전한 dead code 아님. 낮은 우선순위로 별도 판단 |
