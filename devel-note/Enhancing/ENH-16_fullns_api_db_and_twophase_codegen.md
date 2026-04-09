# [ENH-16] 완전 네임스페이스 기반 API DB 정확도 향상 및 2-Phase 샘플코드 생성 개선

## 개요

현재 파이프라인에서 발생하는 심볼 검증 오류(False Positive/Negative)와 LLM의 샘플코드 환각 문제를
두 가지 축으로 동시에 개선한다.

- **축 1**: Doxygen 파서와 심볼 DB의 정확도를 높여 검증 False Negative를 제거한다.
- **축 2**: Stage C의 생성 로직을 자연어/코드 2-Pass로 분리하고, 코드 생성 시 완전 네임스페이스 강제를 통해 LLM 환각률을 낮춘다.

---

## 1. 문제 상황

### 1-1. 심볼 DB의 누락 — False Negative (실제 존재하는 API를 검증 실패)

`stage_d_report_app.json`에서 다음과 같은 심볼이 `unverified_symbols`로 기록된다.

```json
"unverified_symbols": ["Dali::Actor::Property::SIZE"]
```

이 심볼은 `dali-core/dali/public-api/actors/actor.h`에 명확히 존재한다.
그러나 `build_doxygen_symbol_set()`이 구축하는 심볼 DB에는 등록되어 있지 않다.

### 1-2. LLM의 허구 API 생성 — False Positive (존재하지 않는 API를 생성)

```json
"unverified_symbols": ["SetLayoutParameters"]
```

이 심볼은 어떤 DALi 헤더에도 존재하지 않는다. LLM이 주변 맥락에서 그럴싸하게 추론해 생성한 환각이다.
현재 프롬프트의 `permitted_method_block`이 있음에도 발생한다.

### 1-3. 검증 로직의 과도한 관용 — 억울한 PASS

검증 단계 `verify_symbols()`가 3단계 폴백 검색을 수행하는데,
`step3`(simple_names 단독 매칭)이 너무 관대해서 `SetLayoutParameters`가 다른 클래스에 우연히 같은 이름이 있으면 PASS된다.
또한 `step2`(pair_names 쌍 검증)는 부분 네임스페이스(`Actor::Property`)로도 통과시킨다.

---

## 2. 해결해야 할 세부 문제

### 2-1. [파서] struct 내 익명 enum 값이 누락됨

`Dali::Actor::Property`는 **struct compound** 안에 **익명 enum**(이름 없는 enum)이 있다.

```cpp
struct Property {
    enum  // ← 이름이 없음
    {
        SIZE,
        POSITION,
        VISIBLE,
        ...
    };
};
```

Doxygen은 이 익명 enum을 struct의 memberdef로 기록하지만 name이 `""`(빈 문자열)이다.
현재 파서 `doxygen_parser.py`의 `parse_compound()`는 memberdef의 하위 `enumvalue`를 추출하지 않아
`SIZE`, `POSITION` 같은 값들이 members에 포함되지 않는다.

영향 범위: dali-core public-api 내 struct Property 패턴 전체.

```
Dali::Actor::Property          → SIZE, POSITION, VISIBLE ... 누락
Dali::Shader::Property         → PROGRAM 누락
Dali::PanGestureDetector::Property → SCREEN_POSITION ... 누락
Dali::CameraActor::Property    → TYPE, PROJECTION_MODE ... 누락
Dali::LinearConstrainer::Property → VALUE, PROGRESS 누락
```

### 2-2. [파서 → DB] 전체 네임스페이스를 붙인 심볼만 등록

현재 심볼 DB는 3가지 형태를 모두 저장한다.

| 집합 | 예시 |
|------|------|
| `full_names` | `Dali::Actor::SetBackgroundColor` |
| `simple_names` | `SetBackgroundColor` |
| `pair_names` | `Actor::SetBackgroundColor` |

완전 네임스페이스 강제 방향과 맞게, 검증 기준을 **`full_names` 단일화**로 단순화한다.

### 2-3. [검증기] dot-call 기반 타입 추론 추가

완전 네임스페이스 강제 후 코드는 다음 형태가 된다.

```cpp
Dali::Ui::ImageView imageView = Dali::Ui::ImageView::New();
imageView.SetResourceUrl("image.png");  // dot-call → 타입 추론 가능
```

선언부를 파싱해 `변수명 → 타입` 매핑을 구축하고,
dot-call 메서드를 `타입::메서드` 형태로 재구성하여 `full_names`에서 검증한다.

### 2-4. [Stage C] 자연어 설명 / 샘플코드 2-Pass 분리

현재 Stage C는 단일 프롬프트로 자연어 설명과 샘플코드를 동시에 생성한다.
이로 인해 코드 생성 제약(permitted 목록, 완전 네임스페이스 등)을 충분히 강화하기 어렵다.

**Pass 1**: 자연어 문서를 생성. 샘플코드가 필요한 위치에 태그를 삽입.

```
<!-- SAMPLE_CODE: AbsoluteLayoutParams를 이용해 SetBounds()로 자식뷰 배치 -->
```

**Pass 2**: 각 태그에 대해 별도 LLM 호출로 샘플코드만 생성.
이 시점에 완전 네임스페이스 강제, `#include` 생략, permitted 목록 엄격 검증을 적용.

### 2-5. [Stage C] 샘플코드 생성 제약 강화

Pass 2 코드 생성 프롬프트에 다음 규칙을 강제 적용한다.

- **`#include` 완전 금지**: 경로를 LLM이 알 수 없으므로 생략.
- **완전 네임스페이스 필수**: 모든 클래스/메서드/enum/property는 반드시 `Dali::` 접두사 포함.
  - `Dali::Ui::View` (O) / `View` (X)
  - `Dali::Actor::Property::SIZE` (O) / `Property::SIZE` (X)
  - `Dali::Ui::ImageView::SetResourceUrl(...)` — 타입 선언 시
  - `imageView.SetResourceUrl(...)` — 이미 선언된 변수의 dot-call은 허용
- **permitted 목록 외 메서드 사용 절대 금지**: 목록에 없는 메서드는 hallucination으로 간주.

### 2-6. [검증기] pair_names 제거 및 step2 삭제

`pair_names`는 부분 네임스페이스(`Actor::SetBackgroundColor`) 매칭을 위한 집합이었다.
완전 네임스페이스 강제 이후에는 이 단계가 불필요하다.

---

## 3. 해결 방법

### Phase 1 — API DB 정확도 향상 (즉시 적용 가능)

#### 수정 파일: `src/00_extract/doxygen_parser.py`

`parse_compound()` 내에서 struct/class compound 처리 시,
익명 enum memberdef를 만나면 하위 enumvalue들을 부모 compound 이름 기준으로
`{compound_name}::{ev_name}` 형태의 full-name members로 추출한다.

```python
# 익명 enum 처리 추가
if kind == "enum":
    name = (memberdef.findtext("name") or "").strip()
    if not name:  # 익명 enum
        for ev in memberdef.findall("enumvalue"):
            ev_name = extract_text_recursive(ev.find("name"))
            if ev_name:
                compound_data["members"].append({
                    "name": ev_name,
                    "kind": "enumvalue",
                    "api_tier": api_tier,
                    "brief": ...,
                })
```

이렇게 하면 `Dali::Actor::Property`의 members에 `SIZE`, `POSITION` 등이 포함되고,
`build_doxygen_symbol_set()`이 `Dali::Actor::Property::SIZE`를 `full_names`에 등록한다.

#### 수정 파일: `src/02_llm/stage_d_validator.py`

**`build_doxygen_symbol_set()`**: `pair_names` 집합 및 관련 코드 제거.

**`verify_symbols()`**: 3단계를 2단계로 단순화.
1. `full_names` 직접 매칭
2. `simple_names` (dot-call에서 추출한 메서드명 보조 검증)
   - ~~`pair_names` 쌍 검증~~ 제거

**`extract_symbols_from_markdown()`**: 심볼 추출 개선.
- `ClassName::MethodName` 패턴(pair) 추출 제거.
- 선언 파싱으로 `변수명 → Dali:: 타입` 매핑 구축.
- dot-call 검증 시 타입 매핑 기반으로 `Dali::타입::메서드` 재구성 후 `full_names` 검증.

### Phase 2 — 2-Pass 샘플코드 생성 (배치 호출 방식)

#### 수정 파일: `src/02_llm/stage_c_writer.py`

**Pass 1 함수** (`generate_natural_language_draft`):
- 기존 프롬프트와 유사하지만 코드 블록 대신 `<!-- SAMPLE_CODE: ... -->` 태그로 남김.
- 샘플 목적(어떤 API를 어떤 상황에서 보여줄 것)을 자연어로 태그에 기술.
- 대형 feature(토큰 초과)의 경우 기존 롤링 정제(`run_rolling_refinement`)를 Pass 1에 그대로 활용.
- Pass 1 프롬프트에 코드 생략 지시를 추가: "코드 예제가 필요한 위치에 태그만 삽입하고 코드 블록은 작성하지 마라."

**Pass 2 함수** (`generate_code_blocks_batch`):

*핵심 설계: 모든 태그를 **배치(1회 LLM 호출)**로 처리*

- 태그 파싱: `re.findall(r'<!-- SAMPLE_CODE: (.+?) -->', draft)` 로 전체 태그 수집.
- 태그 번호 매핑: `[BLOCK_0]`, `[BLOCK_1]`, ... 헤더로 레이블링.
- **단일 LLM 호출**: 모든 태그 목적을 한 프롬프트에 담아 전송.
  - 응답 형식: `[BLOCK_N]` 구분자로 각 코드 블록 구분.
- 응답 파싱: 구분자로 블록 분리 후 각 블록 개별 심볼 검증.
- 검증 통과 블록: 즉시 태그 위치에 삽입, 이후 재생성 없음.
- 검증 실패 블록: 실패 블록만 모아 **같은 배치 방식으로 재전송** (통과 블록은 재전송하지 않음).
  - 재전송 시 실패 원인(unverified_symbols) 포함하여 수정 지시.
- 최대 재시도 횟수: `MAX_CODE_RETRY = 5`
- 응답 파싱 자체가 실패한 블록: FAIL 처리 (graceful).

**Pass 2 토큰 절감 구조** (Pass 1과의 차이):

| 항목 | Pass 1 (자연어) | Pass 2 (코드 배치) |
|------|----------------|-------------------|
| Doxygen 풀 스펙 JSON | 전송 (주요 토큰 소비) | **미전송** |
| API 정보 | 풀 스펙 (brief, params, notes 등 포함) | 슬림 시그니처만 (`name::method(type) → return`) |
| 예상 토큰 비율 | 100% | ~10~15% |

`build_slim_signatures()` 헬퍼 함수로 specs에서 signature 줄만 추출:
```
- AbsoluteLayoutParams::SetBounds(float x, float y, float w, float h)
- AbsoluteLayoutParams::SetX(float x)
- AbsoluteLayout::New() -> AbsoluteLayout
```

오직 **permitted 메서드 목록 + 슬림 시그니처 + 규칙(namespace/no-include)** 만 전송.
롤링 정제 없음 — 태그 목록과 시그니처만이라 토큰 초과 없음.

**Graceful Degradation**:
- `MAX_CODE_RETRY` 소진 후에도 특정 블록이 실패이면:
  - 통과 블록: 태그 위치에 코드 정상 삽입.
  - 실패 블록: `<!-- SAMPLE_CODE: ... -->` 태그 자체를 삭제. 자연어 설명만 유지.
  - 문서는 `PARTIAL` (WARN 수준)으로 처리하여 `validated_drafts`에 복사 허용.
  - 근거: 환각 코드가 포함된 문서보다 코드 없는 문서가 낫다.

**블록별 결과 저장**:
- `cache/code_block_results/{tier}/{feat_name}.json`에 Pass 2 진행 내역 저장.
- Stage D가 이 파일을 참조해 history에 Pass 2 결과를 기록.

```json
{
  "feature": "animation",
  "verdict": "PARTIAL",
  "total_code_blocks": 5,
  "history": [
    {
      "block_index": 0,
      "block_purpose": "AnimateTo()로 Property::SIZE 애니메이션",
      "verdict": "PASS",
      "attempts": 1
    },
    {
      "block_index": 3,
      "block_purpose": "AnimationGroup으로 복수 속성 동시 애니메이션",
      "verdict": "FAIL",
      "attempts": 5,
      "unverified_symbols": ["SetLayoutParameters"],
      "action": "tag_removed"
    }
  ]
}
```

**통합** (`run_two_pass_generation`):
- Pass 1 결과에서 태그를 Pass 2 생성 코드로 치환.
- 최종 실패 태그는 삭제하여 최종 draft 완성.
- `main()` 루프 내 Full 생성 분기에서 기존 단일 호출을 `run_two_pass_generation()`으로 교체.

---

## 4. 예상되는 결과

| 항목 | 현재 | 개선 후 |
|------|------|---------|
| 억울한 FAIL (`Property::SIZE` 류) | 빈번히 발생 | 제거 |
| 환각 PASS (`SetLayoutParameters` 류) | 간헐적으로 통과 | 검증 강화로 차단 |
| 코드 생성 시 `#include` 오류 | 간헐적 발생 | 생략 강제로 제거 |
| 코드 생성 시 부분 네임스페이스 혼용 | 빈번히 발생 | 완전 네임스페이스 강제로 제거 |
| Stage D 최종 PASS율 | ~38% (3/8) | 70% 이상 목표 |
| stage_d_report의 오탐 비율 | 높음 | 크게 감소 |
| 실패한 코드블록 처리 | 전체 문서 FAIL 처리 | 코드블록만 생략, 문서는 PARTIAL로 저장 |

---

## 5. 파급 효과

### 긍정적 파급 효과

- **Stage D의 역할 단순화**: 현재 Stage D가 재생성까지 담당하는데, Phase 2 완료 후에는
  Stage D가 "최종 게이트 확인"만 하는 경량 단계로 단순화된다.
- **Stage C 재시도 비용 감소**: 코드 생성 블록 단위로 실패를 조기 감지하므로,
  전체 문서 재생성보다 훨씬 적은 토큰을 소모한다.
- **검증 신뢰도 향상**: `pair_names`/`simple_names` 폴백이 제거되어
  검증 결과의 의미가 명확해진다. PASS는 진짜 PASS, FAIL은 진짜 FAIL.
- **API DB 완성도 향상**: 익명 enum 누락 수정으로 `Shader::Property`, `CameraActor::Property` 등
  다수 클래스의 속성 심볼이 DB에 추가되어 다른 feature 문서에도 즉시 이득.

### 주의해야 할 사항

- **파서 수정 후 parsed_doxygen 캐시를 반드시 재생성해야 한다.**
  (`stage_a_extract` 재실행 필요)
- **Phase 2의 배치 방식은 Pass 2 LLM 호출을 1~2회(배치 전송 + 실패분 재전송)로 제한한다.**
  Pass 2는 Doxygen 풀 스펙 대신 슬림 시그니처만 전송하므로, Pass 1보다 토큰이 ~85% 적게 소모된다.
  전체 파이프라인 토큰 증가는 Pass 2 비용이지만, Stage D retry 감소로 상쇄된다.
- **`auto` 타입 추론 한계**: 변수가 `auto`로 선언된 경우 dot-call 타입 매핑을 구축할 수 없다.
  Phase 1-C에서 `auto` 사용 금지를 LLM에게 이미 강제했으므로, 이 문제는 대부분 차단된다.

---

## 구현 우선순위

```
Phase 1-A (우선): doxygen_parser.py — 익명 enum 추출 수정
Phase 1-B (우선): stage_d_validator.py — pair_names 제거, 타입 추론 검증 추가
Phase 1-C (우선): stage_c_writer.py — 완전 네임스페이스 강제, #include 금지
Phase 2   (다음): stage_c_writer.py — 2-Pass 자연어/코드 분리
```

---

## 구현 현황 (2026-04-09)

### Phase 1 — 완료 ✅

커밋: `Fix: Phase 1 — anonymous enum extraction, simplified validator, namespace constraints`

#### Phase 1-A 결과 (doxygen_parser.py)

익명 enum 추출 수정 후 `stage_a_extract`를 재실행하여 `cache/parsed_doxygen/dali-core.json` 검증 완료.

**검증 방법**: `grep -A 200 '"name": "Dali::Actor::Property"' dali-core.json`

**결과**:

```json
{
  "name": "Dali::Actor::Property",
  "kind": "struct",
  "members": [
    { "name": "PARENT_ORIGIN", "kind": "enumvalue", "api_tier": "public-api", "brief": "..." },
    { "name": "PARENT_ORIGIN_X", "kind": "enumvalue", "api_tier": "public-api", "brief": "..." },
    ...
    { "name": "SIZE", "kind": "enumvalue", "api_tier": "public-api", "brief": "..." },
    ...
  ]
}
```

- 수정 전: `Dali::Actor::Property` members에 익명 enum 값 **0개** (전부 누락)
- 수정 후: `PARENT_ORIGIN`, `PARENT_ORIGIN_X`, `SIZE`, `POSITION`, `VISIBLE` 등 **전체 등록**
- `dali-core.json` 내 `enumvalue` 항목 총 **598개** 신규 등록 확인
- 동일 패턴 일괄 수정: `Dali::Shader::Property::PROGRAM`, `Dali::CameraActor::Property::PROJECTION_MODE` 등 포함

이로써 `build_doxygen_symbol_set()`이 `Dali::Actor::Property::SIZE` 등을 `full_names`에 등록하게 되어, Stage D 검증에서의 **억울한 FAIL이 제거**된다.

#### Phase 1-B 결과 (stage_d_validator.py)

- `pair_names` 집합 및 관련 코드 완전 제거 (DB 구축, 검증 함수, 3개 호출 지점 모두)
- `extract_symbols_from_markdown()`: 선언부 타입 추론으로 dot-call 재구성 → `full_names` 직접 검증
- `verify_symbols()`: `::` 유무 2단계 분기로 단순화

#### Phase 1-C 결과 (stage_c_writer.py)

`build_permitted_method_list()`에 2개 CRITICAL CONSTRAINT 블록 추가:

1. **FULLY QUALIFIED NAMESPACES**: `Dali::` 접두사 필수, `auto` 금지, dot-call은 완전 선언 후에만 허용
2. **NO #include DIRECTIVES**: 코드 예제에 `#include` 완전 금지

#### 문법 검사

```
python3 -m py_compile src/00_extract/doxygen_parser.py   → OK
python3 -m py_compile src/02_llm/stage_d_validator.py    → OK
python3 -m py_compile src/02_llm/stage_c_writer.py       → OK
```

### Phase 2 — 진행 중 🔄

#### 확정된 설계 사항

- **배치 LLM 호출**: 태그를 개별 호출하지 않고 한 번에 모아서 배치 전송. 실패분만 같은 방식으로 재전송.
- **슬림 시그니처**: Pass 2는 Doxygen 풀 스펙 대신 `method(type) → return` 형태의 간소화 시그니처만 전송. 토큰 ~85% 절감.
- **MAX_CODE_RETRY = 5**: 배치 재전송 최대 5회. 소진 후 최종 실패 블록은 태그 삭제(Graceful Degradation).
- **롤링 정제 연동**: 대형 feature는 Pass 1에서 기존 `run_rolling_refinement()` 그대로 사용. Pass 2는 동일한 배치 방식 적용.
- **오케스트레이터**: `run_two_pass_generation()` 함수로 Pass 1→2 전체 흐름 통제.
- **블록 결과 저장**: `cache/code_block_results/{tier}/{feat_name}.json`으로 Pass 2 진행 내역 기록.
