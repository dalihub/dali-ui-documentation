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

def enrich_apis_with_members(apis, allowed_tiers):
    """
    feature_map의 apis에 실제 function 멤버가 없는 경우 parsed_doxygen에서 보완해 반환한다.

    feature_clusterer.py는 compound name(클래스/중첩 타입)만 apis에 등록하므로
    single-class 피처(image-view, label 등)에서 stage_b outline 생성 시
    메서드 목록 없이 LLM 추론에만 의존하는 문제를 해결한다.

    판단 기준: parsed_doxygen에서 apis 내 클래스의 실제 function 멤버가
    apis에 하나도 없으면 보완 진행. Label::Property처럼 중첩 타입 compound가
    apis에 있어도 function 멤버가 없으면 보완한다.

    sample_apis()의 50개 캡 로직이 그대로 동작하므로 메서드가 많아도 자동 제한된다.
    """
    class_entries = [a for a in apis if not a.endswith((".cpp", ".h"))]
    if not class_entries:
        return apis

    class_set = set(class_entries)
    apis_set = set(apis)
    enriched = list(apis)
    has_function = False

    for pkg_json in PARSED_DOXYGEN_DIR.glob("*.json"):
        data = load_json(pkg_json)
        if not data:
            continue
        for comp in data.get("compounds", []):
            cn = comp.get("name", "")
            if cn not in class_set:
                continue
            if allowed_tiers and comp.get("api_tier") not in allowed_tiers:
                continue
            for mb in comp.get("members", []):
                mb_kind = mb.get("kind", "")
                mb_name = mb.get("name", "")
                if mb_kind != "function" or not mb_name \
                        or mb_name.startswith("operator") \
                        or mb_name.startswith("~"):
                    continue
                full_sym = f"{cn}::{mb_name}"
                if full_sym in apis_set:
                    # 이미 실제 function 멤버가 apis에 있음 — 보완 불필요
                    return apis
                has_function = True
                enriched.append(full_sym)

    return enriched if has_function else apis


def build_api_tier_index():
    """parsed_doxygen에서 {compound_name: api_tier} 인덱스를 구축한다."""
    index = {}
    for pkg_json in PARSED_DOXYGEN_DIR.glob("*.json"):
        data = load_json(pkg_json)
        if not data:
            continue
        for comp in data.get("compounds", []):
            name = comp.get("name", "")
            tier = comp.get("api_tier", "unknown")
            if name:
                index[name] = tier
                for mb in comp.get("members", []):
                    mb_name = mb.get("name", "")
                    if mb_name:
                        index[f"{name}::{mb_name}"] = tier
    return index


def filter_apis_by_tier(apis, api_tier_index, allowed_tiers):
    """
    APIs 목록에서 allowed_tiers에 속하는 compound만 반환.
    파일명(.cpp/.h) 항목과 인덱스에 없는 항목은 제외한다.
    allowed_tiers가 None이면 원본 목록을 그대로 반환한다.
    """
    if allowed_tiers is None:
        return apis
    filtered = []
    for name in apis:
        if name.endswith((".cpp", ".h")):
            continue
        if api_tier_index.get(name) in allowed_tiers:
            filtered.append(name)
    return filtered




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

    # Fix: .autogen 항목들은 method chaining 보일러플레이트이므로 Blueprint 문서화 대상에서 완전히 배제
    feature_list = [f for f in feature_list if not f.get("feature", "").endswith(".autogen")]

    out_blueprints_path = CACHE_DIR / "doc_blueprints" / f"stage_b_blueprints_{args.tier}.json"

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

    allowed_tiers = {"public-api"} if args.tier == "app" else None

    client = LLMClient()
    api_tier_index = build_api_tier_index()

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
        
        # 1. Filter apis first
        raw_apis = cluster.get("apis", [])
        filtered_apis = filter_apis_by_tier(raw_apis, api_tier_index, allowed_tiers)

        # 2. 메서드가 없는 단일 클래스 피처의 경우 parsed_doxygen에서 메서드 보완
        filtered_apis = enrich_apis_with_members(filtered_apis, allowed_tiers)

        # 3. Sample filtered apis
        apis = sample_apis(filtered_apis)
        cluster["apis"] = apis
        cluster["allowed_tiers"] = list(allowed_tiers) if allowed_tiers else None
        
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
        - Do NOT design sections for 'Extending' or 'Subclassing' '{feat_name}' unless it
          is a documented app-developer pattern for this specific feature.

        FIRST SECTION RULE (mandatory):
        - The first entry MUST always be exactly {{"section_title": "Overview", "description": "<your 1-sentence description>"}}.
        - Do NOT rename it to "Introduction", "What is X", or anything else. The title must be "Overview".
        - The description should answer: what '{feat_name}' is, when to use it, and what makes it distinct.

        Based on the actual complexity and breadth of this feature module, decide the
        appropriate number of sections yourself (between 3 and 10, NOT counting the mandatory Overview).
        - A simple utility module (e.g. math helpers) needs only 3-4 sections.
        - A moderate feature (e.g. animation, events) needs 5-7 sections.
        - A complex subsystem with lifecycle, signals, and advanced usage needs 8-10 sections.
        - A PARENT overview page needs 4-6 sections including a sub-components listing section.
        - A CHILD leaf page needs 4-7 focused sections on the component's specific API.

        Each section must have a practical, developer-facing title and a concrete 1-sentence description
        of what that section covers.

        Output ONLY a valid pure JSON Array. No markdown wrappers. Schema:
        [
          {{"section_title": "Overview", "description": "What {feat_name} is, when to use it, and what makes it distinct"}},
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
            
    out_blueprints_path.parent.mkdir(parents=True, exist_ok=True)

    # ── --features 로 일부만 처리한 경우: 기존 blueprints 와 merge 저장 ────────
    # 전체 실행(--features 미사용)이면 그대로 덮어쓰기
    if args.features:
        existing_map = {}
        if out_blueprints_path.exists():
            try:
                with open(out_blueprints_path, "r", encoding="utf-8") as f:
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

    with open(out_blueprints_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
        
    print(f"\n=================================================================")
    print(f" Stage B Complete! Generative blueprints merged downstream.")
    print(f" JSON schema finalized at: {out_blueprints_path}")
    print("=================================================================")

if __name__ == "__main__":
    main()
