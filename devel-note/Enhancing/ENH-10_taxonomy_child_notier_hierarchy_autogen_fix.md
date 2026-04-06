# ENH-10: Taxonomy Child .notier · 계층 혼란 · Autogen 억제 수정 계획

**상태**: 🔴 미구현  
**관련 파일**:
- `dali-doc-gen/src/01_cluster/taxonomy_reviewer.py`
- `dali-doc-gen/src/02_llm/stage_b_mapper.py`

---

## 배경

Phase 3 완료 이후 실제 파이프라인 출력을 점검한 결과, 다음 세 가지 구조적 버그가 확인되었다.

1. **taxonomy_reviewer 부모-자식 계층 정합성 오류** — 자식 재부모화(re-parenting) 시 이전 부모의 `children` 배열에서 제거되지 않음 (Fix A)
2. **taxonomy child 생성 시 class_feature_map 미갱신** — Stage B가 child 전용 blueprint를 만들어도, class→feature 매핑이 부모 feature를 여전히 가리켜 Stage C가 스펙을 전량 필터링 → `.notier` (Fix B)
3. **autogen feature의 taxonomy 유입** — `.autogen.h` 파일에서 파생된 feature 항목이 taxonomy에 포함되어 불필요한 LLM 처리와 혼선 유발 (Fix C)

---

## 파이프라인 선행 구조 이해

문제를 이해하기 위해 파이프라인의 데이터 흐름을 먼저 정리한다.

```
[오프라인 정적분석]
feature_clusterer.py
  → feature_map.json          (feature 목록, 디렉터리 기반 클러스터링)
  → class_feature_map.json    (class → feature 독점 매핑, 동시 생성)
          ↓
[LLM: Stage A]
stage_a_classifier.py
  읽음: feature_map.json
  → feature_map_classified.json  (feature별 audience 필드 추가)
          ↓
[LLM: Think model]
taxonomy_reviewer.py
  읽음: feature_map.json  ← (classified 아님, 원본)
  → feature_taxonomy.json  (Tree/Flat 구조 결정, child 파생 생성)
          ↓
[LLM: Stage B]
stage_b_mapper.py
  읽음: feature_map_classified.json + feature_taxonomy.json
  → stage_b_blueprints.json
```

**핵심 전제**: `class_feature_map.json`은 `feature_clusterer.py` 실행 시 단 1회 생성된다.  
taxonomy_reviewer가 나중에 파생한 child feature들은 이 파일에 반영되지 않는다.

---

## 문제 1 (Fix A): 부모-자식 계층 정합성 오류

### 증상

`feature_taxonomy.json` 실제 상태:

```json
"view": { "children": ["animated-image-view", "image-view", "label", ...] },
"image-view": { "children": ["static-image-view", "animated-image-view", "lottie-animation-view"] },
"animated-image-view": { "parent": "view" }
```

`animated-image-view`가 `image-view.children`에도 들어있고 `view.children`에도 들어있다.  
`parent` 필드는 `"view"`인데, `image-view`가 자신의 자식이라고 주장하는 불일치 상태.

### 원인

`taxonomy_reviewer.py`의 자식 재부모화(re-parenting) 로직:

```python
# 415-433 (개략)
if new_parent != child_entry.get("parent"):
    child_entry["parent"] = new_parent          # ← child의 parent 갱신
    parent_entry["children"].append(child_name) # ← 새 부모의 children에 추가
    # ⚠️ 이전 부모의 children에서 제거하는 코드 없음
```

LLM이 `animated-image-view`를 `image-view`의 자식으로 재배치하면:
- `image-view.children`에 추가됨 ✅
- `animated-image-view.parent = "image-view"`로 갱신됨 ✅  
- **`view.children`에서 `animated-image-view` 제거 안됨** ❌

### 해결 방법 (Fix A)

`taxonomy_reviewer.py` 재부모화 처리 부분에 이전 부모 정리 로직 추가:

```python
old_parent_name = child_entry.get("parent")

# 새 부모와 다를 때만 처리
if old_parent_name and old_parent_name != new_parent:
    old_parent_entry = taxonomy.get(old_parent_name)
    if old_parent_entry and child_name in old_parent_entry.get("children", []):
        old_parent_entry["children"].remove(child_name)  # ← 이전 부모에서 제거

child_entry["parent"] = new_parent
parent_entry["children"].append(child_name)
```

`sanitize_children()`이 이미 구현되어 있으므로(ENH-06 FIX-0), 자기참조 및 중복은 이미 걸러진다.  
Fix A는 **재부모화 시점**의 이전 부모 정리를 다루는 것으로 보완적 위치에 있다.

---

## 문제 2 (Fix B): taxonomy child의 class_feature_map 미갱신 → .notier

### 증상

`animated-image-view`, `lottie-animation-view` 등 taxonomy child feature들이 실제 문서 대신 `.notier` 마커 파일만 생성된다.

### 원인 분석 (4단계)

**Step 1**: `feature_clusterer.py`가 `feature_map.json`과 함께 `class_feature_map.json`을 생성한다.

```json
// class_feature_map.json (생성 시점 스냅샷)
"Dali::AnimatedImageView": "image-view",   ← 부모 feature로 매핑됨
"Dali::LottieAnimationView": "image-view", ← 부모 feature로 매핑됨
"Dali::ImageView": "image-view"
```

`animated-image-view`, `lottie-animation-view`는 아직 taxonomy child로 생성되지 않았으므로 존재하지 않는다.

**Step 2**: `taxonomy_reviewer.py`가 `feature_taxonomy.json`에 child를 추가한다.

```json
"image-view": { "children": ["static-image-view", "animated-image-view", "lottie-animation-view"] }
```

child가 생성되었지만 `class_feature_map.json`은 갱신되지 않는다.

**Step 3**: `stage_b_mapper.py`의 `build_child_entries()`가 child feature용 blueprint를 생성한다.

```python
# stage_b_mapper.py lines 102-131
def build_child_entries(child_name, taxonomy, ...):
    # animated-image-view 전용 blueprint 생성
    # api_names에 AnimatedImageView 관련 클래스 포함
```

blueprint에는 `animated-image-view`가 사용할 API 목록이 들어있다.

**Step 4**: `stage_c_writer.py`가 spec을 로드할 때 `class_feature_map.json`으로 필터링한다.

```python
# class_feature_map.json 기준으로 foreign class 제거
# AnimatedImageView → "image-view"  (class_feature_map이 여전히 이렇게 읽음)
# 현재 feature는 "animated-image-view" → "image-view" 소속이 아님 → 필터링됨
```

결과: blueprint에 API 목록이 있어도 스펙이 0개 → `.notier` 생성.

### 해결 방법 (Fix B)

`stage_b_mapper.py`의 `build_child_entries()` 실행 후, 새로 생성된 child feature에 속하는 클래스들을 `class_feature_map.json`에 갱신한다.

```python
# stage_b_mapper.py — build_child_entries() 호출 이후
def update_class_feature_map_for_children(child_name, api_names, class_feature_map_path):
    """
    taxonomy child feature가 사용하는 클래스를 class_feature_map에 재등록한다.
    이전에 부모 feature로 매핑되어 있던 항목을 child feature로 덮어쓴다.
    """
    with open(class_feature_map_path) as f:
        cfm = json.load(f)

    updated = False
    for api_name in api_names:
        if cfm.get(api_name) != child_name:
            cfm[api_name] = child_name
            updated = True

    if updated:
        with open(class_feature_map_path, "w") as f:
            json.dump(cfm, f, indent=2)
```

호출 위치:

```python
# build_child_entries() 이후
child_api_names = find_child_api_names(child_name, taxonomy, packages)
child_entry = build_child_entries(child_name, taxonomy, child_api_names, ...)

update_class_feature_map_for_children(
    child_name, child_api_names, CLASS_FEATURE_MAP_PATH
)
```

**주의사항**:
- `class_feature_map.json` 갱신은 반드시 blueprint 작성 이전에 완료되어야 한다.
- 한 클래스가 여러 child에 속하는 경우(드물지만 발생 가능), 마지막에 처리된 child가 승리한다. 이는 `class_feature_map.json`이 exclusive 매핑을 원칙으로 하기 때문에 정상 동작이다.
- `find_child_api_names()`는 Doxygen에서 display_name 기반 검색을 수행하므로 결과가 없을 수 있다. 빈 목록인 경우 갱신 스킵.

---

## 문제 3 (Fix C): Autogen feature의 taxonomy 유입

### 증상

`feature_taxonomy.json`에 다음과 같은 항목이 존재한다:

```json
"dummy-component.autogen": { ... },
"view.autogen": { ... },
"label.autogen": { ... }
```

이들은 `.autogen.h` 파일에서 파생된 method chaining 보일러플레이트 항목으로,  
실제 API 문서화 대상이 아니다.

### 원인

`feature_clusterer.py`가 디렉터리 기반 클러스터링 시 `.autogen.h` 파일을 일반 헤더처럼 처리한다.  
결과적으로 `feature_map.json`에 `*.autogen` 항목이 포함되고, taxonomy_reviewer가 이를 그대로 받아 taxonomy에 올린다.

### 해결 방법 (Fix C)

코드 레벨 하드코딩 필터 대신 **taxonomy_reviewer 프롬프트에 억제 지시**를 추가한다.

`taxonomy_reviewer.py`의 system prompt 또는 feature 분류 지시문에 다음 내용 삽입:

```
STRICT EXCLUSION RULES:
- Any feature whose name ends with ".autogen" MUST be excluded from the taxonomy entirely.
  These are method-chaining boilerplate files, not documentable features.
- Do NOT create children, parents, or any taxonomy entry for ".autogen" features.
- If you encounter a feature name matching "*.autogen" pattern, skip it silently.
```

프롬프트 추가 위치는 feature 목록을 LLM에 전달하기 전 system instruction 섹션.

**보조 방어선**: 프롬프트만으로 100% 억제가 보장되지 않으므로, taxonomy 저장 전 후처리에서 `.autogen` 키를 제거하는 단순 필터를 추가한다.

```python
# taxonomy_reviewer.py — taxonomy 저장 직전
taxonomy = {k: v for k, v in taxonomy.items() if not k.endswith(".autogen")}
```

프롬프트가 1차 방어, 후처리가 2차 방어 역할을 하여 autogen 유입을 완전 차단한다.

---

## 수정 우선순위 및 실행 순서

| # | Fix | 파일 | 우선순위 | 비고 |
|---|-----|------|----------|------|
| A | 재부모화 시 이전 부모 children 제거 | `taxonomy_reviewer.py` | 🔴 High | 계층 정합성 근본 수정 |
| B | build_child_entries 후 class_feature_map 갱신 | `stage_b_mapper.py` | 🔴 High | .notier 직접 원인 |
| C | autogen 억제 프롬프트 + 후처리 필터 | `taxonomy_reviewer.py` | 🟡 Medium | 프롬프트 오탐 가능성 낮음 |

**실행 순서**: Fix A → Fix B (B는 A가 완료된 이후 올바른 계층에서 child 매핑 가능)  
Fix C는 독립적으로 적용 가능.

---

## 검증 방법

1. `taxonomy_reviewer.py` 실행 후 `feature_taxonomy.json` 확인:
   - `animated-image-view.parent == "image-view"` (Fix A)
   - `view.children`에 `animated-image-view` 없음 (Fix A)
   - `*.autogen` 키 없음 (Fix C)

2. `stage_b_mapper.py` 실행 후 `class_feature_map.json` 확인:
   - `"Dali::AnimatedImageView": "animated-image-view"` (Fix B)
   - `"Dali::LottieAnimationView": "lottie-animation-view"` (Fix B)

3. Stage C 실행 후:
   - `animated-image-view/`, `lottie-animation-view/` 디렉터리에 `.notier` 없음 (Fix B)
   - 실제 `.md` 문서 생성 확인
