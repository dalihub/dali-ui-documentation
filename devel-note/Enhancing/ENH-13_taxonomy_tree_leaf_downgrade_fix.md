# [BUG] taxonomy flat → tree → leaf 불일치 문제

## 현상

`image-view`가 `tree_decision: "tree"`임에도 `children: []`인 모순 상태가 되어
Stage B에서 taxonomy context가 주입되지 않고, LLM이 잘못된 "image-view family" 개요 문서를 생성한다.
`animated-image-view`, `lottie-animation-view`는 `parent: "view"`임에도
`decision_reason: "Child of image-view"`로 불일치 상태가 된다.

## 근본 원인

taxonomy_reviewer가 feature를 순차 처리하면서 LLM 결정 간 충돌이 발생한다.

1. `image-view` 처리 시: LLM이 "tree" 결정 → animated-image-view, lottie-animation-view를
   children으로 등록, 두 child의 parent = "image-view"로 설정
2. `view` 처리 시: LLM이 세 feature 모두를 view의 직속 children으로 결정
   → Fix A 코드가 animated-image-view, lottie-animation-view의 parent를
   "image-view" → "view"로 교정, image-view.children에서도 제거
3. **Fix A는 parent와 children 배열만 수정하고 `tree_decision`과 `decision_reason`은 건드리지 않음**

결과:
- `image-view`: tree_decision="tree"지만 children=[], parent="view" → 모순 상태
- `animated-image-view`, `lottie-animation-view`: parent="view"지만 decision_reason="Child of image-view" → 불일치

Stage B 코드에서 `tree_decision == "tree" and children` 조건이 False가 되어
taxonomy context가 아무것도 주입되지 않음 → LLM이 가이드 없이 잘못된 개요 문서 생성.

## 영향 범위

- `image-view` Stage B/C/D 재실행 필요
- `animated-image-view`, `lottie-animation-view`는 taxonomy 값이 실질적으로 변하지 않아 재실행 불필요
- flat → tree → flat 케이스 (parent=null인 최상위 feature에서 발생 가능): decision_reason만 stale 상태로 남지만 pipeline 영향 없음

## 해결 방법

`taxonomy_reviewer.py` 영속화 직전에 후처리 검증 패스 2개 추가:

```python
for feat_key, entry in existing_taxonomy.items():
    # ① tree인데 children이 없으면 leaf/flat으로 다운그레이드 + decision_reason 교정
    if entry.get("tree_decision") == "tree" and not entry.get("children"):
        if entry.get("parent"):
            entry["tree_decision"] = "leaf"
            entry["decision_reason"] = f"Child of {entry['parent']}"
        else:
            entry["tree_decision"] = "flat"

    # ② decision_reason의 "Child of X"와 실제 parent가 불일치하면 교정
    dr = entry.get("decision_reason", "")
    parent = entry.get("parent", "")
    if dr.startswith("Child of ") and parent:
        if dr.replace("Child of ", "").strip() != parent:
            entry["decision_reason"] = f"Child of {parent}"
```

LLM 재호출 없는 순수 Python 후처리. taxonomy_reviewer 실행 시마다 자동 적용.

## 수정 후 효과

| 항목 | 수정 전 | 수정 후 |
|------|---------|---------|
| `image-view` tree_decision | "tree" (children=[]로 모순) | "leaf" |
| `image-view` decision_reason | "The image-view family includes..." | "Child of view" |
| `animated-image-view` decision_reason | "Child of image-view" (불일치) | "Child of view" |
| `lottie-animation-view` decision_reason | "Child of image-view" (불일치) | "Child of view" |
| Stage B taxonomy context | 아무것도 주입 안 됨 | leaf context 주입 → ImageView 집중 TOC |
| Stage C 문서 내용 | "image-view family" 잘못된 개요 | ImageView 단독 집중 문서 |
| Stage D 통과율 | 낮음 (hallucination) | 향상 예상 |

## 구현 체크리스트

- [ ] `taxonomy_reviewer.py` — 영속화 직전 후처리 패스 추가 (① tree+no children 다운그레이드, ② decision_reason 불일치 교정)
