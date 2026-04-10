# [ENH-17] 코드 생성 할루시네이션 감소 — Enum 인라인, 상속 Alias, Setter 우선 규칙

## 1. 현재 문제

Phase 3 (namespace strip) 완료 후에도 코드블럭/백틱 할루시네이션이 지속적으로 발생하고 있다.
검증 통과율이 낮은 이유를 분석하면 크게 세 가지 구조적 원인으로 나뉜다.

### 1-A. LLM이 Permitted List를 "필터"가 아닌 "사후 확인"으로 사용

LLM의 내부 동작 추정:
1. prior knowledge 기반으로 코드 생성 ("Position 설정이 필요 → `SetPosition()` 생성")
2. Permitted List에 없어도 그냥 사용

원하는 동작:
1. "Position 설정이 필요"
2. Permitted List에서 position 관련 메서드 검색
3. `SetPositionX`, `SetPositionY` 발견 → 사용

결과: `View::SetPosition()` 같이 **DB에 없는 메서드**를 창작하는 할루시네이션 발생.

### 1-B. Enum 값을 prior knowledge로 채움

- `FittingMode`, `ReleasePolicy` 등 타입 이름은 Permitted List에 있음
- 그 안의 실제 값(`SCALE_TO_FIT`, `CACHED` 등)은 PERMITTED ENUM VALUES 블록이
  메서드 목록과 분리되어 있어 LLM이 참조하지 않고 자체 생성
- 결과: `FittingMode::SCALE_TO_FIT` 같은 **존재하지 않는 enum 값** 사용

### 1-C. 상속 메서드가 DB에 미등록 → 올바른 코드도 FAIL

- `View::Add()`, `ImageView::Add()` 등은 `Dali::Actor`에서 상속받은 메서드
- parsed_doxygen에는 `base_classes` 필드가 있지만 DB 빌드 시 상속 체인을 타고 올라가지 않음
- full_names에 `Actor::Add` 만 있고 `View::Add`, `ImageView::Add`는 없음
- 결과: LLM이 올바르게 생성한 코드도 stage_c/_d에서 UNVERIFIED

### 1-D. `&` 레퍼런스 파라미터 타입 미캡처 → simple_names 폴백

- 변수 타입 추론 regex가 `Type varname =` 형태만 캡처
- `View& parentView` 같은 레퍼런스 파라미터는 미캡처
- `parentView`가 var_type_map에 없으므로 `parentView.SomeMethod()` → `SomeMethod`만 symbols에 추가
- simple_names는 전체 DB의 메서드 이름 집합 → **다른 클래스의 메서드도 통과**
- 결과: 타입 검증 없이 이름만으로 PASS 가능한 구멍 존재

### 1-E. SetProperty 남용 및 Actor→View 미치환

- TERMINOLOGY OVERRIDE 규칙에도 불구하고 LLM prior knowledge가 강한 경우
  (`parentActor`, `Dali::Actor` 등) 규칙을 따르지 않는 케이스 발생
- `SetProperty(Actor::Property::POSITION, ...)` 처럼 복잡한 표현을 생성해
  `Actor::Property::POSITION` 할루시네이션 위험 증가

---

## 2. 해결해야 할 세부 문제

| ID | 문제 | 현상 |
|----|------|------|
| P1 | Enum 인라인 미제공 | FittingMode, ReleasePolicy 값 창작 |
| P2 | 상속 메서드 DB 미등록 | View::Add, ImageView::Add UNVERIFIED |
| P3 | `&` 파라미터 타입 미캡처 | simple_names 폴백으로 구멍 발생 |
| P4 | SetProperty 남용 | Actor::Property:: 복합 표현 → 할루시네이션 위험 |
| P5 | Concept Index 부재 | 없는 메서드 창작 (SetPosition 등) |

---

## 3. 해결 방법

### S1. Enum 인라인 표시 (P1 해결) — 우선순위 HIGH

**구현**: `build_permitted_method_list()`에서 메서드 signature의 파라미터 타입을 파싱,
`enum_groups`에 해당 타입이 있으면 메서드 바로 아래에 indent로 출력.

변경 전:
```
PERMITTED METHODS:
  ImageView::SetImage(std::string url, FittingMode::Type fit, SamplingMode::Filter smp)

PERMITTED ENUM VALUES:
  FittingMode: SHRINK_TO_FIT, SCALE_TO_FIT, FIT_WIDTH, FIT_HEIGHT, DEFAULT
  SamplingMode: BOX, NEAREST, LINEAR, ...
```

변경 후:
```
PERMITTED METHODS:
  ImageView::SetImage(std::string url, FittingMode::Type fit, SamplingMode::Filter smp)
    ↳ FittingMode values: SHRINK_TO_FIT, SCALE_TO_FIT, FIT_WIDTH, FIT_HEIGHT, DEFAULT
    ↳ SamplingMode values: BOX, NEAREST, LINEAR, BOX_THEN_NEAREST, NO_FILTER, DONT_CARE
```

메서드를 읽는 순간 enum 값이 바로 옆에 보여 prior knowledge로 채울 틈을 줄임.

**토큰 최적화**: 같은 enum 타입이 여러 오버로드에 반복 등장할 경우 첫 등장에만 전체 값 표시,
이후에는 `[→ FittingMode: see above]` anchor만 표시해 중복 토큰을 최소화한다.
PERMITTED ENUM VALUES 블록은 기존대로 유지 (anchor의 참조 대상).

### S2. 상속 Alias 등록 + Permitted List 동기화 (P2 + P3 해결) — 우선순위 HIGH

#### 구조 원칙: Permitted List ⊆ full_names DB

생성(Permitted List)과 검증(full_names DB)이 동일한 API 셋을 기준으로 동작해야 한다.
현재는 `ImageView::Add`가 두 곳 모두에 없어 **LLM이 맞고 시스템이 틀린** 역전 상황.

```
목표 상태:
  Permitted List에 있음  →  full_names DB에 반드시 있음  (⊆ 관계 보장)
  full_names DB에 있음   →  Permitted List에는 없어도 됨 (전체 DB는 더 넓어도 OK)
```

#### 상속 메서드의 두 가지 추가 대상

**① full_names DB 확장** (검증용, 토큰 영향 없음):
- DB 빌드 시 `base_classes` 필드를 타고 상속 체인을 재귀 탐색
- 부모 클래스의 모든 메서드를 자식 클래스 이름으로 alias 등록
- cross-package 상속 처리: `dali-core`, `dali-adaptor`, `dali-ui` compounds를
  단일 맵으로 합친 뒤 재귀 탐색
- stage_c (main DB, inline DB), stage_d 세 곳 모두 동일 로직 적용

```python
# 상속 체인 수집 예시
# Dali::Ui::ImageView → Dali::Ui::View → CustomActor → Dali::Actor
# Actor::Add → View::Add, ImageView::Add 등 모두 full_names에 등록
```

**② Permitted List 추가** (생성용, 프롬프트에 출력):
- 전체 부모 메서드를 모두 넣으면 토큰 낭비 → **수동 화이트리스트** 방식 채택
- `ACTOR_INHERITED_METHODS` 상수로 선별된 공통 메서드만 각 feature의 Permitted List에 추가

```python
ACTOR_INHERITED_METHODS = {"Add", "Remove", "Unparent", "GetParent", "GetChildCount", "GetChildAt"}
```

- 적용 대상: `get_api_specs()`에서 View 파생 클래스가 포함된 feature
- 출력 형태: Permitted List 하단에 별도 섹션으로 표시

```
INHERITED METHODS (from Actor, available on all View-derived classes):
  Add(View child), Remove(View child), Unparent()
  GetParent() → View, GetChildCount() → uint32_t, GetChildAt(uint32_t) → View
```

#### `&` regex 수정 (P3 해결)

`Type& varname` 형태도 var_type_map에 캡처해 타입 없이 simple_names로 폴백하는 구멍을 줄임.

```python
# 변경 전
r'(Type)\s+(varname)\s*[=;{(]'

# 변경 후
r'(Type)\s*&?\s+(varname)\s*[=;{(,]'
```

→ `View& parentView` 캡처 → `parentView.Add()` → `View::Add` 생성 → DB alias PASS

#### simple_names 폴백 유지 방침

`auto`, 반환값 체인, 전역 함수 등 타입 추론이 구조적으로 불가능한 케이스가 남아 있어
simple_names 폴백을 완전히 제거하면 올바른 코드가 UNVERIFIED로 탈락하는 오탐이 증가한다.
현재는 `&` regex 수정으로 폴백 경로를 최소화하는 수준에서 유지한다.

### S3. Setter 우선 규칙 프롬프트 추가 (P4 해결) — 우선순위 MEDIUM

**구현**: `_build_batch_prompt()` 또는 `build_permitted_method_list()` 출력에 규칙 추가.

```
RULE: Always prefer dedicated setter/getter methods over SetProperty/GetProperty.
- Prefer: SetPositionX(x), SetPositionY(y)
- Avoid: SetProperty(Actor::Property::POSITION, ...)
Only use SetProperty when no dedicated setter exists in PERMITTED METHODS.
If a method you need does not appear in PERMITTED METHODS, search the list for
related terms before inventing one. Do not create methods not listed above.
```

두 번째 문장은 P5 (Concept Index 부재)를 프롬프트 수준에서 부분 보완.

### S4. Concept Index (P5 해결) — 우선순위 LOW

**구현**: `build_permitted_method_list()`에서 메서드 이름 토큰화 → 역인덱스 구성.

```
== IF YOU NEED TO... ==
Set position  → SetPositionX(float), SetPositionY(float)
Set size      → SetWidth(float), SetHeight(float)
Set image     → SetImage(std::string), SetResourceUrl(std::string)
```

자동 생성 방식은 메서드 이름에서 camelCase 토큰 추출 후 의미 단어로 그룹화.
품질이 보장되지 않는 부분이 있어 S1~S3 효과 확인 후 진행.

---

## 4. 작업 후 영향력

| 수정 | stage_c | stage_d | LLM 생성 품질 | 토큰 영향 |
|------|---------|---------|--------------|----------|
| S1 Enum 인라인 | Pass 2 프롬프트 변경 | 영향 없음 | Enum 값 창작 감소 | 소폭 증가 (anchor로 최소화) |
| S2 DB alias | DB full_names 확장 | DB full_names 확장 | 올바른 코드 PASS율 향상 | 없음 (프롬프트 미출력) |
| S2 Permitted List | Pass 2 프롬프트 변경 | 영향 없음 | Add/Remove 등 명시적 허가 | 소폭 증가 (화이트리스트 한정) |
| S2 `&` regex | `_verify_code_block` | `extract_symbols_from_markdown` | 타입 추론 정확도 향상 | 없음 |
| S3 Setter 규칙 | Pass 2 프롬프트 변경 | 영향 없음 | SetProperty 남용 감소 | 미미 |
| S4 Concept Index | Pass 2 프롬프트 변경 | 영향 없음 | 없는 메서드 창작 감소 | 증가 |

---

## 5. 고려되는 사이드이펙트

### S1 (Enum 인라인)
- 프롬프트 길이 증가: enum 값이 많은 메서드가 여러 개인 경우 토큰 증가
- 완화: 해당 feature에서 실제로 사용되는 메서드에만 인라인 표시 (이미 get_api_specs 기준으로 필터됨)

### S2 (상속 Alias + Permitted List 동기화)
- **DB alias**: 프롬프트에 출력되지 않으므로 토큰 영향 없음
  - 추가 alias 수: 파생 클래스(7+) × Actor 메서드(30~40개) ≈ 200~300개 → 문제없는 수준
- **cross-package 단축명 매핑**: `base_classes`에 `CustomActor`(단축명)로 저장되어
  `Dali::CustomActor`(full name)과 매핑이 안 될 수 있음 → 전체 compounds를 단일 맵으로
  합친 뒤 short name으로도 탐색하는 방어 로직 필요
- **Permitted List 화이트리스트**: `ACTOR_INHERITED_METHODS` 상수를 수동 관리해야 함.
  Actor 외 다른 상속 체인이 생기면 별도 상수 추가 필요. 현재 DALi 구조상 Actor가
  유일한 공통 부모라 당분간은 유지 가능
- **의도치 않은 PASS**: `ImageView::SomeActorOnlyMethod()` 처럼 실제로는 쓰면 안 되는
  메서드가 검증을 통과할 수 있으나, LLM 코드 품질 문제이지 검증 구조 문제는 아님

### S3 (Setter 규칙)
- 프롬프트 규칙 누적: 이미 TERMINOLOGY OVERRIDE, NAMESPACE RULE 등 다수 존재
  → 너무 많은 규칙은 LLM이 중요 규칙을 무시하는 원인이 될 수 있음
  → 한 줄로 핵심만 압축해서 추가

### S4 (Concept Index)
- 자동 생성 토큰화 품질: `SetAdditionalImageResourceUrl` 에서 의미 있는
  의도 단어 추출이 어려워 노이즈 항목 발생 가능
- 잘못된 매핑이 오히려 LLM을 혼란시킬 수 있음 → 품질 검증 후 적용

---

## 6. 우선순위

| 순위 | 항목 | 이유 |
|------|------|------|
| 1 | S1 Enum 인라인 | 구현 쉽고 효과 확실. 현재 가장 많이 발생하는 enum 값 창작을 직접 타격 |
| 2 | S2 상속 Alias + `&` regex | 올바른 코드가 FAIL 나는 구조적 버그 수정. Pass율 왜곡 제거 |
| 3 | S3 Setter 우선 규칙 | 프롬프트 한 줄 추가로 SetProperty 남용 및 Concept Index 부재 부분 보완 |
| 4 | S4 Concept Index | 효과는 크지만 자동화 품질 불확실. S1~S3 이후 실측 데이터 보고 결정 |

S1과 S3은 `_build_batch_prompt()` / `build_permitted_method_list()` 수정으로
같은 작업 사이클에 묶어서 처리 가능.
S2는 DB 빌드 로직 변경이므로 stage_c, stage_d 양쪽 모두 수정 필요.
