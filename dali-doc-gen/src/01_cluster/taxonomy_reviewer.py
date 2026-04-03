"""
taxonomy_reviewer.py — Phase 1.5: Feature Taxonomy 설계 (LLM Think 모델)

역할:
  - feature_map_classified.json + parsed_doxygen의 상속 관계(derived_classes)를 분석
  - LLM(Think)이 각 상속 계층의 Tree 문서 구조 생성 여부를 판단
  - 결과를 cache/feature_taxonomy/feature_taxonomy.json에 영속화
  - 증분 모드: 기존 taxonomy 로드 후 신규/변경 클래스만 LLM 재검토

출력 schema:
  {
    "view": {
      "display_name": "View (Base UI Object)",
      "parent": null,
      "children": ["image-view", "label", "scroll-view"],
      "doc_file": "view.md",
      "tree_decision": "tree",         # "tree" | "flat"
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
FEATURE_MAP_PATH = CACHE_DIR / "feature_map" / "feature_map.json"   # Phase 1 출력
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
    match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        text_to_parse = match.group(1)
    else:
        start = text.find('{')
        end = text.rfind('}') + 1
        text_to_parse = text[start:end] if start != -1 and end > 0 else text
    try:
        return json.loads(text_to_parse)
    except Exception as e:
        print(f"   [JSON Parse Error] {e}")
        return None


def sanitize_children(parent_key, children):
    """
    LLM 응답의 children 목록에서 자기 참조 및 중복을 제거합니다.
    sanitize 후 children이 비어 있으면 호출 측에서 decision을 'flat'으로 다운그레이드해야 합니다.
    """
    seen = set()
    valid = []
    for c in children:
        feature_key = c.get("feature", "").strip()
        if not feature_key:
            continue
        if feature_key == parent_key:       # 자기 참조 제거
            print(f"   [Sanitize] Removed self-referencing child '{feature_key}' from '{parent_key}'")
            continue
        if feature_key in seen:             # 중복 제거
            print(f"   [Sanitize] Removed duplicate child '{feature_key}' from '{parent_key}'")
            continue
        seen.add(feature_key)
        valid.append(c)
    return valid


def class_exists_in_doxygen(display_name):
    """
    display_name(예: 'AnimatedImageView')으로 Doxygen에 실제 클래스가
    존재하는지 확인합니다. exact match(소문자, 공백/하이픈 제거)만 허용.
    """
    search_name = display_name.lower().replace("-", "").replace(" ", "")
    for pkg_json in PARSED_DOXYGEN_DIR.glob("*.json"):
        data = load_json(pkg_json)
        if not data:
            continue
        for comp in data.get("compounds", []):
            simple_name = comp.get("name", "").split("::")[-1].lower()
            if simple_name == search_name:
                return True
    return False


def build_inheritance_map():
    """
    parsed_doxygen/*.json에서 derived_classes 정보를 수집하여
    {class_name: [derived_class1, derived_class2, ...]} 형태로 반환.
    """
    inheritance_map = {}
    for pkg_json in PARSED_DOXYGEN_DIR.glob("*.json"):
        data = load_json(pkg_json)
        if not data:
            continue
        for comp in data.get("compounds", []):
            if not isinstance(comp, dict):
                continue
            name = comp.get("name", "")
            derived = comp.get("derived_classes", [])
            if derived:
                inheritance_map[name] = derived
    return inheritance_map


def get_candidates_for_review(feature_list, existing_taxonomy, inheritance_map):
    """
    Tree 구조 검토가 필요한 Feature 후보를 선별합니다.
    - force_tree_review: true인 Feature
    - derived_classes가 3개 이상인 Feature
    - 기존 taxonomy에 없는(신규) Feature
    """
    candidates = []
    existing_keys = set(existing_taxonomy.keys())

    for feat in feature_list:
        feat_name = feat.get("feature", "")
        base_class = feat.get("base_class", "")
        force_review = feat.get("force_tree_review", False)

        # 상속 관계 수집
        derived = inheritance_map.get(base_class, [])

        # 검토 필요 여부 판단
        needs_review = (
            force_review or
            len(derived) >= 3 or
            feat_name not in existing_keys
        )

        if needs_review:
            candidates.append({
                "feature": feat_name,
                "display_name": feat.get("display_name", feat_name),
                "base_class": base_class,
                "derived_classes": derived,
                "apis_sample": feat.get("apis", [])[:10],
                "force_review": force_review
            })

    return candidates


def get_oversized_candidates(feature_list, existing_taxonomy):
    """
    feature_clusterer가 마킹한 oversized: true feature 중
    split_candidates가 3개 이상인 것만 LLM 판단 대상으로 반환한다.
    이미 taxonomy에 등록된(tree/leaf/oversized_single) feature는 재검토하지 않는다.
    """
    candidates = []
    for feat in feature_list:
        if not feat.get("oversized"):
            continue
        feat_name = feat.get("feature", "")
        split_candidates = feat.get("split_candidates", [])
        if len(split_candidates) < 3:
            # 그룹이 3개 미만 → LLM 판단 없이 바로 oversized_single로 처리
            continue
        # 이미 taxonomy에 등록되어 있고 oversized 관련 결정이 있으면 스킵
        existing = existing_taxonomy.get(feat_name, {})
        if existing.get("tree_decision") in ("tree", "flat", "leaf") or existing.get("oversized_single"):
            continue
        candidates.append(feat)
    return candidates


def review_oversized_feature(feat, client):
    """
    oversized feature의 split_candidates를 LLM에게 제시하고
    각 그룹이 독립적인 개발자 시나리오를 갖는지 판단받는다.

    반환: ("split", [children_list]) 또는 ("single", [])
    """
    feat_name = feat.get("feature", "")
    split_candidates = feat.get("split_candidates", [])
    total_specs = feat.get("total_spec_count", 0)

    # 각 그룹의 대표 클래스 이름 샘플 (최대 5개)
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
    or kept as a SINGLE document (using multi-pass generation)?

    Decision rules:
    - SPLIT: if each group represents a distinct component that app developers would use
      independently (e.g., a developer uses only AddonManager without needing AddonEvent)
    - SINGLE: if the groups are tightly coupled and must be explained together
      (e.g., all groups are always used together in the same workflow)

    Reply ONLY with a raw JSON object (no markdown):
    For SPLIT:
    {{
      "decision": "split",
      "reason": "1-sentence explanation",
      "children": [
        {{"feature": "group-slug", "display_name": "GroupDisplayName", "doc_file": "group-slug.md"}},
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

    if decision == "split":
        children = sanitize_children(feat_name, children)
        if not children:
            print(f"   [Sanitize] No valid children after sanitization — downgrading '{feat_name}' to SINGLE.")
            decision = "single"

    reason = result.get("reason", "")
    print(f"   [+] Oversized decision: {decision.upper()} — {reason}")
    if decision == "split":
        print(f"       Children: {[c.get('feature') for c in children]}")

    return decision, children


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true",
                        help="기존 taxonomy 무시하고 전체 재검토 (최초 1회 또는 taxonomy 초기화 시)")
    args = parser.parse_args()

    print("=================================================================")
    print(" Phase 1.5: Feature Taxonomy Reviewer                           ")
    print("=================================================================")

    feature_list = load_json(FEATURE_MAP_PATH)
    if not feature_list:
        print("Error: feature_map.json not found. Run Phase 1 (feature_clusterer.py) first.")
        return

    # 기존 taxonomy 로드 (증분 업데이트용)
    existing_taxonomy = {}
    if not args.full and TAXONOMY_PATH.exists():
        existing_taxonomy = load_json(TAXONOMY_PATH) or {}
        print(f">> Loaded existing taxonomy: {len(existing_taxonomy)} entries.")
    else:
        print(">> Full review mode: starting fresh taxonomy.")

    # 상속 관계 맵 구축
    print(">> Building inheritance map from Doxygen data...")
    inheritance_map = build_inheritance_map()
    print(f"   Found {len(inheritance_map)} classes with derived classes.")

    # 검토 후보 선별
    candidates = get_candidates_for_review(feature_list, existing_taxonomy, inheritance_map)
    print(f">> {len(candidates)} feature(s) require taxonomy review.")

    if not candidates:
        print(">> No new features to review. Existing taxonomy is up-to-date.")
        # taxonomy 파일이 없으면 기존 flat 정보로 초기화
        if not TAXONOMY_PATH.exists():
            _write_default_taxonomy(feature_list, existing_taxonomy)

    client = LLMClient() if candidates else None

    for cand in candidates:
        feat_name = cand["feature"]
        base_class = cand["base_class"]
        derived = cand["derived_classes"]

        print(f"\n -> Reviewing taxonomy for '{feat_name}' "
              f"(base: {base_class}, derived count: {len(derived)})...")

        prompt = f"""
        You are a C++ framework documentation architect for the Samsung DALi UI framework.
        
        Analyze whether the following class hierarchy warrants a TREE document structure
        (parent page + individual child pages) or a FLAT document structure (single page).

        Feature: '{feat_name}'
        Base Class: '{base_class}'
        Derived Classes: {json.dumps(derived, indent=2)}
        Sample APIs: {json.dumps(cand['apis_sample'], indent=2)}

        Decision rules:
        - TREE: if there are 3+ derived classes AND each has distinct app-developer use cases
        - FLAT: if derived classes are minor variants, internal, or not directly used by app developers

        For TREE decisions, list which derived classes should become child documents.
        Use feature name slugs (lowercase-hyphenated, e.g. "image-view", "scroll-view").

        IMPORTANT: Each child `feature` slug in the `children` array must be UNIQUE and must
        NOT equal the parent feature name '{feat_name}'. Use lowercase-hyphenated slugs that
        describe what makes each child component distinct (e.g. "animated-image-view", not
        "{feat_name}" again). If you cannot determine distinct child slugs, use decision "flat".

        Reply ONLY with a raw JSON object (no markdown):
        {{
          "feature": "{feat_name}",
          "decision": "tree",
          "reason": "1-sentence explanation",
          "parent_doc_file": "{feat_name}.md",
          "children": [
            {{"feature": "image-view", "display_name": "ImageView", "doc_file": "image-view.md"}},
            {{"feature": "label", "display_name": "Label", "doc_file": "label.md"}}
          ]
        }}
        OR for flat:
        {{
          "feature": "{feat_name}",
          "decision": "flat",
          "reason": "1-sentence explanation",
          "parent_doc_file": "{feat_name}.md",
          "children": []
        }}
        """

        response = client.generate(prompt, use_think=True)
        result = extract_json_from_text(response)

        if result and "decision" in result:
            decision = result.get("decision", "flat")
            reason = result.get("reason", "")
            children = result.get("children", [])

            # children 후처리: 자기 참조 및 중복 제거
            children = sanitize_children(feat_name, children)
            # sanitize 후 children이 비어 있으면 tree → flat 다운그레이드
            if decision == "tree" and not children:
                print(f"   [Sanitize] No valid children remain after sanitization — downgrading to FLAT.")
                decision = "flat"
                reason = reason + " (downgraded to flat: no valid unique children after sanitization)"

            print(f"   [+] Decision: {decision.upper()} — {reason}")
            if children:
                print(f"       Children: {[c.get('feature') for c in children]}")

            # Doxygen 존재 여부로 child 검증 (없으면 제외)
            verified_children = []
            for c in children:
                c_display = c.get("display_name", c.get("feature", ""))
                if class_exists_in_doxygen(c_display):
                    verified_children.append(c)
                else:
                    print(f"   [Doxygen Check] Rejected child '{c.get('feature')}' "
                          f"({c_display}): not found in Doxygen — skipping.")
            # verified_children이 비어 있으면 tree → flat 다운그레이드
            if decision == "tree" and not verified_children:
                print(f"   [Doxygen Check] No verified children remain — downgrading '{feat_name}' to FLAT.")
                decision = "flat"
                reason = reason + " (downgraded to flat: no Doxygen-verified children)"
            children = verified_children

            # taxonomy에 기록
            existing_taxonomy[feat_name] = {
                "display_name": cand.get("display_name", feat_name),
                "base_class": base_class,
                "parent": None,
                "children": [c.get("feature") for c in children],
                "doc_file": result.get("parent_doc_file", f"{feat_name}.md"),
                "tree_decision": decision,
                "decision_reason": reason
            }
            # 자식 항목도 taxonomy에 등록
            # 이미 존재하는 항목은 parent 필드만 업데이트 (독립 feature로 먼저 등록된 경우 불일치 수정)
            for child in children:
                child_key = child.get("feature", "")
                if not child_key:
                    continue
                if child_key in existing_taxonomy:
                    if existing_taxonomy[child_key].get("parent") != feat_name:
                        print(f"   [Taxonomy Fix] '{child_key}' parent updated: "
                              f"{existing_taxonomy[child_key].get('parent')!r} → {feat_name!r}")
                        existing_taxonomy[child_key]["parent"] = feat_name
                else:
                    existing_taxonomy[child_key] = {
                        "display_name": child.get("display_name", child_key),
                        "base_class": "",
                        "parent": feat_name,
                        "children": [],
                        "doc_file": child.get("doc_file", f"{child_key}.md"),
                        "tree_decision": "leaf",
                        "decision_reason": f"Child of {feat_name}"
                    }
        else:
            print(f"   [-] Failed to parse LLM response. Defaulting to FLAT.")
            existing_taxonomy[feat_name] = {
                "display_name": cand.get("display_name", feat_name),
                "base_class": base_class,
                "parent": None,
                "children": [],
                "doc_file": f"{feat_name}.md",
                "tree_decision": "flat",
                "decision_reason": "LLM parse failure — defaulted to flat"
            }

    # ── Oversized Feature 독립성 판단 ─────────────────────────────────────────
    oversized_candidates = get_oversized_candidates(feature_list, existing_taxonomy)
    if oversized_candidates:
        print(f"\n>> {len(oversized_candidates)} oversized feature(s) require split/single decision.")
        if not client:
            client = LLMClient()
        for feat in oversized_candidates:
            feat_name = feat.get("feature", "")
            print(f"\n -> Reviewing oversized feature '{feat_name}' "
                  f"({feat.get('total_spec_count', 0)} specs, "
                  f"{len(feat.get('split_candidates', []))} candidate groups)...")

            decision, children = review_oversized_feature(feat, client)

            if decision == "split":
                existing_taxonomy[feat_name] = {
                    "display_name": feat.get("display_name", feat_name),
                    "parent": None,
                    "children": [c.get("feature") for c in children],
                    "doc_file": f"{feat_name}.md",
                    "tree_decision": "tree",
                    "decision_reason": f"Oversized ({feat.get('total_spec_count')} specs) — split into sub-features"
                }
                for child in children:
                    child_key = child.get("feature", "")
                    if not child_key:
                        continue
                    if child_key not in existing_taxonomy:
                        existing_taxonomy[child_key] = {
                            "display_name": child.get("display_name", child_key),
                            "parent": feat_name,
                            "children": [],
                            "doc_file": child.get("doc_file", f"{child_key}.md"),
                            "tree_decision": "leaf",
                            "decision_reason": f"Sub-feature of oversized '{feat_name}'"
                        }
                    else:
                        existing_taxonomy[child_key]["parent"] = feat_name
            else:
                # SINGLE: stage_c가 롤링 정제 모드로 처리
                existing_taxonomy[feat_name] = {
                    "display_name": feat.get("display_name", feat_name),
                    "parent": None,
                    "children": [],
                    "doc_file": f"{feat_name}.md",
                    "tree_decision": "flat",
                    "oversized_single": True,
                    "decision_reason": f"Oversized ({feat.get('total_spec_count')} specs) — kept single, rolling refinement"
                }

        # split_candidates가 3개 미만인 oversized feature는 taxonomy 미등록 상태로 남겨두면
        # stage_c의 token 기반 fallback이 자동으로 롤링 정제를 처리한다.
        # 단, taxonomy 파일에 명시적으로 oversized_single 등록 (추적 가능성 확보)
        for feat in feature_list:
            if not feat.get("oversized"):
                continue
            feat_name = feat.get("feature", "")
            if feat_name in existing_taxonomy:
                continue  # 이미 처리됨
            if len(feat.get("split_candidates", [])) < 3:
                existing_taxonomy[feat_name] = {
                    "display_name": feat.get("display_name", feat_name),
                    "parent": None,
                    "children": [],
                    "doc_file": f"{feat_name}.md",
                    "tree_decision": "flat",
                    "oversized_single": True,
                    "decision_reason": f"Oversized ({feat.get('total_spec_count')} specs) — fewer than 3 candidate groups, rolling refinement"
                }
                print(f"   [Auto] '{feat_name}': oversized_single (< 3 groups, no LLM needed)")

    # 영속화
    TAXONOMY_DIR.mkdir(parents=True, exist_ok=True)
    with open(TAXONOMY_PATH, "w", encoding="utf-8") as f:
        json.dump(existing_taxonomy, f, indent=2, ensure_ascii=False)

    print(f"\n=================================================================")
    print(f" Phase 1.5 Complete! Taxonomy saved to: {TAXONOMY_PATH}")
    print(f" Total entries: {len(existing_taxonomy)}")
    print("=================================================================")


def _write_default_taxonomy(feature_list, existing_taxonomy):
    """taxonomy 파일이 없을 때 기본 flat 구조로 초기화."""
    for feat in feature_list:
        feat_name = feat.get("feature", "")
        if feat_name and feat_name not in existing_taxonomy:
            existing_taxonomy[feat_name] = {
                "display_name": feat.get("display_name", feat_name),
                "parent": None,
                "children": [],
                "doc_file": f"{feat_name}.md",
                "tree_decision": "flat",
                "decision_reason": "Default initialization"
            }
    TAXONOMY_DIR.mkdir(parents=True, exist_ok=True)
    with open(TAXONOMY_PATH, "w", encoding="utf-8") as f:
        json.dump(existing_taxonomy, f, indent=2, ensure_ascii=False)
    print(f">> Default taxonomy initialized: {TAXONOMY_PATH}")


if __name__ == "__main__":
    main()
