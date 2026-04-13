# [ENH-21] 심볼 DB 커버리지 및 할루시네이션 수정

## 개요

테스트 실행 로그 분석에서 발견된 세 가지 문제.
각각 검증 실패 / stage_b spec 부족 / LLM 할루시네이션이 원인이며 독립적으로 수정 가능하다.

---

## 항목 1: named nested enum 중간 레이어 미처리로 인한 검증 실패

### 문제

```
BLOCK_10 [INLINE_CODE]: FAIL (unverified: ['AlphaFunction::EASE_IN_OUT'])
BLOCK_10 [INLINE_CODE]: FAIL (unverified: ['AlphaFunction::BOUNCE'])
→ 5회 소진 후 tag 삭제
```

`AlphaFunction::EASE_IN_OUT` 은 C++에서 유효한 표기다.
`BuiltinFunction`이 `AlphaFunction`의 **일반 enum** (`enum BuiltinFunction : uint8_t`)이므로
값이 outer class scope으로 노출되어 `AlphaFunction::EASE_IN_OUT`이 문법상 맞다.
LLM이 틀린 코드를 생성한 것이 아니다.

### 해결해야 할 세부 문제

**검증 원칙**: validation은 반드시 exact full match다. 부분 일치는 허용하지 않는다.
- `Actor::Property::OPACITY` → `Actor::OPACITY`, `Property::OPACITY` 는 **오탐** → 허용 불가
- `AlphaFunction::BuiltinFunction::EASE_IN_OUT` → `AlphaFunction::EASE_IN_OUT` 은 **실제로 유효** → 허용해야 함

이 구분은 중간 레이어가 **일반 enum**(값이 outer scope 노출)인지 **struct/class/enum class**(값이 내부에만 있음)인지에 달려있다.

현재 `_symbol_aliases()`는 문자열만 받기 때문에 중간 레이어의 kind를 알 수 없다.
잘못된 위치에서 추론하면 `Actor::OPACITY` 같은 오탐을 만들 위험이 있다.

```cpp
// 일반 enum — outer scope 노출 O
class AlphaFunction {
  enum BuiltinFunction : uint8_t { EASE_IN_OUT, BOUNCE, ... };  // AlphaFunction::EASE_IN_OUT 유효
};

// struct — outer scope 노출 X
namespace Actor {
  struct Property { enum { OPACITY, SIZE, ... }; };  // Actor::OPACITY 는 무효
}
```

### 해결 방법

**대상**: `stage_c_writer.py` DB 빌드 루프 (1116~1132번째 줄 인라인 빌드 블록)

`_symbol_aliases()` 가 아니라 **Doxygen parsed 데이터를 읽는 DB 빌드 시점**에서 수정.
이 시점에는 compound member의 `kind` 필드로 일반 enum / struct / enum class 구분이 가능하다.

compound를 순회할 때, member의 `kind == "enum"` 인 경우 (일반 enum, struct/enum class 제외)
해당 enum의 하위 `enumvalue`들에 대해 **중간 enum 이름을 생략한 단축 심볼**을 추가 등록한다.

```python
for comp in data.get("compounds", []):
    cn = comp.get("name", "")
    ...
    for mb in comp.get("members", []):
        mn = mb.get("name", "")
        mb_kind = mb.get("kind", "")
        if mn:
            full_sym = f"{cn}::{mn}"
            _full_names.add(full_sym)
            _full_names.update(_symbol_aliases(full_sym))
            _simple_names.add(mn)

        # 일반 enum member인 경우: enumvalue를 Class::VALUE 단축형으로 추가 등록
        # kind == "enum" 은 일반 enum (값이 outer scope 노출)
        # kind == "enumvalue" 멤버는 이미 위에서 full_sym으로 등록됨
        # 여기서는 Doxygen이 enum 자체를 member로 기록한 경우를 처리
        # (namespace compound의 경우 extract_enum_synthetics로 별도 처리되므로
        #  class compound 내부의 named enum member가 대상)
        if mb_kind == "enum" and mn:
            # 이 enum의 enumvalue를 Class::VALUE 형태로 추가
            for ev in mb.get("enumvalues", []):   # doxygen_parser가 저장한 경우
                ev_name = ev.get("name", "")
                if ev_name:
                    shortcut = f"{cn}::{ev_name}"
                    _full_names.add(shortcut)
                    _full_names.update(_symbol_aliases(shortcut))
```

단, doxygen_parser.py가 현재 enum member의 하위 enumvalue를 `mb` 딕셔너리에 저장하지 않고
있다면 parser도 함께 수정해서 `enumvalues` 리스트를 저장하도록 해야 한다.
(현재 class compound의 anonymous enum 처리는 있으나, named enum member의 enumvalue 보존은 확인 필요)

### 전체 결과에의 영향

- `AlphaFunction::EASE_IN_OUT`, `AlphaFunction::BOUNCE` 등 full_names에 추가 등록
- animation 피처 tag 삭제 없이 정상 삽입
- struct/enum class 중간 레이어는 대상이 아니므로 `Actor::OPACITY` 같은 오탐 없음
- validation 원칙(exact match) 유지 — 새 심볼이 등록되는 것이지 매칭 방식이 바뀌는 게 아님
- DALi 전체에서 동일 패턴(named regular enum in class)에 일괄 적용

---

## 항목 2: stage_b feature_map 메서드 미등록

### 문제

```
[4] animated-image-view  Sampled APIs: 1
[5] image-view           Sampled APIs: 1
[6] input-field          Sampled APIs: 2
[7] label                Sampled APIs: 2
[8] view                 Sampled APIs: 3
```

단일 클래스로 이루어진 피처들(`ImageView`, `Label`, `InputField`)은
feature_map에 클래스명 1개만 등록되어 있고 메서드가 전혀 없다.

### 해결해야 할 세부 문제

`sample_apis()`는 feature_map의 `apis` 리스트를 기반으로 동작한다.
`image-view: ["Dali::Ui::ImageView", "image-view.cpp", "image-view.h"]`에서
`.cpp`/`.h` 제거 후 실질 항목이 클래스명 1개뿐이면 `method_entries`가 비어
`sample_apis()`가 샘플링 로직 없이 그대로 반환한다.

stage_b가 outline을 생성할 때 메서드 목록이 없으므로
`SetText()`, `SetResourceUrl()` 같은 실제 API 기반 섹션 제목 대신
LLM의 일반 지식으로 섹션을 추론한다.

stage_c는 parsed_doxygen에서 클래스 전체 멤버를 직접 로드하므로 영향 없다.

### 해결 방법

**대상**: `stage_b_mapper.py` `find_child_api_names()`

현재 클래스명만 반환하는 부분에서 parsed_doxygen을 읽어
public 메서드명도 `ClassName::MethodName` 형태로 함께 등록.

```python
# 현재: 클래스명만 수집
api_names.append(compound_name)

# 변경 후: 클래스명 + public 메서드명 수집
api_names.append(compound_name)
for mb in compound.get("members", []):
    if mb.get("kind") == "function" and mb.get("name"):
        api_names.append(f"{compound_name}::{mb['name']}")
```

`sample_apis()`의 50개 캡 로직이 그대로 동작하므로
메서드가 많아도 균등 샘플링으로 자연스럽게 제한된다.

### 전체 결과에의 영향

- `image-view`, `label`, `input-field`, `view` 등의 stage_b outline 품질 향상
- TOC 섹션 제목이 실제 API 기반으로 구체화됨
- stage_c에는 영향 없음 (parsed_doxygen 직접 로드 경로 독립)
- `find_child_api_names()`가 불리는 경로에서만 적용되므로
  manual_features로 등록된 view, actors 등에는 적용 안 됨 (별도 고려 불필요)

---

## 항목 3: view 피처 — Trait/UiState spec 누락으로 인한 할루시네이션

### 문제

```
FAIL (unverified: ['Trait::HIGHLIGHT'])
FAIL (unverified: ['Trait::PRESSED'])
FAIL (unverified: ['Trait::NONE'])
FAIL (unverified: ['Trait::PRESS_EFFECT'])
FAIL (unverified: ['UiState::IsSelected'])
→ 5번째 시도에서 PASS (retry 낭비 4회)
```

### 해결해야 할 세부 문제

`Trait` 클래스(`trait.h`)는 BaseHandle 래퍼로 enum이 전혀 없다.
실제 구조:

```
상태 상수:  UiState::PRESSED, UiState::SELECTED, UiState::FOCUSED  (비트마스크 값 타입)
상태 조회:  InteractiveTrait::IsPressed(), SelectableTrait::IsSelected()
```

현재 view 피처 스펙에는 `Dali::Ui::View`와 `Dali::Ui::Visual`만 포함된다.
`InteractiveTrait`, `SelectableTrait`, `UiState`는 각자 독립 피처(`interactive-trait` 등)로
class_feature_map에 등록되어 있어서 `get_api_specs()`가 `foreign_classes`로 걸러낸다.

LLM은 스펙에서 `Trait` 클래스를 보고 "상태를 가지는 객체"로 추론해
존재하지 않는 `Trait::PRESSED`, `UiState::IsSelected()` 를 창작한다.

단순히 permitted_method_block에 주의사항을 추가하는 것은 임시방편이며,
근본적으로 LLM이 올바른 API(`InteractiveTrait::IsPressed()`)를 쓰려면
해당 클래스의 스펙이 view 문서 생성 시 완전히 포함되어야 한다.

### 해결 방법

**`merge_mode: full`** 신규 플래그 도입. 기존 `merge_into`의 동작을 건드리지 않는다.

#### 왜 기존 `merge_into`를 그대로 쓰면 안 되나

현재 `merge_into` 처리는 "base class, briefly mention" 용도다.
- `actors` → `view`: Actor 메서드를 View 문서에서 간단히 언급
- 프롬프트 지시: "Do NOT write dedicated sections — weave naturally"

이 정책을 바꾸면 `actors` → `view` 결과물 품질이 달라진다.

#### 변경 내용

**① `repo_config.yaml`**

```yaml
- feature: "interactive-trait"
  suppress_doc: true
  merge_into: "view"
  merge_mode: "full"

- feature: "selectable-trait"
  suppress_doc: true
  merge_into: "view"
  merge_mode: "full"

- feature: "ui-state"
  suppress_doc: true
  merge_into: "view"
  merge_mode: "full"
```

**② `feature_clusterer.py`** — merge_mode: full 대상의 apis를 target apis에 병합

```python
# merge_into + merge_mode:full 처리
# suppress_doc 소스의 apis를 target feature의 apis에 자동 병합
for feat_name, cluster in feature_map.items():
    if cluster.get("merge_into") and cluster.get("merge_mode") == "full" \
            and cluster.get("suppress_doc"):
        target = cluster["merge_into"]
        if target in feature_map:
            existing = set(feature_map[target]["apis"])
            for a in cluster.get("apis", []):
                if a not in existing:
                    feature_map[target]["apis"].append(a)
```

이 처리 후 class_feature_map 생성 시 기존 로직(suppress 아닌 feature 우선)이
`Dali::Ui::InteractiveTrait → view`로 자동 교체해준다. 추가 코드 불필요.

**③ `stage_c_writer.py`** — merge_mode 분기

```python
# merge_sources 역매핑 생성 시 merge_mode 저장
if target and f.get("suppress_doc"):
    merge_sources.setdefault(target, []).append({
        **f,
        "merge_mode": f.get("merge_mode", "inherit")  # "inherit" | "full"
    })

# merge_into 처리 루프에서 분기
for src in sources:
    src_specs_raw, _ = get_api_specs(src.get("packages", []), src.get("apis", []), ...)

    if src.get("merge_mode") == "full":
        # specs에 직접 병합 — permitted list, slim_sigs에 완전 포함
        specs.extend(src_specs_raw)
        print(f"    [+] Full-merged from '{src['feature']}': {len(src_specs_raw)} spec(s)")
    else:
        # 기존 동작: inherited_context (briefly mention)
        gap_specs = [...]
        inherited_specs.extend(gap_specs)
```

### 전체 결과에의 영향

- `InteractiveTrait::IsPressed()`, `SelectableTrait::IsSelected()`, `UiState::PRESSED` 등이
  view 피처의 permitted method list와 slim_sigs에 완전 포함됨
- LLM이 올바른 API를 참조하므로 `Trait::PRESSED` 류 할루시네이션 제거
- retry 낭비 4회 제거
- `interactive-trait`, `selectable-trait`, `ui-state` 독립 문서 미생성 (suppress_doc)
- 기존 `merge_into` 동작(`actors`, `image-view-types`)에 영향 없음
  — `merge_mode` 미지정 시 기존 "inherit" 경로 그대로 동작

---

## 우선순위

```
항목 1 (nested enum alias)    ← tag 삭제 직접 원인. 코드 1곳 수정. 높음
항목 3 (Trait merge_mode)     ← 할루시네이션 근본 제거. 파급 범위 넓으나 안전. 중간
항목 2 (stage_b 메서드 등록)  ← stage_c 무관, 품질 개선 수준. 낮음
```
