# .notier 문서 생성 실패 해결 구현 계획

## 1. 문제 정의

### 1.1 발생 현상

`label`, `input-field`, `scroll-view`, `lottie-animation-view`, `layout` 등 dali-ui의 주요 컴포넌트들이 Stage C 실행 후 `.md` 파일 대신 `.notier` 마커 파일만 생성된다. 해당 파일의 내용은 비어 있으며, 문서로 이어지지 않는다.

```
cache/markdown_drafts/app/
  view.md            ← 정상 생성
  label.notier       ← 문서 없음
  input-field.notier ← 문서 없음
  scroll-view.notier ← 문서 없음
  ...
```

### 1.2 근본 원인 분석

세 단계가 연쇄적으로 작용한다.

---

**원인 1 — `feature_clusterer.py`: tier 루트 파일의 feature 분류 실패**

`extract_feature_name()` 함수는 파일이 tier 디렉토리 하위 **서브폴더**에 있을 때만 feature 이름을 추출한다.

```python
# feature_clusterer.py:80-97
def extract_feature_name(file_path, api_tiers):
    for tier in api_tiers:
        if tier in file_path:
            parts = file_path.split(tier + "/")
            if len(parts) > 1:
                sub_path = parts[1]
                sub_parts = sub_path.split("/")
                if len(sub_parts) > 1:
                    return sub_parts[0]  # 예: "actors/actor.h" → "actors" (정상)
                else:
                    return None          # ← 문제: "label.h" → None
    return None
```

dali-ui의 `Dali::Ui::Label` 실제 경로:
```
repos/dali-ui/dali-ui-foundation/public-api/label.h   ← 서브폴더 없이 tier 루트에 직접 위치
```

경로 분리 결과:
```
tier = "dali-ui-foundation/public-api"
sub_path = "label.h"
sub_parts = ["label.h"]  →  len == 1  →  return None
```

`None`이 반환되면 `feature_name = "uncategorized_ambiguous_root"`로 대체되어, `Dali::Ui::Label`을 비롯한 모든 tier 루트 파일 소속 클래스가 잘못된 feature에 등록된다.

```json
// cache/feature_map/class_feature_map.json (현재 상태)
"Dali::Ui::Label":          "uncategorized_ambiguous_root",
"Dali::Ui::InputField":     "uncategorized_ambiguous_root",
"Dali::Ui::ScrollView":     "uncategorized_ambiguous_root",
"Dali::Ui::Layout":         "uncategorized_ambiguous_root",
"Dali::Ui::LottieAnimationView": "uncategorized_ambiguous_root"
```

---

**원인 2 — `stage_b_mapper.py`: taxonomy child 주입 시 `class_feature_map` 미갱신**

`feature_clusterer.py`에 `label` feature가 존재하지 않기 때문에, `stage_b_mapper.py`의 `build_child_entries()`가 taxonomy에서 `label`을 leaf child로 감지하고 blueprint에 동적 주입한다. 그러나 이 주입 단계는 `class_feature_map.json`을 갱신하지 않는다.

```python
# stage_b_mapper.py:94-123
def build_child_entries(taxonomy, existing_feature_keys):
    child_entries = []
    for feat_key, tax_entry in taxonomy.items():
        if tax_entry.get("tree_decision") != "leaf":
            continue
        if feat_key in existing_feature_keys:
            continue  # feature_map에 이미 있으면 스킵

        # Doxygen에서 API 찾아서 blueprint에 주입
        child_entries.append({...})
    return child_entries
    # ← class_feature_map.json은 갱신하지 않음
```

결과: `label` feature가 blueprint에는 존재하지만 `class_feature_map.json`에는 없다.

---

**원인 3 — `stage_c_writer.py`: foreign class 필터링이 taxonomy child의 스펙을 전부 제거**

`get_api_specs()`는 `class_feature_map`을 참조하여 다른 feature 소속 클래스를 `foreign_classes`로 제외한다.

```python
# stage_c_writer.py:243-248
mapped = class_feature_map.get(c_name)   # → "uncategorized_ambiguous_root"
if mapped and mapped != owning_feature:  # "uncategorized_ambiguous_root" != "label"
    foreign_classes.append(c_name)        # Dali::Ui::Label이 foreign으로 간주됨
    continue
```

`Dali::Ui::Label`의 `class_feature_map` 값이 `"uncategorized_ambiguous_root"`이고,
현재 처리 중인 `owning_feature`는 `"label"`이므로 불일치 → **모든 label 클래스가 제외됨**.

```python
# stage_c_writer.py:601-605
if not specs:
    (tier_drafts_dir / f"{feat_name}.notier").touch()  # .notier 파일 생성
    continue
```

---

**왜 `view`는 정상 작동하는가?**

`view`는 `repo_config.yaml`의 `manual_features`에서 `base_class: "Dali::Ui::View"`로 직접 주입된다. `feature_clusterer.py`가 이 base_class 기반으로 `class_feature_map["Dali::Ui::View"] = "view"`를 정확히 등록하므로, stage_c의 foreign class 필터를 통과한다.

---

### 1.3 영향 범위

tier 루트(`public-api/` 바로 아래)에 위치한 **모든 dali-ui 컴포넌트 헤더 파일**이 해당된다.

| 파일 | 클래스 | 현재 class_feature_map |
|---|---|---|
| `public-api/label.h` | `Dali::Ui::Label` | `uncategorized_ambiguous_root` |
| `public-api/input-field.h` | `Dali::Ui::InputField` | `uncategorized_ambiguous_root` |
| `public-api/scroll-view.h` | `Dali::Ui::ScrollView` | `uncategorized_ambiguous_root` |
| `public-api/layout.h` | `Dali::Ui::Layout` | `uncategorized_ambiguous_root` |
| `public-api/lottie-animation-view.h` | `Dali::Ui::LottieAnimationView` | `uncategorized_ambiguous_root` |

---

## 2. 해결 전략

두 지점을 각각 수정한다. Fix 1이 근본 수정이며, Fix 2는 방어적 안전망이다.

```
[Fix 1] feature_clusterer.py
  tier 루트 파일 → 파일명을 feature 이름으로 사용
  → class_feature_map에 올바른 feature 등록
  → stage_b taxonomy child 주입 불필요 (이미 feature_map에 존재)
  → stage_c foreign 필터 통과

[Fix 2] stage_c_writer.py (안전망)
  uncategorized_ambiguous_root 매핑은 "미소유"로 간주
  → owning_feature와 불일치해도 foreign 처리 안 함
  → Fix 1 누락 케이스 방어
```

---

## 3. 상세 구현 계획

### 3.1 Fix 1 — `feature_clusterer.py`: `extract_feature_name()` 수정

**수정 위치:** `src/01_cluster/feature_clusterer.py:94`

**현재 코드:**
```python
def extract_feature_name(file_path, api_tiers):
    for tier in api_tiers:
        if tier in file_path:
            parts = file_path.split(tier + "/")
            if len(parts) > 1:
                sub_path = parts[1]
                sub_parts = sub_path.split("/")
                if len(sub_parts) > 1:
                    return sub_parts[0]
                else:
                    return None          # ← 이 분기
    return None
```

**수정 후:**
```python
def extract_feature_name(file_path, api_tiers):
    for tier in api_tiers:
        if tier in file_path:
            parts = file_path.split(tier + "/")
            if len(parts) > 1:
                sub_path = parts[1]
                sub_parts = sub_path.split("/")
                if len(sub_parts) > 1:
                    return sub_parts[0]                        # 기존: "actors/actor.h" → "actors"
                else:
                    stem = sub_parts[0].rsplit(".", 1)[0]      # 신규: "label.h" → "label"
                    return stem if stem else None
    return None
```

**기대 효과:**

`label.h` → `"label"`, `input-field.h` → `"input-field"`, `scroll-view.h` → `"scroll-view"` 등이 각각 독립적인 feature 클러스터로 등록된다.

```json
// 수정 후 class_feature_map.json
"Dali::Ui::Label":          "label",
"Dali::Ui::InputField":     "input-field",
"Dali::Ui::ScrollView":     "scroll-view",
"Dali::Ui::Layout":         "layout",
"Dali::Ui::LottieAnimationView": "lottie-animation-view"
```

**stage_b와의 연쇄 효과:**

`feature_map.json`에 `label`이 생기면 `stage_b_mapper.py`의 `build_child_entries()`는 `existing_feature_keys`에서 `label`을 발견하고 taxonomy child 주입을 건너뛴다. 중복 없이 자연스럽게 수렴된다.

```python
# stage_b_mapper.py:103-104
if feat_key in existing_feature_keys:
    continue  # "label"이 feature_map에 이미 있으므로 주입 안 함
```

---

### 3.2 Fix 2 — `stage_c_writer.py`: `uncategorized_ambiguous_root` 안전망

**수정 위치:** `src/02_llm/stage_c_writer.py:243-248`, `get_api_specs()` 함수 내부

**현재 코드:**
```python
if class_feature_map and owning_feature:
    mapped = class_feature_map.get(c_name)
    if mapped and mapped != owning_feature:
        foreign_classes.append(c_name)
        continue
```

**수정 후:**
```python
if class_feature_map and owning_feature:
    mapped = class_feature_map.get(c_name)
    # uncategorized_ambiguous_root는 "미분류"이지 "다른 feature 소유"가 아님
    # → owning_feature가 명시적으로 이 클래스를 api_names에 포함한 경우 통과
    if mapped and mapped != owning_feature and mapped != "uncategorized_ambiguous_root":
        foreign_classes.append(c_name)
        continue
```

**의도:**

`class_feature_map` 값이 `"uncategorized_ambiguous_root"`인 클래스는 어느 feature에도 귀속되지 못한 상태이다. 이 경우 현재 처리 중인 feature의 `api_names`에 명시된 클래스라면 foreign으로 제외하지 않고 포함한다. Fix 1로 대부분의 케이스가 해소되지만, 향후 추가될 tier 루트 파일이나 예외 케이스에 대한 방어망 역할을 한다.

---

## 4. 변경 파일 및 영향도

| 파일 | 변경 유형 | 영향 범위 |
|---|---|---|
| `src/01_cluster/feature_clusterer.py` | 버그 수정 (1줄 교체) | tier 루트 파일의 feature 분류 |
| `src/02_llm/stage_c_writer.py` | 조건 완화 (1줄 수정) | `get_api_specs()` foreign class 필터 |
| `cache/feature_map/feature_map.json` | 런타임 재생성 | `label`, `input-field` 등 신규 feature 추가 |
| `cache/feature_map/class_feature_map.json` | 런타임 재생성 | 해당 클래스들이 올바른 feature로 재등록 |

변경하지 않는 파일:
- `stage_b_mapper.py` — 수정 불필요 (existing_feature_keys 체크로 자동 수렴)
- `stage_a_classifier.py` — 변경 없음
- `taxonomy_reviewer.py` — 변경 없음
- `pipeline.py` — 변경 없음

### 4.1 하위 호환성

- 기존에 정상 동작하던 `view`, `animation` 등 서브폴더 기반 feature는 코드 경로가 동일하게 유지된다.
- `manual_features`(`view`, `actors`, `custom-actor`)는 feature_clusterer 경로와 무관하게 강제 주입되므로 영향 없다.
- tier 루트 파일이 없는 `dali-core`, `dali-adaptor`는 `extract_feature_name`의 `len(sub_parts) > 1` 분기를 그대로 타므로 영향 없다.

### 4.2 파이프라인 실행 순서

```
기존:
  feature_clusterer  →  stage_a  →  stage_b (label taxonomy child 주입)
    →  stage_c (label foreign 필터 → specs 없음 → .notier)

수정 후:
  feature_clusterer (label 등 tier 루트 파일 → 정상 feature 등록)
    →  stage_a  →  stage_b (label이 existing_keys에 있으므로 주입 스킵)
    →  stage_c (class_feature_map["Dali::Ui::Label"] = "label" → 매칭 → specs 수집)
    →  label.md 생성
```

---

## 5. 구현 단계

| 단계 | 작업 | 파일 |
|---|---|---|
| Step 1 | `extract_feature_name()`의 `return None` → 파일명 stem 반환으로 교체 | `feature_clusterer.py` |
| Step 2 | `get_api_specs()`의 foreign class 조건에 `uncategorized_ambiguous_root` 예외 추가 | `stage_c_writer.py` |
| Step 3 | `feature_clusterer.py` 재실행 → `feature_map.json`, `class_feature_map.json` 재생성 확인 | — |
| Step 4 | `stage_a`, `stage_b`, `stage_c --features label,input-field,scroll-view` 순서로 실행 | — |
| Step 5 | 생성된 `.md` 파일 존재 및 내용 확인 | — |

Step 1, 2는 서로 독립적으로 적용 가능하다. Step 1만으로 대부분의 케이스가 해소되며, Step 2는 추가 방어망이다.

---

## 6. 리스크 및 대응

| 리스크 | 가능성 | 대응 |
|---|---|---|
| tier 루트에 컴포넌트가 아닌 공통 헤더(`types.h`, `common.h` 등)가 있어 원치 않는 feature 생성 | 낮음 | `feature_map_classified.json`에서 Stage A가 `audience`를 판단하므로 suppress_doc이나 audience 필터로 대응 가능 |
| 동일한 파일명 stem이 여러 tier에 존재하여 중복 feature 생성 | 낮음 | `feature_map`은 cluster_key 기반 dict이므로 같은 이름이면 자동으로 병합됨 |
| Fix 2 적용 후 uncategorized 클래스가 여러 feature에 동시 포함 | 중간 | Fix 1로 근본 해소 시 Fix 2는 거의 작동하지 않음. 단, uncategorized 클래스가 두 feature의 api_names에 모두 있는 경우 중복 문서화 가능 — Stage D 검증에서 확인 |
| feature_clusterer 재실행 후 기존 taxonomy 구조와 충돌 | 낮음 | 신규로 생긴 `label` 등은 taxonomy_reviewer가 다음 실행 시 tree/leaf 판단. 첫 실행은 flat으로 처리됨 |

---

## 7. 검증 기준

- [ ] `feature_map.json`에 `label`, `input-field`, `scroll-view`, `layout`, `lottie-animation-view` feature가 추가됨
- [ ] `class_feature_map.json`에서 `"Dali::Ui::Label"` 값이 `"label"`으로 등록됨
- [ ] Stage C 실행 후 `label.md`, `input-field.md` 등 `.md` 파일이 생성됨
- [ ] 생성된 문서에 `Dali::Ui::Label` 클래스의 실제 메서드가 기술됨 (할루시네이션 아님)
- [ ] `view.md` 등 기존 정상 동작하던 문서는 내용 변화 없음
- [ ] `uncategorized_ambiguous_root` feature의 api 목록에서 `Dali::Ui::Label` 등이 사라짐
