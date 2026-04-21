"""
taxonomy_reviewer.py — Phase 1.5: Feature 재구조화 및 Taxonomy Tree 설계

Phase A: Feature 재구조화
  A-1: Oversized feature를 split_candidates 기반으로 분할 → feature_map.json에 sub-feature 추가
  A-2: 소규모 feature를 LLM 판단으로 통합 → suppress_doc + merge_into 설정
  A-3: 변경된 feature_map.json 저장 (class_feature_map 재계산은 stage_a 책임)

Phase B: 전체 일괄 Tree 설계 (LLM 1회 호출)
  - 재구조화된 전체 feature 목록을 한 번에 LLM에 전달
  - 최대 2뎁스 트리 생성
  - split locked 그룹 제약 적용
  - 증분 모드: 기존 taxonomy를 컨텍스트로 제공하여 변경사항만 반영

출력:
  feature_taxonomy.json — 트리 구조 정보
  feature_map.json      — split/merge 반영된 feature 목록 (갱신)

출력 schema (feature_taxonomy.json):
  {
    "view": {
      "display_name": "View (Base UI Object)",
      "parent": null,
      "children": ["image-view", "label", "scroll-view"],
      "doc_file": "view.md",
      "tree_decision": "tree",
      "decision_reason": "..."
    },
    ...
  }
"""

import re
import json
import argparse
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent / "02_llm"))
from llm_client import LLMClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = PROJECT_ROOT / "cache"
FEATURE_MAP_PATH = CACHE_DIR / "feature_map" / "feature_map.json"
PARSED_DOXYGEN_DIR = CACHE_DIR / "parsed_doxygen"
TAXONOMY_DIR = CACHE_DIR / "feature_taxonomy"
TAXONOMY_PATH = TAXONOMY_DIR / "feature_taxonomy.json"
DOC_CONFIG_PATH = PROJECT_ROOT / "config" / "doc_config.yaml"


def load_json(path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_doc_config():
    import yaml
    if not DOC_CONFIG_PATH.exists():
        return {}
    with open(DOC_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def extract_json_from_text(text):
    """JSON 배열 또는 객체를 텍스트에서 추출."""
    match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        text_to_parse = match.group(1)
    else:
        # 배열 우선 탐색
        start_arr = text.find('[')
        start_obj = text.find('{')
        if start_arr != -1 and (start_obj == -1 or start_arr < start_obj):
            end = text.rfind(']') + 1
            text_to_parse = text[start_arr:end] if end > 0 else text
        elif start_obj != -1:
            end = text.rfind('}') + 1
            text_to_parse = text[start_obj:end] if end > 0 else text
        else:
            text_to_parse = text
    try:
        return json.loads(text_to_parse)
    except Exception as e:
        print(f"   [JSON Parse Error] {e}")
        return None


def count_feature_specs(feat, all_compounds_by_name):
    """feature의 총 spec 수(클래스 + 멤버)를 반환."""
    total = 0
    for name in feat.get("apis", []):
        compound = all_compounds_by_name.get(name)
        if compound:
            total += 1 + len(compound.get("members", []))
        else:
            total += 1
    return total


def build_all_compounds_index():
    """parsed_doxygen에서 {class_name: compound_dict} 인덱스 구축."""
    index = {}
    for pkg_json in PARSED_DOXYGEN_DIR.glob("*.json"):
        data = load_json(pkg_json)
        if not data:
            continue
        for comp in data.get("compounds", []):
            name = comp.get("name", "")
            if name:
                index[name] = comp
    return index


# ─────────────────────────────────────────────────────────────────────────────
# Phase A-1: Oversized Feature 분할
# ─────────────────────────────────────────────────────────────────────────────

def get_oversized_candidates(feature_list, existing_taxonomy):
    """
    oversized: true이고 split_candidates가 3개 이상인 feature 중
    아직 taxonomy에 등록되지 않은 것을 반환.
    """
    candidates = []
    for feat in feature_list:
        if not feat.get("oversized"):
            continue
        feat_name = feat.get("feature", "")
        split_candidates = feat.get("split_candidates", [])
        if len(split_candidates) < 3:
            continue
        existing = existing_taxonomy.get(feat_name, {})
        if existing.get("tree_decision") in ("tree", "flat", "leaf") or existing.get("oversized_single"):
            continue
        candidates.append(feat)
    return candidates


def review_oversized_feature(feat, client):
    """
    oversized feature의 split_candidates를 LLM에 제시하고
    split/single 여부를 판단받는다.

    반환: ("split", [children_list]) 또는 ("single", [])
    """
    feat_name = feat.get("feature", "")
    split_candidates = feat.get("split_candidates", [])
    total_specs = feat.get("total_spec_count", 0)

    groups_summary = [
        {"group": c["group_name"], "sample_apis": c["apis"][:5]}
        for c in split_candidates
    ]

    prompt = f"""
    You are a C++ framework documentation architect for the Samsung DALi UI framework.

    The feature '{feat_name}' has {total_specs} API specs across {len(split_candidates)} namespace groups,
    which is too large to document in a single page.

    Candidate sub-groups (based on namespace analysis):
    {json.dumps(groups_summary, indent=2)}

    Decide: should this feature be SPLIT into separate documentation pages per group,
    or kept as a SINGLE document?

    Decision rules:
    - SPLIT: if each group represents a distinct component that app developers would use
      independently
    - SINGLE: if the groups are tightly coupled and must be explained together

    Reply ONLY with a raw JSON object (no markdown):
    For SPLIT:
    {{
      "decision": "split",
      "reason": "1-sentence explanation",
      "children": [
        {{"feature": "group-slug", "display_name": "GroupDisplayName"}},
        ...
      ]
    }}
    For SINGLE:
    {{
      "decision": "single",
      "reason": "1-sentence explanation",
      "children": []
    }}
    """

    response = client.generate(prompt, use_think=True)
    result = extract_json_from_text(response)

    if not result or "decision" not in result:
        print(f"   [-] Failed to parse LLM response for oversized '{feat_name}'. Defaulting to SINGLE.")
        return "single", []

    decision = result.get("decision", "single")
    children = result.get("children", [])
    reason = result.get("reason", "")
    print(f"   [+] Oversized decision: {decision.upper()} — {reason}")
    if decision == "split":
        print(f"       Children: {[c.get('feature') for c in children]}")

    return decision, children


def apply_oversized_splits(feature_list, existing_taxonomy, client):
    """
    Phase A-1: oversized feature를 분할하여 feature_list에 sub-feature를 추가.
    split된 그룹(locked_groups)을 반환하여 Phase B에서 활용.

    반환: (updated_feature_list, locked_groups)
      locked_groups: [{"parent": str, "children": [str, ...]}]
    """
    feature_map_index = {f["feature"]: f for f in feature_list}
    candidates = get_oversized_candidates(feature_list, existing_taxonomy)
    locked_groups = []
    new_entries = []

    if not candidates:
        return feature_list, locked_groups

    print(f"\n>> {len(candidates)} oversized feature(s) require split/single decision.")

    for feat in candidates:
        feat_name = feat.get("feature", "")
        split_candidates = feat.get("split_candidates", [])
        print(f"\n -> Reviewing oversized feature '{feat_name}' "
              f"({feat.get('total_spec_count', 0)} specs, "
              f"{len(split_candidates)} candidate groups)...")

        decision, children = review_oversized_feature(feat, client)

        if decision == "split":
            child_ids = []
            all_child_apis = set()
            # split_candidates group_name → apis 역매핑 (순서 독립적 매칭용)
            candidate_by_slug = {c["group_name"]: c["apis"] for c in split_candidates}
            for i, child in enumerate(children):
                child_id = child.get("feature", "")
                if not child_id or child_id in feature_map_index:
                    continue
                # group_name slug 기반 매칭 우선, fallback은 순서 기반
                child_apis = (
                    candidate_by_slug.get(child_id)
                    or candidate_by_slug.get(child.get("display_name", "").lower().replace(" ", "-"))
                    or (split_candidates[i]["apis"] if i < len(split_candidates) else [])
                )
                all_child_apis.update(child_apis)
                new_entry = {
                    "feature": child_id,
                    "display_name": child.get("display_name", child_id),
                    "packages": feat.get("packages", []),
                    "api_tiers": feat.get("api_tiers", []),
                    "apis": child_apis,
                    "cross_package_links": [],
                    "ambiguous": False,
                    "_taxonomy_split": True,
                    "_split_parent": feat_name,
                }
                new_entries.append(new_entry)
                feature_map_index[child_id] = new_entry
                child_ids.append(child_id)
                print(f"   [+] Sub-feature added: '{child_id}' ({len(child_apis)} APIs)")

            if child_ids:
                # 부모 A의 apis에서 children이 가져간 APIs 제거 (overview만 유지)
                original_count = len(feat.get("apis", []))
                feat["apis"] = [a for a in feat.get("apis", []) if a not in all_child_apis]
                # _split_root: True — stage_a에서 ambiguous 분류 대상(target_candidates)에서 제외
                feat["_split_root"] = True
                print(f"   [+] Parent '{feat_name}' overview APIs: "
                      f"{original_count} → {len(feat['apis'])} (children took {len(all_child_apis)})")
                locked_groups.append({"parent": feat_name, "children": child_ids})
        else:
            # SINGLE: feature_map에서 oversized_single 마킹
            feat["oversized_single"] = True
            print(f"   [~] '{feat_name}': oversized_single — kept as single doc")

    feature_list = list(feature_map_index.values())
    return feature_list, locked_groups


# ─────────────────────────────────────────────────────────────────────────────
# Phase A-2: 소규모 Feature 통합
# ─────────────────────────────────────────────────────────────────────────────

def apply_small_feature_merges(feature_list, all_compounds_index, min_specs, client):
    """
    Phase A-2: spec_count < min_specs인 소규모 feature를 LLM 판단으로 통합.
    suppress_doc + merge_into 설정.

    반환: updated_feature_list
    """
    if min_specs <= 0:
        print(">> Small feature merge disabled (min_specs_for_standalone = 0).")
        return feature_list

    feature_map_index = {f["feature"]: f for f in feature_list}
    stable_features = [
        f for f in feature_list
        if not f.get("suppress_doc") and not f.get("ambiguous")
        and not f.get("feature", "").endswith(".autogen")
        and not f.get("_taxonomy_split")   # split 자식은 locked_group 제약 대상, merge 금지
        and not f.get("_split_root")       # split 부모는 overview 페이지, merge 대상 아님
    ]

    small_feats = []
    stable_feats = []
    for feat in stable_features:
        spec_count = count_feature_specs(feat, all_compounds_index)
        if spec_count < min_specs:
            small_feats.append(feat)
        else:
            stable_feats.append(feat)

    if not small_feats:
        print(">> No small features found for merge evaluation.")
        return feature_list

    print(f"\n>> {len(small_feats)} small feature(s) (< {min_specs} specs) evaluated for merge.")

    stable_ids = [f["feature"] for f in stable_feats]
    small_summary = [
        {
            "feature_id": f["feature"],
            "display_name": f.get("display_name", f["feature"]),
            "brief": f.get("description", ""),
            "api_count": count_feature_specs(f, all_compounds_index),
        }
        for f in small_feats
    ]

    prompt = f"""
    You are a C++ framework documentation architect for the Samsung DALi UI framework.

    The following features are too small (few APIs) to warrant standalone documentation pages.
    Decide whether each should be merged into an existing larger feature or kept as-is.

    Small features to evaluate:
    {json.dumps(small_summary, indent=2)}

    Available merge targets (existing stable features):
    {json.dumps(stable_ids, indent=2)}

    Rules:
    - MERGE: if the small feature is conceptually a sub-part of an existing stable feature
    - KEEP: if the small feature is a standalone concept with no natural parent

    Reply ONLY with a raw JSON array (no markdown):
    [
      {{"action": "merge", "source": "small-feat-a", "into": "larger-feat-x"}},
      {{"action": "keep", "feature": "small-feat-b"}}
    ]
    """

    response = client.generate(prompt, use_think=True)
    result = extract_json_from_text(response)

    if not result or not isinstance(result, list):
        print("   [-] Failed to parse merge decisions. Keeping all small features as-is.")
        return feature_list

    merged_count = 0
    for decision in result:
        action = decision.get("action", "keep")
        if action != "merge":
            continue
        source_id = decision.get("source", "")
        target_id = decision.get("into", "")

        # 유효성 검증
        if source_id not in feature_map_index:
            print(f"   [!] Merge source '{source_id}' not found — skipping.")
            continue
        if target_id not in feature_map_index:
            print(f"   [!] Merge target '{target_id}' not found — skipping.")
            continue
        if feature_map_index[target_id].get("suppress_doc"):
            print(f"   [!] Merge target '{target_id}' is suppressed — skipping.")
            continue
        if source_id == target_id:
            print(f"   [!] Circular merge '{source_id}' → '{target_id}' — skipping.")
            continue

        feature_map_index[source_id]["suppress_doc"] = True
        feature_map_index[source_id]["merge_into"] = target_id
        # merge_mode:full 설정 — stage_c가 B/C를 inherited_context(brief)가 아닌
        # 완전 스펙으로 문서화하도록, 그리고 merge_sources 이중 처리를 방지한다.
        feature_map_index[source_id]["merge_mode"] = "full"

        # merge_mode:full 동작: source apis를 target apis에 물리 병합
        # (feature_clusterer의 merge_mode:full 처리와 동일한 방식)
        target_feat = feature_map_index[target_id]
        source_apis = feature_map_index[source_id].get("apis", [])
        existing_apis = set(target_feat.get("apis", []))
        new_apis = [a for a in source_apis if a not in existing_apis]
        if new_apis:
            target_feat["apis"] = target_feat.get("apis", []) + new_apis

        merged_count += 1
        print(f"   [Merge] '{source_id}' → '{target_id}' "
              f"(merge_mode:full, +{len(new_apis)} APIs merged into target)")

    print(f">> Merged {merged_count} small feature(s).")
    return list(feature_map_index.values())


# ─────────────────────────────────────────────────────────────────────────────
# Phase B: 전체 일괄 Tree 설계
# ─────────────────────────────────────────────────────────────────────────────

def build_active_feature_summary(feature_list, all_compounds_index):
    """LLM에 전달할 active feature 요약 목록 생성."""
    summaries = []
    for feat in feature_list:
        if feat.get("suppress_doc"):
            continue
        if feat.get("feature", "").endswith(".autogen"):
            continue
        summaries.append({
            "feature_id": feat["feature"],
            "display_name": feat.get("display_name", feat["feature"]),
            "brief": feat.get("description", feat.get("base_class", "")),
            "api_count": count_feature_specs(feat, all_compounds_index),
        })
    return summaries


def design_tree_full(feature_summaries, locked_groups, client):
    """
    Full 모드: 전체 feature 목록을 한 번에 LLM에 전달하여 tree 설계.
    """
    locked_hint = ""
    if locked_groups:
        locked_hint = f"""
LOCKED GROUPS (split decisions already made — do NOT reassign these):
{json.dumps(locked_groups, indent=2)}
- The parent of each locked group must remain a root-level feature (cannot be a child of anything).
- The children of each locked group cannot be assigned to a different parent.
"""

    prompt = f"""
You are a C++ framework documentation architect for the Samsung DALi UI framework.

Design a documentation tree structure for the following features.
Group features into parent-child relationships ONLY when there is a clear conceptual
ownership (e.g., a base class and its specializations, a container and its elements).
When in doubt, keep features as flat standalone pages. Prefer fewer tree relationships
over forcing artificial groupings.

Feature list:
{json.dumps(feature_summaries, indent=2)}
{locked_hint}
CONSTRAINTS:
1. Tree depth must not exceed 2 levels. Grandchildren are NOT allowed.
   If a child feature has sub-components, flatten them as siblings under the same root.
2. children must only contain feature_ids from the provided feature list above.
3. A feature can appear as a child of at most one parent.
4. Locked group parents must not appear as children of any other feature.
5. Locked group children must remain under their designated parent.

For each feature, decide:
- "tree": this feature is a logical parent that owns the listed child sub-components
- "flat": this feature is an independent concept with no natural parent (DEFAULT)

Features not mentioned in the response will be treated as "flat".
Only emit "tree" entries when the grouping is semantically clear and beneficial to readers.

Reply ONLY with a raw JSON array (no markdown):
[
  {{"feature_id": "view", "tree_decision": "tree", "children": ["image-view", "label"]}},
  {{"feature_id": "image-view", "tree_decision": "flat", "children": []}}
]
"""

    response = client.generate(prompt, use_think=True)
    result = extract_json_from_text(response)
    if not result or not isinstance(result, list):
        print("   [-] Failed to parse tree design response.")
        return []
    return result


def design_tree_incremental(feature_summaries, locked_groups, existing_taxonomy,
                             new_features, removed_features, client):
    """
    Incremental 모드: 기존 taxonomy를 컨텍스트로 제공하고 변경사항만 LLM에 요청.
    """
    locked_hint = ""
    if locked_groups:
        locked_hint = f"""
LOCKED GROUPS:
{json.dumps(locked_groups, indent=2)}
"""

    # 기존 taxonomy 요약 (display_name 제외 최소 정보)
    existing_summary = [
        {
            "feature_id": k,
            "tree_decision": v.get("tree_decision", "flat"),
            "children": v.get("children", []),
            "parent": v.get("parent"),
        }
        for k, v in existing_taxonomy.items()
        if not v.get("suppress_doc")
    ]

    prompt = f"""
You are a C++ framework documentation architect for the Samsung DALi UI framework.

Below is the EXISTING tree structure. Update it minimally to reflect the listed changes.
Keep unchanged features exactly as they are.

EXISTING TREE:
{json.dumps(existing_summary, indent=2)}

CHANGES:
- Added features: {json.dumps([s for s in feature_summaries if s["feature_id"] in new_features], indent=2)}
- Removed feature IDs: {json.dumps(list(removed_features), indent=2)}
{locked_hint}
CONSTRAINTS:
1. Tree depth must not exceed 2 levels. No grandchildren.
2. children must only contain feature_ids from the current active feature list.
3. Locked group parents must not appear as children of any other feature.
4. Only group features into tree-leaf relationships when there is a clear conceptual
   ownership between them. Prefer flat for new features unless a natural parent exists.

Return ONLY the entries that need to change (new, modified, or affected by removal).
Unchanged entries should be omitted from the response.

Reply ONLY with a raw JSON array (no markdown):
[
  {{"feature_id": "...", "tree_decision": "tree/flat", "children": [...]}}
]
"""

    response = client.generate(prompt, use_think=True)
    result = extract_json_from_text(response)
    if not result or not isinstance(result, list):
        print("   [-] Failed to parse incremental tree response.")
        return []
    return result


def validate_and_build_taxonomy(tree_decisions, feature_summaries,
                                 locked_groups, existing_taxonomy=None):
    """
    LLM 응답을 검증하고 taxonomy dict를 구축.

    검증 항목:
    1. children의 feature_id가 active feature 목록에 없음 → 제거
    2. 3뎁스 탐지 → grandchildren을 parent 레벨로 flatten
    3. 한 feature가 여러 parent에 등재 → 첫 등장 parent만 유지
    4. tree인데 children 없음 → flat 다운그레이드
    5. locked 그룹 위반 → 복원
    """
    feature_id_set = {s["feature_id"] for s in feature_summaries}
    feature_display = {s["feature_id"]: s.get("display_name", s["feature_id"])
                       for s in feature_summaries}

    # locked 그룹 정보
    locked_parents = set()
    locked_child_to_parent = {}
    for grp in locked_groups:
        parent_id = grp["parent"]
        locked_parents.add(parent_id)
        for child_id in grp["children"]:
            locked_child_to_parent[child_id] = parent_id

    # tree_decisions를 dict로 변환
    decisions = {}
    for entry in tree_decisions:
        fid = entry.get("feature_id", "")
        if not fid or fid not in feature_id_set:
            continue
        decisions[fid] = {
            "tree_decision": entry.get("tree_decision", "flat"),
            "children": [c for c in entry.get("children", []) if c in feature_id_set and c != fid],
        }

    # incremental 모드: 기존 taxonomy 항목을 base로 사용
    if existing_taxonomy:
        for fid, entry in existing_taxonomy.items():
            if fid not in decisions and fid in feature_id_set:
                decisions[fid] = {
                    "tree_decision": entry.get("tree_decision", "flat"),
                    "children": [c for c in entry.get("children", []) if c in feature_id_set],
                }

    # 검증 1: children 중복 parent 탐지 (첫 등장 우선)
    assigned_parent = {}
    for fid, dec in decisions.items():
        valid_children = []
        for child_id in dec["children"]:
            if child_id in assigned_parent:
                print(f"   [Validate] '{child_id}' already assigned to '{assigned_parent[child_id]}' "
                      f"— removing from '{fid}'")
                continue
            assigned_parent[child_id] = fid
            valid_children.append(child_id)
        dec["children"] = valid_children

    # 검증 2: locked 그룹 위반 복원
    for grp in locked_groups:
        parent_id = grp["parent"]
        # locked parent가 누군가의 child가 되면 제거
        if parent_id in assigned_parent:
            offending_parent = assigned_parent[parent_id]
            if offending_parent in decisions:
                decisions[offending_parent]["children"] = [
                    c for c in decisions[offending_parent]["children"] if c != parent_id
                ]
            del assigned_parent[parent_id]
            print(f"   [Locked] '{parent_id}' removed from children of '{offending_parent}' (locked parent)")
        # locked children을 올바른 parent 아래 배치
        locked_children = grp["children"]
        if parent_id not in decisions:
            decisions[parent_id] = {"tree_decision": "tree", "children": []}
        for child_id in locked_children:
            # 잘못된 parent의 children 목록에서 제거
            if child_id in assigned_parent and assigned_parent[child_id] != parent_id:
                wrong_parent = assigned_parent[child_id]
                if wrong_parent in decisions:
                    decisions[wrong_parent]["children"] = [
                        c for c in decisions[wrong_parent]["children"] if c != child_id
                    ]
                    print(f"   [Locked] '{child_id}' removed from '{wrong_parent}' children "
                          f"— belongs under locked parent '{parent_id}'")
            if child_id not in decisions[parent_id]["children"]:
                decisions[parent_id]["children"].append(child_id)
            assigned_parent[child_id] = parent_id

    # 검증 3: 3뎁스 탐지 — child가 다시 children을 가지면 flatten
    for fid, dec in list(decisions.items()):
        if dec["tree_decision"] != "tree":
            continue
        grandchildren_to_adopt = []
        for child_id in list(dec["children"]):
            child_dec = decisions.get(child_id, {})
            if child_dec.get("children"):
                print(f"   [Flatten] '{child_id}' has grandchildren under '{fid}' — flattening")
                grandchildren_to_adopt.extend(child_dec["children"])
                child_dec["children"] = []
                child_dec["tree_decision"] = "flat"
        for gc in grandchildren_to_adopt:
            if gc not in dec["children"]:
                dec["children"].append(gc)
                assigned_parent[gc] = fid

    # 검증 4: tree인데 children 없음 → flat
    for fid, dec in decisions.items():
        if dec["tree_decision"] == "tree" and not dec["children"]:
            dec["tree_decision"] = "flat"
            print(f"   [Fix] '{fid}': tree+no-children → flat")

    # taxonomy dict 구축
    taxonomy = {}
    for fid, dec in decisions.items():
        tree_decision = dec["tree_decision"]
        children = dec["children"]
        parent = assigned_parent.get(fid, None)

        # tree_decision 재결정
        if parent and tree_decision != "tree":
            tree_decision = "leaf"
        elif not parent and tree_decision == "leaf":
            tree_decision = "flat"

        taxonomy[fid] = {
            "display_name": feature_display.get(fid, fid),
            "parent": parent,
            "children": children,
            "doc_file": f"{fid}.md",
            "tree_decision": tree_decision,
            "decision_reason": (
                f"Child of {parent}" if parent
                else ("Has child components" if children else "Standalone feature")
            ),
        }

    # feature_summaries에 있지만 decisions에 없는 feature → flat으로 추가
    for fid in feature_id_set:
        if fid not in taxonomy:
            parent = assigned_parent.get(fid)
            taxonomy[fid] = {
                "display_name": feature_display.get(fid, fid),
                "parent": parent,
                "children": [],
                "doc_file": f"{fid}.md",
                "tree_decision": "leaf" if parent else "flat",
                "decision_reason": f"Child of {parent}" if parent else "Standalone feature",
            }

    return taxonomy


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true",
                        help="기존 taxonomy 무시하고 전체 재검토")
    parser.add_argument("--mode", choices=["full", "update"], default="full",
                        help="실행 모드 (full: 전체 재생성, update: 증분)")
    args = parser.parse_args()

    # --full 플래그는 --mode full과 동일
    is_full = args.full or args.mode == "full"

    print("=================================================================")
    print(" Phase 1.5: Feature Taxonomy Reviewer                           ")
    print("=================================================================")

    feature_list = load_json(FEATURE_MAP_PATH)
    if not feature_list:
        print("Error: feature_map.json not found. Run Phase 1 (feature_clusterer.py) first.")
        return

    # .autogen 항목 제외
    autogen_before = len(feature_list)
    feature_list = [f for f in feature_list if not f.get("feature", "").endswith(".autogen")]
    filtered = autogen_before - len(feature_list)
    if filtered:
        print(f">> [AutogenFilter] Excluded {filtered} .autogen feature(s).")

    doc_config = load_doc_config()
    min_specs = doc_config.get("token_overflow", {}).get("min_specs_for_standalone", 0)

    # 기존 taxonomy 로드
    existing_taxonomy = {}
    if not is_full and TAXONOMY_PATH.exists():
        existing_taxonomy = load_json(TAXONOMY_PATH) or {}
        print(f">> Loaded existing taxonomy: {len(existing_taxonomy)} entries.")
    else:
        print(">> Full mode: starting fresh taxonomy.")

    # 전체 compound 인덱스 구축 (spec count 계산용)
    print(">> Building compound index from Doxygen data...")
    all_compounds_index = build_all_compounds_index()
    print(f"   Found {len(all_compounds_index)} compounds.")

    client = LLMClient()

    # ── Phase A-1: Oversized Feature 분할 ────────────────────────────────────
    print("\n>> Phase A-1: Oversized feature split evaluation...")
    feature_list, locked_groups = apply_oversized_splits(
        feature_list, existing_taxonomy, client
    )
    if locked_groups:
        print(f">> {len(locked_groups)} locked group(s) from split decisions:")
        for grp in locked_groups:
            print(f"   {grp['parent']} → {grp['children']}")

    # ── Phase A-2: 소규모 Feature 통합 ──────────────────────────────────────
    print("\n>> Phase A-2: Small feature merge evaluation...")
    feature_list = apply_small_feature_merges(
        feature_list, all_compounds_index, min_specs, client
    )

    # ── A-3: feature_map.json 저장 ───────────────────────────────────────────
    # sets를 list로 변환 (JSON 직렬화)
    for feat in feature_list:
        for key in ("packages", "api_tiers", "cross_package_links"):
            if isinstance(feat.get(key), set):
                feat[key] = list(feat[key])

    FEATURE_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(FEATURE_MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(feature_list, f, indent=2, ensure_ascii=False)
    print(f"\n>> feature_map.json updated ({len(feature_list)} features).")

    # ── Phase B: 전체 일괄 Tree 설계 ─────────────────────────────────────────
    print("\n>> Phase B: Tree design (single LLM call)...")
    feature_summaries = build_active_feature_summary(feature_list, all_compounds_index)
    active_ids = {s["feature_id"] for s in feature_summaries}
    print(f"   Active features: {len(feature_summaries)}")

    if is_full or not existing_taxonomy:
        print("   Mode: FULL — designing complete tree from scratch.")
        tree_decisions = design_tree_full(feature_summaries, locked_groups, client)
        taxonomy = validate_and_build_taxonomy(
            tree_decisions, feature_summaries, locked_groups
        )
    else:
        # 변경 감지
        existing_ids = set(existing_taxonomy.keys())
        new_features = active_ids - existing_ids
        removed_features = existing_ids - active_ids
        # split으로 생성된 feature도 신규로 처리
        split_ids = {f["feature"] for f in feature_list if f.get("_taxonomy_split")}
        new_features |= split_ids

        print(f"   Mode: INCREMENTAL — new: {len(new_features)}, "
              f"removed: {len(removed_features)}")

        if not new_features and not removed_features:
            print("   No changes detected. Reusing existing taxonomy.")
            taxonomy = existing_taxonomy
        else:
            tree_decisions = design_tree_incremental(
                feature_summaries, locked_groups, existing_taxonomy,
                new_features, removed_features, client
            )
            taxonomy = validate_and_build_taxonomy(
                tree_decisions, feature_summaries, locked_groups, existing_taxonomy
            )

    # .autogen 잔존 항목 정리
    stale_autogen = [k for k in taxonomy if k.endswith(".autogen")]
    for k in stale_autogen:
        del taxonomy[k]
    if stale_autogen:
        print(f">> [AutogenFilter] Removed {len(stale_autogen)} stale .autogen entry/entries.")

    # 삭제된 feature의 taxonomy 항목 제거
    for fid in list(taxonomy.keys()):
        feat_in_map = any(f["feature"] == fid for f in feature_list)
        if not feat_in_map and not taxonomy[fid].get("parent"):
            # suppress된 feature도 taxonomy에서 제거
            pass  # suppress된 것은 taxonomy에 없어야 함
        if not feat_in_map:
            del taxonomy[fid]

    # 영속화
    TAXONOMY_DIR.mkdir(parents=True, exist_ok=True)
    with open(TAXONOMY_PATH, "w", encoding="utf-8") as f:
        json.dump(taxonomy, f, indent=2, ensure_ascii=False)

    print(f"\n=================================================================")
    print(f" Phase 1.5 Complete! Taxonomy saved to: {TAXONOMY_PATH}")
    print(f" Total entries: {len(taxonomy)}")
    print("=================================================================")


if __name__ == "__main__":
    main()
