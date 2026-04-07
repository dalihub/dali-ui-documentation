# [BUG] enum-only feature의 hallucination 및 Stage D FAIL 반복 문제

## 현상

`view-accessibility-enums`, `scrollable-enum`, `view-focus-enums` 등 enum만 정의된 헤더 파일이
단독 feature가 되는 경우, Stage C에 전달되는 API 스펙이 사실상 비어 있어 LLM이
엉뚱한 namespace와 존재하지 않는 메서드를 hallucinate한다.
그 결과 Stage D 검증 FAIL → retry loop → 최종 FAIL → `validated_drafts/`에 파일 없음
→ `index.md`에 깨진 링크 생성.

## 근본 원인

Doxygen은 `enum class`를 별도 compound로 생성하지 않고 namespace compound의
`memberdef`로 처리한다. namespace compound는 `<location>`이 없어 `file_path=""`가 되고,
`feature_clusterer`의 `extract_feature_name()`이 `None`을 반환해 `uncategorized_ambiguous_root`로
탈락한다. 결과적으로 `feature_map.apis`에 파일명만 남고 실제 enum 클래스명은 없다.

## 영향 범위

- dali-ui `public-api`: `view-accessibility-enums`, `scrollable-enum`, `view-focus-enums`
- dali-ui `devel-api`: `direction-enums` 등
- dali-core / dali-adaptor 내 동일 패턴의 enum-only 헤더도 잠재적으로 해당

---

## 해결 방법: 2곳 수정

### ① `src/00_extract/doxygen_parser.py`

namespace compound 파싱 시 `kind="enum"` memberdef를 독립 compound 엔트리로 추출한다.
이 때 해당 enum의 `<location>` 파일 경로와 `<enumvalue>` 자식들도 함께 저장한다.

```
Dali::Ui namespace compound 파싱
  └─ memberdef kind="enum" name="AccessibilityState" location="view-accessibility-enums.h"
       └─ enumvalue: ENABLED, SELECTED, CHECKED, BUSY, EXPANDED, MAX_COUNT
  → synthetic compound 생성:
     {
       name: "Dali::Ui::AccessibilityState",
       kind: "enum",
       file: ".../public-api/view-accessibility-enums.h",
       api_tier: "public-api",
       brief: "Represents current state of a control.",
       members: [
         {name: "ENABLED",   kind: "enumvalue", brief: ""},
         {name: "SELECTED",  kind: "enumvalue", brief: ""},
         ...
       ]
     }
```

`@brief`가 개별 enumvalue에 있으면 brief에 반영되고, 없으면 빈 문자열로 처리.

### ② `src/01_cluster/feature_clusterer.py`

위에서 추출된 synthetic enum compound들을 `file` 경로 기반으로 올바른 feature에 라우팅한다.
기존 namespace compound 처리 시 `file_path=""`라 탈락하던 문제를 각 member 단위
파일 경로 추출로 해결한다.

```
synthetic compound {name: "Dali::Ui::AccessibilityState", file: ".../view-accessibility-enums.h"}
→ extract_feature_name() → "view-accessibility-enums"
→ feature_map["view-accessibility-enums"].apis 에 "Dali::Ui::AccessibilityState" 추가
```

결과적으로 `feature_map.json`:
```json
{
  "feature": "view-accessibility-enums",
  "apis": [
    "view-accessibility-enums.h",
    "Dali::Ui::AccessibilityState",
    "Dali::Ui::AccessibilityRole"
  ]
}
```

---

## 수정 후 파이프라인 효과

| 단계 | 수정 전 | 수정 후 |
|------|---------|---------|
| Stage C 입력 스펙 | 파일 compound 1개, members 없음 | enum 클래스 + enumvalue 전달 |
| LLM namespace | `Dali::Accessibility::*` hallucinate | `Dali::Ui::AccessibilityState` 정확히 사용 |
| LLM 메서드 | `SetRole`, `AddState` 등 없는 메서드 생성 | 스펙에 메서드 없으므로 anti-hallucination rule 작동 |
| Stage D 검증 | FAIL → retry 2회 → 최종 FAIL | PASS 또는 WARN 수준 |
| index.md 링크 | 깨진 링크 | 정상 링크 또는 미생성(플래그 기반) |
| 토큰 사용량 | Stage C 3회 호출(retry 포함) | 1회로 종료, 순감소 |

---

## 해결되지 않는 것 (허용 가능한 한계)

- 개별 enum value에 `@brief`가 없으면 LLM에 의미 설명 없이 이름만 전달됨
  → 추후 소스코드에 `@brief` 추가 시 자동으로 품질 향상
- Stage D가 `ENABLED`, `SELECTED` 등 단순 이름을 검증할 때 동명 심볼이 다른 곳에 있으면
  오탐 가능성 있으나, enum 클래스명 자체는 verified되므로 FAIL보다는 WARN 수준

---

## 구현 체크리스트

- [ ] `doxygen_parser.py` — `parse_compound()`: namespace kind일 때 `kind="enum"` memberdef를 synthetic compound로 추출
  - qualified name = `{namespace_name}::{enum_name}`
  - `file` = memberdef `<location file="">` 값
  - `api_tier` = file path에서 추출
  - `brief` = enum `<briefdescription>`
  - `members` = `<enumvalue>` 자식들 (name + brief)
  - `kind` = `"enum"` (synthetic 표시로 `"synthetic": true` 추가 고려)
- [ ] `doxygen_parser.py` — `process_package()`: `parse_compound()` 반환값이 list가 될 수 있도록 처리 (namespace → 여러 synthetic compound)
- [ ] `feature_clusterer.py` — synthetic enum compound의 `file` 경로로 `extract_feature_name()` 호출하여 올바른 feature에 라우팅
