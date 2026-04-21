# [ENH-25] Taxonomy Tree 품질 개선 및 Tree Feature 문서 생성 정확도 향상

## 개요

두 가지 독립적인 문제를 수정한다.

1. **Phase B 프롬프트 과도한 계층화** — "Organize them into a logical hierarchy"라는 지시가 LLM을 불필요한 tree-leaf 조합으로 유도하여, 의미적으로 독립적인 feature들이 억지로 parent-child 관계로 묶임
2. **Tree feature 문서 생성 정보 손실** — `_split_root`가 아닌 일반 feature가 Phase B에서 tree로 승격될 경우, 자체 API가 남아있음에도 stage_b/stage_c가 "PARENT OVERVIEW PAGE" 컨텍스트만 주입하여 해당 API들이 문서화되지 않음

---

## 배경: 코드 분석으로 확인된 현상

### Phase B 프롬프트 (`taxonomy_reviewer.py` line 448)

```python
prompt = f"""
...
Design a documentation tree structure for the following features.
Organize them into a logical hierarchy of at most 2 depth levels (root → children only).
...
For each feature, decide:
- "tree": this feature is a parent with children listed
- "flat": this feature stands alone (no children, no parent)
"""
```

"Organize them into a logical hierarchy"라는 지시가 LLM을 계층화 방향으로 과도하게 유도한다.  
의미적으로 독립적인 feature들도 억지로 parent-child 관계에 포함시키는 경향이 있다.

### Stage B tree 컨텍스트 (`stage_b_mapper.py` lines 287~314)

```python
if tree_decision == "tree" and children:
    taxonomy_context = f"""
    DOCUMENT STRUCTURE CONTEXT:
    This feature ('{feat_name}') is a PARENT document in a tree hierarchy.
    It should serve as an OVERVIEW page that introduces the concept and lists
    its child sub-components: {child_list}.
    ...
    Do NOT write deep API details for child components here — just overview.
    """
```

### Stage C tree 컨텍스트 (`stage_c_writer.py` lines 1519~1567)

```python
if tree_decision == "tree" and children:
    taxonomy_context = f"""
    DOCUMENT ROLE — PARENT OVERVIEW PAGE:
    ...
    Writing rules:
    - Introduce the overall concept and architecture of this feature family.
    - Describe each child component in 2-3 sentences and add a '→ See: [ChildName]' reference.
    - Do NOT write exhaustive API details for child components — just enough to understand when to use each.
    - Focus on how the parent and children relate structurally.
    """
```

**문제:** `_split_root` 여부에 무관하게 모든 tree feature에 동일한 "PARENT OVERVIEW PAGE" 컨텍스트가 주입된다. 분기 로직이 없다.

### 두 케이스의 차이

| 케이스 | `_split_root` | `apis` | 현재 동작 | 올바른 동작 |
|---|---|---|---|---|
| Split 부모 (Phase A-1) | `True` | `[]` (자식에게 분배됨) | OVERVIEW 페이지 생성 | 그대로 유지 (올바름) |
| 일반 feature → tree 승격 (Phase B) | 없음 | `[...]` (자체 API 보유) | OVERVIEW 페이지 생성 (정보 손실) | 자기 API 문서 + 하단 leaf 요약 |

Split 부모는 Phase A-1에서 API를 자식들에게 의도적으로 분배하고 비운다 (`taxonomy_reviewer.py` lines 268~274).  
일반 feature가 Phase B에서 tree로 승격되는 경우 API가 그대로 남아있으므로, 이 두 케이스를 구분해야 한다.

---

## 작업 1: Phase B 프롬프트 개선 (`taxonomy_reviewer.py`)

### 대상

- `design_tree_full()` — Full 모드 프롬프트
- `design_tree_incremental()` — Incremental 모드 프롬프트

### 변경 방향

"논리적 계층 구조로 구성하라"는 지시를 "의미적 소유 관계가 명확한 경우에만 묶으라"로 수정한다.  
flat이 기본 상태이며, tree-leaf는 관계가 명확할 때만 선택하도록 유도한다.

**변경 전:**
```
Design a documentation tree structure for the following features.
Organize them into a logical hierarchy of at most 2 depth levels (root → children only).
...
For each feature, decide:
- "tree": this feature is a parent with children listed
- "flat": this feature stands alone (no children, no parent)

Features not mentioned in the response will be treated as "flat".
```

**변경 후 (핵심 부분):**
```
Design a documentation tree structure for the following features.
Group features into parent-child relationships ONLY when there is a clear conceptual
ownership (e.g., a base class and its specializations, a container and its elements).
When in doubt, keep features as flat standalone pages.

For each feature, decide:
- "tree": this feature is a logical parent that owns the listed child sub-components
- "flat": this feature is an independent concept with no natural parent (DEFAULT)

Features not mentioned in the response will be treated as "flat".
Prefer fewer tree relationships over forcing artificial groupings.
```

### 영향 범위

| 파일 | 변경 내용 |
|---|---|
| `src/01_cluster/taxonomy_reviewer.py` | `design_tree_full()`, `design_tree_incremental()` 프롬프트 수정 |

---

## 작업 2: Tree feature 문서 생성 분기 (`stage_b_mapper.py`, `stage_c_writer.py`)

### 분기 기준

`_split_root: True` 플래그를 기준으로 두 경로를 분리한다.

- `_split_root: True` → 순수 overview 페이지 (현재 동작 유지)
- `_split_root` 없음 (일반 tree feature) → 자기 API 문서 + 하단 leaf 요약 섹션

### Stage B 변경 (`stage_b_mapper.py`)

```python
# feature_map에서 _split_root 여부 조회
is_split_root = fm_entry.get("_split_root", False) if fm_entry else False

if tree_decision == "tree" and children:
    if is_split_root:
        # 기존: 순수 overview (split 부모, API 없음)
        taxonomy_context = f"""
        DOCUMENT STRUCTURE CONTEXT:
        This feature ('{feat_name}') is a PARENT OVERVIEW page for a split feature family.
        Its child sub-components ({child_list}) each contain the detailed APIs.
        Write an overview introducing the feature family and briefly describing each child.
        Do NOT write API details — children have dedicated pages.
        """
    else:
        # 신규: 자기 API 문서 + 하단 leaf 요약
        taxonomy_context = f"""
        DOCUMENT STRUCTURE CONTEXT:
        This feature ('{feat_name}') is a parent in the documentation tree with child
        sub-components: {child_list}.
        Write full documentation for '{feat_name}' own APIs as normal.
        At the end, add a brief "Related Sub-Components" section that introduces each child
        in 1-2 sentences and links to its dedicated page.
        Do NOT write deep API details for child components — just a brief introduction.
        """
```

### Stage C 변경 (`stage_c_writer.py`)

동일한 `_split_root` 기준으로 taxonomy_context 분기:

```python
is_split_root = fm_entry.get("_split_root", False) if fm_entry else False

if tree_decision == "tree" and children:
    if is_split_root:
        # 기존: 순수 overview
        taxonomy_context = f"""
        DOCUMENT ROLE — PARENT OVERVIEW PAGE (split family):
        This is the overview page for the '{feat_name}' feature family.
        Child components ({child_list}) each have their own dedicated pages.
        Writing rules:
        - Introduce the overall concept and architecture of this feature family.
        - Describe each child component in 2-3 sentences and add a '→ See: [ChildName]' reference.
        - Do NOT write exhaustive API details — children cover all APIs.
        """
    else:
        # 신규: 자기 문서 + 하단 child 소개
        taxonomy_context = f"""
        DOCUMENT ROLE — PRIMARY FEATURE PAGE WITH SUB-COMPONENTS:
        This feature ('{feat_name}') has its own APIs to document, and also serves as a
        logical parent for child sub-components: {child_list}.
        Writing rules:
        - Document '{feat_name}' own APIs fully and in detail (same as a flat feature).
        - At the end of the document, add a "Related Sub-Components" section.
          For each child, write 1-2 sentences describing its role and add a '→ See: [ChildName]' link.
        - Do NOT write exhaustive API details for child components in this page.
        """
```

### 영향 범위

| 파일 | 변경 내용 |
|---|---|
| `src/02_llm/stage_b_mapper.py` | tree 컨텍스트 주입 시 `_split_root` 기준 분기 추가 |
| `src/02_llm/stage_c_writer.py` | tree 컨텍스트 주입 시 `_split_root` 기준 분기 추가 |

---

## 전체 영향 범위 요약

| 파일 | 작업 |
|---|---|
| `src/01_cluster/taxonomy_reviewer.py` | 1 (Phase B 프롬프트 수정) |
| `src/02_llm/stage_b_mapper.py` | 2 (tree 컨텍스트 분기) |
| `src/02_llm/stage_c_writer.py` | 2 (tree 컨텍스트 분기) |

## 작업 순서

작업 1 → 작업 2 순으로 진행한다.

- 작업 1로 불필요한 tree 승격이 줄어들면, 작업 2의 분기가 적용되는 케이스도 자연히 줄어듦
- 작업 2는 작업 1과 독립적이므로 병렬 진행 가능하나, 작업 1 완료 후 통합 테스트 권장
