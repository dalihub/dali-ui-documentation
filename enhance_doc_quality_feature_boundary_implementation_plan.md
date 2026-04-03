# 문서 품질 개선 — Feature 경계 정확도 및 Actor/View 통합 구현 계획

## 1. 문제 정의

### 1.1 문제 A — Spec 오염 (Cross-Feature Spec Contamination)

`SpringData` 같은 클래스가 `actors.md`, `common.md`, `math.md` 등 여러 feature 문서에 동시에 나타난다.

**근본 원인:**

`get_api_specs()`의 매칭 로직이 느슨하다.

```python
# stage_c_writer.py 현재 코드
api_name_set = set(a.split("::")[-1] for a in api_names_list)  # 단순 이름 집합
is_class_match = any(a in c_name for a in api_names_list) or \
                 any(c_name.split("::")[-1] in api_name_set for _ in [1])
```

- `api_names_list`에 `"Dali::Actor"`가 있으면 `api_name_set`에 `"Actor"`가 들어간다
- Doxygen 전체 compound를 순회하면서 이름이 부분적으로 겹치는 것을 모두 가져온다
- `feature_clusterer`가 디렉터리 기반으로 분류하므로 `SpringData`가 `actors/` 폴더에 있으면 `actors` feature에 묶이고, `common/`에도 있으면 `common`에도 묶인다
- 각 클래스가 **정확히 하나의 feature에만 귀속**된다는 보장이 없다

### 1.2 문제 B — Actor 별도 문서 생성

`actors.md`가 생성되지만 최신 DALi 개발 가이드에서는 Actor 대신 View를 사용해야 한다.
Actor 관련 내용은 View 문서에 "inherited context"로 통합하는 것이 적절하다.

현재 `repo_config.yaml`에 `audience: "platform"`이 설정되어 있어 app-guide에서는 제외되지만,
platform-guide에서도 별도 문서로 나타나는 것은 불필요하다.

### 1.3 문제 C — CustomActor 별도 문서 생성

`custom-actor.md`가 생성되지만 앱 개발자나 플랫폼 개발자 모두 `CustomActor`를 직접 쓸 일이 없다.
문서에서 완전히 제거하는 것이 맞다.

---

## 2. 해결 전략

### 2.1 전략 A — 배타적 Feature-Class 매핑 (문제 A)

`feature_clusterer.py`가 빌드 시점에 **클래스 → feature** 역매핑을 생성하고,
`get_api_specs()`가 이 맵을 참조해 현재 feature 소속이 아닌 클래스를 명시적으로 제외한다.

```
feature_clusterer.py 출력 추가:
  cache/feature_map/class_feature_map.json
  {
    "Dali::Actor":      "actors",
    "Dali::SpringData": "animation",   ← 다른 feature 소속
    "Dali::Vector2":    "math",
    ...
  }

get_api_specs() 동작 변경:
  현재: 이름이 겹치면 포함
  변경: class_feature_map에서 현재 feature 소속인 클래스만 포함
        → 다른 feature 소속 클래스는 foreign_classes로 분리
        → Stage C 프롬프트에 foreign_classes 목록 추가 ("이 클래스는 다루지 말 것")
```

### 2.2 전략 B+C — suppress_doc / merge_into 설정 (문제 B, C)

`repo_config.yaml`의 `manual_features`에 두 가지 새 플래그를 추가한다.

| 플래그 | 의미 |
|---|---|
| `suppress_doc: true` | 이 feature의 `.md` 파일을 생성하지 않는다 |
| `merge_into: "target"` | spec을 target feature 문서에 inherited context로 포함시킨다 |

파이프라인 각 단계가 이 플래그를 인식하도록 수정한다.

---

## 3. 상세 구현 계획

### 3.1 전략 A 구현

#### Step A-1: `feature_clusterer.py` — `class_feature_map.json` 생성

`main()` 직렬화 단계에 추가.
각 클래스 이름이 어느 feature에 속하는지 **단일 매핑**으로 저장한다.
같은 클래스가 여러 feature의 api 목록에 중복 등록된 경우, 더 구체적인 feature(하위 디렉터리)를 우선한다.

```json
// cache/feature_map/class_feature_map.json
{
  "Dali::Actor": "actors",
  "Dali::DevelActor": "actors",
  "Dali::SpringData": "animation",
  "Dali::Vector2": "math",
  "Dali::Matrix": "math"
}
```

#### Step A-2: `stage_c_writer.py` — `get_api_specs()` 수정

```python
def get_api_specs(pkg_names, api_names_list, allowed_tiers=None,
                  owning_feature=None, class_feature_map=None):
    """
    owning_feature: 현재 문서를 생성 중인 feature 이름
    class_feature_map: {class_name: feature_name} 역매핑

    class_feature_map이 제공된 경우:
    - owning_feature 소속 클래스만 specs에 포함
    - 다른 feature 소속 클래스는 foreign_classes 목록으로 반환
    """
    specs = []
    foreign_classes = []
    ...
    # 매칭 시:
    if class_feature_map and owning_feature:
        mapped_feature = class_feature_map.get(c_name)
        if mapped_feature and mapped_feature != owning_feature:
            foreign_classes.append(c_name)  # 제외 목록으로
            continue
    specs.append(...)
    ...
    return specs, foreign_classes  # 반환값 변경
```

#### Step A-3: `stage_c_writer.py` — Stage C 프롬프트에 foreign_classes 주입

```
SCOPE BOUNDARY — DO NOT DOCUMENT THESE CLASSES:
The following classes appear in the codebase but belong to OTHER features.
Do NOT describe, mention, or write code examples using them:
- Dali::SpringData  (belongs to: animation)
- Dali::Vector3     (belongs to: math)
```

---

### 3.2 전략 B+C 구현

#### Step B-1: `repo_config.yaml` 수정

```yaml
manual_features:
  - feature: "actors"
    display_name: "Actor (Scene Graph Node)"
    source_package: "dali-core"
    base_class: "Dali::Actor"
    description: "..."
    suppress_doc: true       # actors.md 생성 안 함
    merge_into: "view"       # Actor spec을 View 문서에 inherited context로 포함

  - feature: "custom-actor"
    display_name: "CustomActor"
    source_package: "dali-core"
    suppress_doc: true       # custom-actor.md 생성 안 함
    # merge_into 없음 — 어디에도 포함하지 않음
```

#### Step B-2: `feature_clusterer.py` — suppress_doc / merge_into 전파

`manual_features` 처리 시 기존 클러스터에 플래그를 그대로 저장한다.
(현재 `display_name`, `description` 등 메타데이터를 보강하는 코드 블록에 추가)

```json
// feature_map.json 해당 항목 예시
{
  "feature": "actors",
  "suppress_doc": true,
  "merge_into": "view",
  ...
}
```

#### Step B-3: `taxonomy_reviewer.py` — suppress_doc feature taxonomy 등록

suppress_doc feature도 taxonomy에 등록은 하되 플래그를 유지한다.
(taxonomy는 merge_into 대상인 View가 어떤 스펙을 상속받는지 참조할 때 필요)

#### Step B-4: `stage_c_writer.py` — suppress/merge 처리

**suppress 처리:**
```python
# main() 루프에서 blueprint 처리 전
if taxonomy.get(feat_name, {}).get("suppress_doc") or \
   feature_map_entry.get("suppress_doc"):
    print(f"[{idx+1}] SKIP '{feat_name}': suppress_doc=true")
    continue
```

**merge_into 처리 (View 문서 생성 시) — View-Actor 차집합 방식:**

View가 이미 갖고 있는 메서드는 Actor 것을 다시 포함하지 않는다.
Python에서 메서드 이름 집합 차집합으로 처리하므로 LLM 추가 호출 없음.

```python
# 1. View 메서드 이름 집합 추출
view_method_names = {
    s["name"].split("::")[-1]
    for s in view_specs
    if s.get("kind") != "class"
}

# 2. merge_into 대상 feature(actors)의 public-api 스펙 로드 (압축: name+brief+signature만)
actor_specs_raw, _ = get_api_specs(
    actor_packages, actor_apis, allowed_tiers={"public-api"}
)

# 3. View에 없는 Actor 메서드만 inherited_specs로 추출
inherited_specs = [
    {"name": s["name"], "brief": s.get("brief",""), "signature": s.get("signature","")}
    for s in actor_specs_raw
    if s.get("kind") != "class"
    and s["name"].split("::")[-1] not in view_method_names
]
# 예: SetPosition → View에 있음 → 제외
#     SetColor    → View에 없음 → 포함 (압축 형태)
```

토큰 예상: 4,000 스펙 → public-api 필터 → View 중복 제거 → 수십~수백 개 수준

**View 프롬프트에 inherited_specs 추가:**
```
INHERITED API CONTEXT (from Actor — View's base class):
The following APIs exist on Actor but are NOT directly defined in View's own API.
View inherits them. Include them only as supplementary context where relevant.
- Do NOT write dedicated sections for these — weave into existing sections naturally.
- Always use View references in code examples, not raw Actor.
[inherited_specs JSON — name+brief+signature only]
```

#### Step B-5: `index_generator.py` — suppress_doc 제외

```python
# top_level_roots 수집 시 한 줄 추가
if entry.get("suppress_doc"):
    continue
```

---

## 4. 변경 파일 및 영향도

| 파일 | 변경 유형 | 내용 |
|---|---|---|
| `config/repo_config.yaml` | 설정 추가 | `actors`, `custom-actor`에 `suppress_doc`, `merge_into` 추가 |
| `src/01_cluster/feature_clusterer.py` | 기능 추가 | `class_feature_map.json` 생성, suppress/merge 플래그 전파 |
| `src/01_cluster/taxonomy_reviewer.py` | 경미 수정 | suppress_doc feature taxonomy 등록 유지 |
| `src/02_llm/stage_c_writer.py` | 기능 추가 | `get_api_specs()` 반환값 변경, suppress 스킵, merge inherited_specs 로드, 프롬프트 수정 |
| `src/03_render/index_generator.py` | 경미 수정 | suppress_doc 항목 인덱스 제외 |
| `src/03_render/sidebar_generator.py` | 변경 없음 | 실제 .md 파일 기준 동작 — 자동 처리 |
| `cache/feature_map/class_feature_map.json` | 신규 생성 | 런타임 생성 |

### 4.1 하위 호환성

- suppress_doc / merge_into 플래그가 없는 기존 feature는 코드 경로 변화 없음
- class_feature_map이 없는 경우 (첫 실행 또는 캐시 없음) `get_api_specs()`는 기존 방식으로 fallback
- `--tier app` 실행에서 `actors`는 이미 `audience: "platform"` 필터로 제외 중 → 추가 영향 없음

---

## 5. 구현 순서

| 단계 | 작업 | 우선순위 |
|---|---|---|
| Step 1 | `repo_config.yaml`에 `suppress_doc`, `merge_into` 추가 | 높음 |
| Step 2 | `feature_clusterer.py` — 플래그 전파 + `class_feature_map.json` 생성 | 높음 |
| Step 3 | `stage_c_writer.py` — suppress 스킵 + merge inherited_specs | 높음 |
| Step 4 | `index_generator.py` — suppress_doc 제외 | 높음 |
| Step 5 | `stage_c_writer.py` — `get_api_specs()` 정밀 매칭 + foreign_classes 프롬프트 | 중간 |
| Step 6 | E2E 테스트: actors 미생성 확인, view.md에 Actor 상속 내용 포함 확인, SpringData 오염 제거 확인 | — |

Step 1~4 (suppress/merge)는 독립적으로 먼저 배포 가능하다.
Step 5 (spec 오염 제거)는 `feature_clusterer` 재실행이 필요하므로 별도 진행한다.

---

## 6. 리스크 및 대응

| 리스크 | 가능성 | 대응 |
|---|---|---|
| class_feature_map의 우선순위 충돌 (같은 클래스가 두 feature 목록에 있을 때) | 중간 | 더 구체적인 경로(하위 디렉터리 깊이)를 기준으로 우선순위 결정 |
| inherited_specs가 너무 많아 View 문서 토큰 초과 | 낮음 | View-Actor 차집합 후에도 많으면 `spec_token_threshold` 적용, 초과 시 name만 포함하는 최소 압축 모드 사용 |
| suppress된 feature가 다른 feature의 children로 taxonomy에 등록된 경우 | 낮음 | taxonomy_reviewer에서 suppress_doc children을 parent children 목록에서도 제거 |
| View 문서에서 Actor 상속 내용이 너무 많이 노출될 경우 | 중간 | inherited_specs 프롬프트 규칙을 엄격하게 — "1문장 + 링크"만 허용 |

---

## 7. 검증 기준

- [ ] `actors.md`, `custom-actor.md`가 생성되지 않음
- [ ] `view.md`에 Actor 상속 API가 배경 컨텍스트로 포함됨 (전용 섹션 없이)
- [ ] `index.md`에 actors, custom-actor 항목이 없음
- [ ] `sidebar.json`에 actors, custom-actor 항목이 없음 (이미 자동 처리)
- [ ] `SpringData`가 actors.md, common.md, math.md에 나타나지 않음
- [ ] 기존 정상 feature (animation, math, common 등) 문서 생성에 영향 없음
