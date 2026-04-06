import os
import re
import json
import yaml
import argparse
from pathlib import Path

# Important: Append module path so it can import llm_client natively
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from llm_client import LLMClient

# Path Definitions
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = PROJECT_ROOT / "cache"
CLASSIFIED_MAP_PATH = CACHE_DIR / "feature_map" / "feature_map_classified.json"
OUT_BLUEPRINTS_PATH = CACHE_DIR / "doc_blueprints" / "stage_b_blueprints.json"
TAXONOMY_PATH = CACHE_DIR / "feature_taxonomy" / "feature_taxonomy.json"
PARSED_DOXYGEN_DIR = CACHE_DIR / "parsed_doxygen"
DOC_CONFIG_PATH = PROJECT_ROOT / "config" / "doc_config.yaml"

def load_doc_config():
    if not DOC_CONFIG_PATH.exists():
        return {}
    with open(DOC_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def sample_apis(api_names, max_count=50):
    """
    Blueprint용 API 샘플링 (클래스명+메서드명 혼재 리스트 대응).

    - 클래스 수 >= max_count : 클래스 선언만 전부 반환 (메서드 제외)
    - 클래스 수 < max_count  : 모든 클래스 선언 포함 +
                               나머지 슬롯을 전체 메서드 풀에서 균등 간격으로 채움
                               (메서드가 많은 클래스가 자연스럽게 더 많이 할당됨)
    - 메서드 항목이 없는 경우 : 그대로 반환 (클래스명 전용 리스트)
    """
    name_set = set(api_names)
    # 다른 항목의 prefix인 것 = 클래스 선언 (e.g. "Dali::Actor" → "Dali::Actor::SetPos")
    class_entries = [n for n in api_names
                     if any(other.startswith(n + "::") for other in name_set)]
    method_entries = [n for n in api_names if n not in set(class_entries)]

    # 메서드 항목이 없으면 클래스명 전용 리스트 — 캡 없이 그대로 반환
    if not method_entries:
        return api_names

    num_classes = len(class_entries)

    if num_classes >= max_count:
        # Case 1: 클래스 선언만 전부 (메서드 없이)
        return class_entries

    # Case 2: 모든 클래스 + 나머지 슬롯을 메서드 풀에서 균등 간격 샘플
    remaining = max_count - num_classes
    if len(method_entries) <= remaining:
        extra = method_entries
    else:
        step = len(method_entries) / remaining
        extra = [method_entries[int(i * step)] for i in range(remaining)]

    return class_entries + extra


def load_json(path):
    if not path.exists():
        print(f"Error: Could not locate map inside '{path}'. Have you run Stage A?")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def find_child_api_names(display_name):
    """
    Taxonomy child의 display_name(예: 'ImageView')으로 Doxygen에서
    해당 클래스의 API 이름 목록을 검색해 반환합니다.
    """
    api_names = []
    packages_found = set()
    search_name = display_name.lower().replace("-", "").replace(" ", "")

    for pkg_json in PARSED_DOXYGEN_DIR.glob("*.json"):
        data = load_json(pkg_json)
        if not data:
            continue
        pkg_name = data.get("package", pkg_json.stem)
        for comp in data.get("compounds", []):
            comp_name = comp.get("name", "")
            # 클래스 이름의 마지막 부분이 display_name과 일치하는지 확인
            simple_name = comp_name.split("::")[-1].lower()
            if simple_name == search_name:
                api_names.append(comp_name)
                packages_found.add(pkg_name)
                for mb in comp.get("members", [])[:30]:
                    api_names.append(f"{comp_name}::{mb.get('name', '')}")
                break  # 패키지당 첫 매칭 클래스만
        if api_names:
            break  # 첫 번째 패키지 매칭으로 충분

    return sample_apis(api_names), list(packages_found)


def build_child_entries(taxonomy, existing_feature_keys):
    """
    taxonomy에 있는 leaf child 중 feature_map_classified에 없는 항목을
    Doxygen에서 API를 조회하여 synthetic feature entry로 만들어 반환합니다.
    """
    child_entries = []
    for feat_key, tax_entry in taxonomy.items():
        if tax_entry.get("tree_decision") != "leaf":
            continue
        if feat_key in existing_feature_keys:
            continue  # 이미 feature_map에 있으면 스킵

        display_name = tax_entry.get("display_name", feat_key)
        parent = tax_entry.get("parent", "")
        api_names, packages = find_child_api_names(display_name)

        child_entries.append({
            "feature": feat_key,
            "display_name": display_name,
            "packages": packages,
            "api_tiers": ["public-api"],
            "apis": api_names,
            "cross_package_links": [],
            "ambiguous": False,
            "_is_taxonomy_child": True,   # child임을 표시
            "parent_feature": parent
        })
        print(f"  [Taxonomy Child] Injected '{feat_key}' ({display_name}, {len(api_names)} APIs found)")

    return child_entries


def extract_json_from_text(text):
    """
    Robustly isolates JSON array brackets out of potentially hallucinated Markdown answers.
    """
    match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        text_to_parse = match.group(1)
    else:
        # Fallback raw parser logic looking for top level List Brackets
        start = text.find('[')
        end = text.rfind(']') + 1
        if start != -1 and end != -1:
            text_to_parse = text[start:end]
        else:
            text_to_parse = text
            
    try:
        return json.loads(text_to_parse)
    except Exception as e:
        print(f"   [JSON Parser Check] Syntax err: {e}")
        return []

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Hard limit processing count (useful for fast-path sandbox testing to save quotas).")
    parser.add_argument("--features", type=str, default="", help="Comma-separated list of features to process exclusively.")
    parser.add_argument("--tier", type=str, choices=["app", "platform"], default="app",
                        help="Documentation tier: 'app' (public-api only) or 'platform' (all tiers).")
    args = parser.parse_args()
    
    print("=================================================================")
    print(f" Initiating Stage B: Generative Content Mapper (TOC Outlining) [{args.tier.upper()}]")
    print("=================================================================")

    feature_list = load_json(CLASSIFIED_MAP_PATH)
    if not feature_list:
        return

    # feature_hints 로드
    doc_config = load_doc_config()
    feature_hints = doc_config.get("feature_hints", {})
    if feature_hints:
        print(f"[FeatureHints] Loaded hints for: {list(feature_hints.keys())}")

    # Phase 1.5 taxonomy 로드 (없으면 빈 dict로 진행)
    taxonomy = {}
    if TAXONOMY_PATH.exists():
        taxonomy = load_json(TAXONOMY_PATH) or {}
        print(f"[Taxonomy] Loaded {len(taxonomy)} entries from feature_taxonomy.json")
    else:
        print("[Taxonomy] feature_taxonomy.json not found — proceeding without tree context.")

    # ── Taxonomy child feature 주입 ──────────────────────────────────────
    # feature_map에 없는 leaf child를 Doxygen에서 찾아 목록에 추가
    existing_keys = {f["feature"] for f in feature_list}
    if taxonomy:
        print("[Taxonomy] Scanning for child features not in feature map...")
        child_entries = build_child_entries(taxonomy, existing_keys)
        if child_entries:
            print(f"[Taxonomy] Appended {len(child_entries)} child feature(s) to processing list.")
            feature_list.extend(child_entries)
    # ────────────────────────────────────────────────────────────────────

    client = LLMClient()

    if args.features:
        target_features = [f.strip() for f in args.features.split(",") if f.strip()]
        if target_features:
            feature_list = [f for f in feature_list if f.get("feature") in target_features]
            print(f"[!] TARGET MODE ENGAGED: Filtering to exclusively process {len(feature_list)} requested feature(s): {target_features}")

    if args.limit > 0:
        print(f"[!] TEST MODE ENGAGED: Hard limiting the loop to process only the first {args.limit} clusters.")
        feature_list = feature_list[:args.limit]
        
    for index, cluster in enumerate(feature_list):
        feat_name = cluster.get("feature", "Unknown")
        # 클래스명만 있는 리스트 → sample_apis가 캡 없이 그대로 반환
        apis = sample_apis(cluster.get("apis", []))
        tiers = cluster.get("api_tiers", [])
        
        print(f"\n[{index+1}/{len(feature_list)}] Mapping structural outlines for feature module '{feat_name}' (Sampled APIs: {len(apis)})...")
        
        # dali-ui View context hint: inject for actor/view-related features
        view_context = ""
        tax_entry_b = taxonomy.get(feat_name, {})
        parent_b = tax_entry_b.get("parent", None)
        if feat_name in ("actors", "views", "ui", "ui-components") or \
           parent_b in ("view", "actors", "ui-components") or \
           any("View" in a or "Actor" in a for a in apis):
            view_context = """
        IMPORTANT CONTEXT - DALi UI Architecture:
        All DALi UI code must be based on dali-ui (Dali::Ui::*). Do NOT use raw Dali::Actor.
        Use Dali::Ui::View (or its subclasses) as the primary UI object.
        When designing TOC sections about actor-level behaviors (position, size, signals),
        frame them in terms of how Dali::Ui::View exposes or wraps those capabilities.
        """

        # ── Tier context 주입 ───────────────────────────────────────────
        if args.tier == "app":
            tier_context = """
        TIER CONSTRAINT — APP GUIDE:
        Design sections for APPLICATION DEVELOPERS only.
        - Do NOT include sections about engine internals, integration hooks, platform
          extension points, or devel-api lifecycle management.
        - Focus entirely on public-api usage: how to create, configure, and use this
          feature to build apps.
        - Do not design a section for 'Extending' or 'Subclassing' this feature unless
          it is a direct app-developer pattern (e.g. CustomActor is for app devs).
        """
        else:
            tier_context = """
        TIER CONSTRAINT — PLATFORM GUIDE:
        Design sections for PLATFORM/ENGINE DEVELOPERS.
        - Include sections on internal architecture, lifecycle, thread safety, and
          integration API usage where relevant.
        - You may include both public-api and devel-api/integration-api patterns.
        """

        # ── Taxonomy context 주입 ────────────────────────────────────────
        tax_entry = taxonomy.get(feat_name, {})
        tree_decision = tax_entry.get("tree_decision", "flat")
        children = tax_entry.get("children", [])
        parent = tax_entry.get("parent", None)

        taxonomy_context = ""
        if tree_decision == "tree" and children:
            child_list = ", ".join(f"'{c}'" for c in children)
            taxonomy_context = f"""
        DOCUMENT STRUCTURE CONTEXT:
        This feature ('{feat_name}') is a PARENT document in a tree hierarchy.
        It should serve as an OVERVIEW page that introduces the concept and lists
        its child sub-components: {child_list}.
        Each child will have its own separate detailed documentation page.
        Your TOC should include a section like "Sub-Components Overview" that
        briefly describes each child and links to its dedicated page.
        Do NOT write deep API details for child components here — just overview.
        """
        elif tree_decision == "leaf" and parent:
            taxonomy_context = f"""
        DOCUMENT STRUCTURE CONTEXT:
        This feature ('{feat_name}') is a CHILD component of '{parent}'.
        It should be a FOCUSED, DETAILED page about this specific component.
        Readers are expected to already understand the parent '{parent}' concept.
        Do NOT re-explain basic View/Actor fundamentals — focus on what makes
        '{feat_name}' unique: its specific properties, signals, and use cases.
        """
        # ────────────────────────────────────────────────────────────────

        # ── feature_hints 주입 ───────────────────────────────────────────
        hint_extra = feature_hints.get(feat_name, {}).get("extra_context", "")
        feature_hint_block = f"""
        FEATURE-SPECIFIC GUIDANCE FOR TOC DESIGN:
        {hint_extra}
        """ if hint_extra else ""
        # ────────────────────────────────────────────────────────────────

        prompt = f"""
        You are a senior technical writer documenting the Samsung DALi GUI framework.
        Design a logical Table of Contents (TOC) layout for the feature module '{feat_name}'.
        {view_context}
        {tier_context}
        {taxonomy_context}
        {feature_hint_block}
        Context:
        - Target Audience API Tiers: {tiers}
        - Key API Methods/Classes: {json.dumps(apis, indent=2)}

        SCOPE RULES for TOC design:
        - Design sections ONLY for the '{feat_name}' feature itself.
        - Do NOT design sections that primarily explain a parent class or sibling components.
        - The first section must introduce '{feat_name}' specifically — not a general
          overview of the parent category.
        - Do NOT design sections for 'Extending' or 'Subclassing' '{feat_name}' unless it
          is a documented app-developer pattern for this specific feature.

        Based on the actual complexity and breadth of this feature module, decide the
        appropriate number of sections yourself (between 3 and 10).
        - A simple utility module (e.g. math helpers) needs only 3-4 sections.
        - A moderate feature (e.g. animation, events) needs 5-7 sections.
        - A complex subsystem with lifecycle, signals, and advanced usage needs 8-10 sections.
        - A PARENT overview page needs 4-6 sections including a sub-components listing section.
        - A CHILD leaf page needs 4-7 focused sections on the component's specific API.

        Each section must have a practical, developer-facing title and a concrete 1-sentence description
        of what that section covers.

        Output ONLY a valid pure JSON Array. No markdown wrappers. Schema:
        [
          {{"section_title": "Introduction to {feat_name}", "description": "What it does and when to use it"}},
          {{"section_title": "Core Classes and Architecture", "description": "The key classes and how they relate"}}
        ]
        """
        
        # Deploy Think mode inference
        response = client.generate(prompt, use_think=True)
        outline_json = extract_json_from_text(response)
        
        # Verify and strictly enforce standard formatting natively arrayed payloads
        if outline_json and isinstance(outline_json, list) and len(outline_json) > 0:
            cluster["outline"] = outline_json
            print(f"    [+] Intelligence mapped. Successfully generated {len(outline_json)} TOC sub-headers.")
        else:
            print(f"    [-] Failed to securely parse the outline syntax. Applying a generic fallback template to protect the pipeline.")
            cluster["outline"] = [
                {"section_title": f"Overview of {feat_name}", "description": "General domain knowledge covering functionality."},
                {"section_title": "Key Classes and Usages", "description": "Detailed implementation walkthroughs."}
            ]
            
    OUT_BLUEPRINTS_PATH.parent.mkdir(parents=True, exist_ok=True)

    # ── --features 로 일부만 처리한 경우: 기존 blueprints 와 merge 저장 ────────
    # 전체 실행(--features 미사용)이면 그대로 덮어쓰기
    if args.features:
        existing_map = {}
        if OUT_BLUEPRINTS_PATH.exists():
            try:
                with open(OUT_BLUEPRINTS_PATH, "r", encoding="utf-8") as f:
                    for item in json.load(f):
                        existing_map[item["feature"]] = item
            except Exception:
                pass
        for item in feature_list:
            existing_map[item["feature"]] = item
        merged = list(existing_map.values())
        print(f"  [*] Merged {len(feature_list)} processed feature(s) into existing blueprints "
              f"({len(merged)} total).")
    else:
        merged = feature_list

    with open(OUT_BLUEPRINTS_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
        
    print(f"\n=================================================================")
    print(f" Stage B Complete! Generative blueprints merged downstream.")
    print(f" JSON schema finalized at: {OUT_BLUEPRINTS_PATH}")
    print("=================================================================")

if __name__ == "__main__":
    main()
