# [ENH-24] Feature 재구조화 및 Taxonomy Tree 품질 개선

## 개요

세 가지 독립적인 개선을 수행한다.

1. **taxonomy_reviewer Phase A: Feature 재구조화** — Oversized feature 분할, 소규모 feature 통합, 결과를 feature_map.json에 반영
2. **taxonomy_reviewer Phase B: 전체 일괄 Tree 설계** — 재구조화된 feature 목록을 기반으로 LLM 1회 호출로 2뎁스 트리 생성
3. **stage_a: classified 기반 class_feature_map 재계산** — feature_map_classified.json 완성 후 class_feature_map.json 재생성
4. **stage_b: Fix B 로직 제거** — taxonomy_reviewer가 feature_map을 직접 관리하므로 런타임 주입 불필요
5. **stage_c: get_api_specs() class_feature_map 기반 exact match** — substring 오매칭 제거

---

## 전체 파이프라인 변경

```
[변경 전]
feature_clusterer
  → taxonomy_reviewer (개별 LLM N회)
  → stage_a
  → stage_b (Fix B 런타임 주입)
  → stage_c (blueprint api 기반 substring 매칭)

[변경 후]
feature_clusterer
  → taxonomy_reviewer
      Phase A: feature 재구조화 → feature_map.json 업데이트
      Phase B: 전체 feature 일괄 LLM 1회 → feature_taxonomy.json
  → stage_a → feature_map_classified.json + class_feature_map.json 재생성
  → stage_b (Fix B 제거)
  → stage_c (class_feature_map 기반 exact match)
```

---

## 작업 1: taxonomy_reviewer.py 재설계

### Phase A: Feature 재구조화

#### A-1: Oversized Feature 분할

feature_clusterer가 마킹한 `oversized: true` feature 중 split_candidates가 3개 이상인 것을 LLM이 분할 여부를 판단한다. 기존 `review_oversized_feature()` 로직을 유지하되, 분할 결정 결과를 taxonomy가 아닌 **feature_map.json에 직접 반영**한다.

**분할 시 feature_map에 추가되는 sub-feature 형식:**
```json
{
  "feature": "sub-feature-id",
  "display_name": "Sub Feature Name",
  "packages": ["<부모 패키지 상속>"],
  "api_tiers": ["<부모 api_tiers 상속>"],
  "apis": ["<split_candidates[i].apis>"],
  "_taxonomy_split": true,
  "_split_parent": "original-feature-id"
}
```

부모 feature는 feature_map에서 제거하지 않는다. 부모는 overview 문서를 위해 유지되며, apis는 그대로 남긴다.

**Phase A split 결과는 taxonomy에 쓰지 않는다.** 트리 관계는 Phase B에서 단일 책임으로 처리한다.

**Locked 그룹 제약:**
- split된 부모 feature → Phase B에서 다른 feature의 child가 될 수 없음 (3뎁스 방지)
- split으로 생성된 sub-feature → Phase B에서 부모 변경 불가 (parent 충돌 방지)

Phase B에 전달되는 split 힌트:
```json
[{"parent": "original-feature", "children": ["sub-a", "sub-b"]}]
```

#### A-2: 소규모 Feature 통합

spec_count가 임계값(기본: `min_specs_for_standalone`, doc_config.yaml에서 설정) 미만인 feature를 소규모로 판단한다.

소규모 feature 목록과 전체 stable feature 목록을 LLM에 제시하여 merge 여부를 판단받는다.

**LLM 응답 형식:**
```json
[
  {"action": "merge", "source": "small-feat-a", "into": "larger-feat-x"},
  {"action": "keep", "feature": "small-feat-b"}
]
```

merge 결정된 feature는 feature_map에서 `suppress_doc: true`, `merge_into: <target>` 설정한다.

**코너케이스 처리:**
- merge target이 존재하지 않는 feature_id → keep 처리
- source와 target이 순환 참조 → keep 처리
- merge target이 suppress_doc인 feature → keep 처리

#### A-3: feature_map.json + class_feature_map.json 업데이트

Phase A 완료 후 feature_map.json을 저장한다.

class_feature_map.json은 이 시점에서 재계산하지 않는다. **class_feature_map의 최종 생성 책임은 stage_a에 있다** (A-3 항목 참조).

### Phase B: 전체 일괄 Tree 설계 (LLM 1회 호출)

#### 입력 준비

active features = feature_map에서 `suppress_doc`이 아닌 feature 전체.

각 feature에 대해 LLM에 제공하는 정보:
```json
{
  "feature_id": "image-view",
  "display_name": "ImageView",
  "brief": "feature_map의 description 또는 base_class brief",
  "api_count": 42
}
```

Phase A에서 결정된 split 힌트도 함께 제공:
```
아래 feature들은 split 결정이 완료된 locked 그룹입니다.
반드시 명시된 parent-child 관계를 유지하고, 해당 parent를 다른 feature의 child로 지정하지 마십시오:
[{"parent": "original-feature", "children": ["sub-a", "sub-b"]}]
```

#### Full 모드 (--full 또는 최초 실행)

전체 feature 목록을 한 번에 프롬프트에 담아 LLM 1회 호출.

**응답 형식:**
```json
[
  {"feature_id": "view", "tree_decision": "tree", "children": ["image-view", "label", "scroll-view"]},
  {"feature_id": "image-view", "tree_decision": "flat", "children": []}
]
```

**프롬프트 핵심 제약:**
```
CONSTRAINTS:
1. Tree depth must not exceed 2 levels (root → children only). Grandchildren are NOT allowed.
2. children 목록에는 반드시 제공된 feature_id 목록 내 항목만 사용하라.
3. locked 그룹의 parent를 다른 feature의 child로 지정하지 마라.
```

#### Incremental 모드 (--mode update)

변경 감지:
- 신규 feature: feature_map에 있으나 기존 taxonomy에 없는 것
- 재구조화된 feature: `_taxonomy_split` 플래그가 있거나 suppress_doc이 새로 설정된 것
- 삭제된 feature: 기존 taxonomy에 있으나 현재 feature_map에 없는 것

LLM에 제공:
```
기존 트리 구조: [기존 taxonomy JSON]

아래 변경사항을 반영하여 트리를 업데이트하라:
- 추가된 features: [...]
- 삭제된 features: [...]
가급적 기존 구조를 유지하고 변경된 부분만 조정하라.

변경이 필요한 feature 항목만 반환하라 (unchanged 항목 생략).
```

#### 후처리 검증

1. children의 feature_id가 active feature 목록에 없음 → 해당 child 제거
2. 3뎁스 탐지: A의 child인 B가 다시 children을 가짐 → B의 children을 A의 children으로 flatten
3. 한 feature가 여러 parent의 children에 동시 등재 → 첫 등장 parent만 유지
4. tree_decision이 "tree"인데 children 없음 → "flat"으로 다운그레이드
5. locked 그룹 위반: split parent가 누군가의 child로 지정됨 → 해당 child 지정 제거
6. locked 그룹 위반: split child의 parent가 변경됨 → locked parent로 복원

#### taxonomy 저장 형식

기존 형식 유지:
```json
{
  "view": {
    "display_name": "View",
    "parent": null,
    "children": ["image-view", "label"],
    "doc_file": "view.md",
    "tree_decision": "tree",
    "decision_reason": "..."
  },
  "image-view": {
    "display_name": "ImageView",
    "parent": "view",
    "children": [],
    "doc_file": "image-view.md",
    "tree_decision": "leaf",
    "decision_reason": "Child of view"
  }
}
```

### 영향 범위

| 파일 | 변경 내용 |
|---|---|
| `src/01_cluster/taxonomy_reviewer.py` | Phase A (split/merge → feature_map 반영), Phase B (일괄 LLM 1회 + incremental), Fix D 후처리 유지 |

---

## 작업 2: stage_a_classifier.py — classified 기반 class_feature_map 재계산

### 문제

`class_feature_map.json`은 현재 `feature_clusterer.py`가 `feature_map.json` 기반으로 생성한다. 그러나 `stage_a`가 ambiguous feature의 APIs를 stable feature로 귀속시킨 결과(`feature_map_classified.json`)와 class_feature_map이 불일치한다.

```
feature_map.json 기준: Dali::SomeClass → uncategorized_ambiguous_root  (틀림)
classified.json 기준:  Dali::SomeClass → view                          (맞음)
```

stage_c가 class_feature_map 기반 exact match로 전환하면 이 불일치가 직접적인 spec 누락으로 이어진다.

### 해결

stage_a_classifier.py 실행 완료 후, `feature_map_classified.json` 기반으로 `class_feature_map.json`을 재계산하여 덮어쓴다. feature_clusterer가 생성한 class_feature_map은 임시 초안이 되며, stage_a의 결과가 최종본이 된다.

**재계산 로직:**
```python
cfm = {}
for feat in final_classified_map:
    for cls in feat.get("apis", []):
        if cls and cls not in cfm:
            cfm[cls] = feat["feature"]

# suppress_doc feature의 클래스를 merge_into target으로 재매핑
# (feature_map에 suppress_doc 설정된 경우 classified에 포함되지 않으므로
#  feature_map에서 별도 로드하여 처리)
```

### 영향 범위

| 파일 | 변경 내용 |
|---|---|
| `src/02_llm/stage_a_classifier.py` | 실행 완료 후 classified 기반 class_feature_map 재계산 및 저장 추가 |

---

## 작업 3: stage_b_mapper.py — Fix B 로직 제거

### 문제

taxonomy_reviewer가 split sub-feature를 feature_map.json에 직접 추가하고, stage_a가 classified + class_feature_map을 완성하므로 stage_b의 런타임 주입 로직이 불필요해진다.

### 제거 대상

| 함수/블록 | 설명 |
|---|---|
| `find_child_api_names()` | Doxygen에서 child API 조회 — taxonomy_reviewer 불필요 (split_candidates 활용) |
| `build_child_entries()` | taxonomy child를 synthetic entry로 주입 — feature_map에 이미 포함 |
| `update_class_feature_map_for_children()` | child feature 클래스 재매핑 — stage_a가 처리 |
| `main()`의 Fix B 호출 블록 | 위 세 함수 호출부 |

### 영향 범위

| 파일 | 변경 내용 |
|---|---|
| `src/02_llm/stage_b_mapper.py` | Fix B 관련 함수 3개 및 호출 블록 제거 |

---

## 작업 4: stage_c_writer.py — get_api_specs() class_feature_map 기반 exact match

### 문제

현재 `get_api_specs()`는 blueprint의 `api_names_list`(클래스명 + 메서드명 혼합)를 substring 매칭으로 parsed_doxygen에서 검색한다.

```python
is_class_match = any(a in c_name for a in api_names_list) or \
                 any(c_name.split("::")[-1] in api_name_set for _ in [1])
```

메서드명이 컴파운드명에 substring으로 우연히 일치하면 오매칭 발생. 또한 class_feature_map이 완성된 이상 이를 primary 검색 키로 쓰는 것이 더 정확하다.

### 해결

`class_feature_map`과 `owning_feature`가 모두 제공된 경우, 해당 feature 소속 클래스 집합(`class_keys_set`)을 사전 계산하여 exact match로 전환한다. 둘 중 하나라도 없는 호출은 기존 fallback 방식을 유지한다.

**변경 전:**
```python
api_name_set = set(a.split("::")[-1] for a in api_names_list)
is_class_match = any(a in c_name for a in api_names_list) or \
                 any(c_name.split("::")[-1] in api_name_set for _ in [1])
```

**변경 후:**
```python
# 함수 진입 시 1회 계산
class_keys_set = set()
if class_feature_map and owning_feature:
    class_keys_set = {cls for cls, fid in class_feature_map.items()
                      if fid == owning_feature}

# 루프 내
if class_keys_set:
    is_class_match = c_name in class_keys_set
    # class_keys_set 모드: 소속이 다른 클래스는 자동 배제, foreign_classes 불필요
else:
    # fallback: 기존 substring 매칭
    api_name_set = set(a.split("::")[-1] for a in api_names_list)
    is_class_match = any(a in c_name for a in api_names_list) or \
                     any(c_name.split("::")[-1] in api_name_set for _ in [1])
    if is_class_match and class_feature_map and owning_feature:
        mapped = class_feature_map.get(c_name)
        if mapped and mapped != owning_feature and mapped != "uncategorized_ambiguous_root":
            foreign_classes.append(c_name)
            is_class_match = False
```

**호출 위치별 처리:**

| 호출 위치 | owning_feature 전달 | 동작 |
|---|---|---|
| 메인 생성 (line ~1656) | ✅ 전달 | class_keys_set 기반 exact match |
| patch 모드 (line ~1628) | ✅ 전달 추가 | class_keys_set 기반 exact match |
| child 메서드 수집 (line ~1521) | ❌ 없음 | fallback (보조 조회, owning_feature 개념 없음) |

### 영향 범위

| 파일 | 변경 내용 |
|---|---|
| `src/02_llm/stage_c_writer.py` | `get_api_specs()` 매칭 로직 변경, patch 모드 호출에 owning_feature 추가 |

---

## 전체 영향 범위 요약

| 파일 | 작업 |
|---|---|
| `src/01_cluster/taxonomy_reviewer.py` | 1 (전면 재설계) |
| `src/02_llm/stage_a_classifier.py` | 2 |
| `src/02_llm/stage_b_mapper.py` | 3 |
| `src/02_llm/stage_c_writer.py` | 4 |

## 작업 순서

작업 1 → 작업 2 → 작업 3 → 작업 4 순으로 진행한다.

- 작업 2는 작업 1의 feature_map 업데이트를 전제로 class_feature_map 최종본 생성
- 작업 3은 작업 1, 2 완료 후 Fix B가 불필요해진 것을 확인 후 제거
- 작업 4는 작업 2의 class_feature_map 완성 후 적용해야 exact match가 정확하게 동작
