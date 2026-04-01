import os
import json
import argparse
from pathlib import Path
import sys

# Important: Append module path so it can import llm_client natively
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from llm_client import LLMClient

# Context Directories
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = PROJECT_ROOT / "cache"
BLUEPRINTS_PATH = CACHE_DIR / "doc_blueprints" / "stage_b_blueprints.json"
PARSED_DOXYGEN_DIR = CACHE_DIR / "parsed_doxygen"
OUT_DRAFTS_DIR = CACHE_DIR / "markdown_drafts"
VALIDATED_DRAFTS_DIR = CACHE_DIR / "validated_drafts"
CHANGED_APIS_PATH = CACHE_DIR / "changed_apis.json"
TAXONOMY_PATH = CACHE_DIR / "feature_taxonomy" / "feature_taxonomy.json"

def load_json(path):
    if not path.exists():
        print(f"Error: Required context file '{path}' missing.")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_api_specs(pkg_names, api_names_list):
    """
    Reverse Lookup Engine mapping arbitrary ambiguous node names back 
    to precise C++ specification definitions pulled from Stage 1 Doxygen parsings.
    """
    specs = []
    
    # Cap matching complexity against overwhelming LLM Token usage
    max_apidocs_to_extract = 40  # Increased for richer context in generated docs
    
    # Build a simple lookup set from api_names_list for faster matching
    api_name_set = set(a.split("::")[-1] for a in api_names_list)
    
    for pkg in pkg_names:
        pkg_path = PARSED_DOXYGEN_DIR / f"{pkg}.json"
        pkg_data = load_json(pkg_path)
        if not pkg_data: 
            continue
        
        # Real schema is: {"package": "dali-core", "compounds": [...]}
        compounds = pkg_data.get("compounds", [])
        
        for comp in compounds:
            if not isinstance(comp, dict):
                continue
            c_name = comp.get("name", "")
            
            # Match on class name (e.g. "Dali::Actor" contains "Actor")
            is_class_match = any(a in c_name for a in api_names_list) or \
                             any(c_name.split("::")[-1] in api_name_set for _ in [1])
            
            if is_class_match:
                specs.append({
                    "name": c_name,
                    "kind": comp.get("kind", "class"),
                    "brief": comp.get("brief", "No description provided.")
                })
                
                # Granular function parameter lookups within matched class
                for mb in comp.get("members", []):
                    if not isinstance(mb, dict):
                        continue
                    specs.append({
                        "name": f"{c_name}::{mb.get('name', '')}",
                        "kind": mb.get("kind", "function"),
                        "brief": mb.get("brief", ""),
                        "signature": mb.get("signature", "")
                    })
                    if len(specs) >= max_apidocs_to_extract:
                        break
                        
            if len(specs) >= max_apidocs_to_extract:
                break
        if len(specs) >= max_apidocs_to_extract:
            break
            
    return specs

def strip_markdown_wrapping(text):
    """
    Forces pure raw markdown content preventing API from mistakenly 
    double wrapping output in generic ```markdown chunks
    """
    stripped = text.strip()
    if stripped.startswith("```markdown"):
        stripped = stripped[11:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    elif stripped.startswith("```"):
        stripped = stripped[3:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()

def build_patch_prompt(feat_name, existing_draft, changed_specs, taxonomy_context, view_context):
    """기존 문서를 최대한 보존하면서 변경된 API 부분만 수술하는 패치 프롬프트를 생성합니다. (원칙 3)"""
    return f"""
    You are an elite C++ technical writer updating the Samsung DALi GUI framework documentation.
    Your task is to UPDATE the existing guide document for the '{feat_name}' module
    by incorporating only the changed API specifications below.
    {view_context}
    {taxonomy_context}

    [EXISTING PUBLISHED GUIDE DOCUMENT — PRESERVE AS MUCH AS POSSIBLE]
    {existing_draft}

    [CHANGED API SPECIFICATIONS — BASED ON LATEST SOURCE CODE]
    {json.dumps(changed_specs, indent=2)}

    STRICT PATCHING RULES:
    - Keep the existing document's section structure, writing style, and example code style exactly as-is.
    - Modify ONLY the parts of the document that describe the changed APIs listed above.
    - Do NOT alter any content, examples, or explanations unrelated to the changed APIs.
    - If a new API is added: insert it in the most appropriate existing section.
    - If an API is removed: delete only the description and examples for that specific API.
    - Output the COMPLETE updated markdown document (not just the changed sections).
    - Output raw markdown text only. Do NOT wrap in ```markdown blocks.
    """


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Terminal isolation debug boundary.")
    parser.add_argument("--features", type=str, default="", help="Comma-separated list of features to process exclusively (full mode).")
    parser.add_argument("--patch", action="store_true", help="Patch mode: reuse existing draft, update only changed API sections.")
    parser.add_argument("--patch-features", type=str, default="", help="Comma-separated list of features to patch (used with --patch).")
    args = parser.parse_args()
    
    print("=================================================================")
    print(" Initiating Stage C: Instruct Writer (Markdown Generation)       ")
    print("=================================================================")

    blueprints = load_json(BLUEPRINTS_PATH)
    if not blueprints:
        print("Blueprints corrupted. Aborting Markdown Generation.")
        return

    # Phase 1.5 taxonomy 로드
    taxonomy = {}
    if TAXONOMY_PATH.exists():
        taxonomy = load_json(TAXONOMY_PATH) or {}
        print(f"[Taxonomy] Loaded {len(taxonomy)} entries from feature_taxonomy.json")
    else:
        print("[Taxonomy] feature_taxonomy.json not found — proceeding without tree context.")

    client = LLMClient()
    OUT_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    
    # ── 패치 모드: --patch-features 로 대상 결정 ───────────────────────────────
    if args.patch:
        patch_feature_list = [f.strip() for f in args.patch_features.split(",") if f.strip()]
        if patch_feature_list:
            blueprints = [bp for bp in blueprints if bp.get("feature") in patch_feature_list]
            print(f"[PATCH] Patch mode engaged: {len(blueprints)} feature(s) targeted: {patch_feature_list}")
        else:
            print("[PATCH] --patch set but --patch-features is empty. Processing all blueprints in patch mode.")

        # changed_apis.json 로드 (패치 모드 전용)
        changed_apis_data = load_json(CHANGED_APIS_PATH) if CHANGED_APIS_PATH.exists() else {}
        changed_api_names_global = set()
        for pkg_apis in changed_apis_data.values():
            for api in pkg_apis:
                changed_api_names_global.add(api.get("name", ""))
    else:
        # ── Full 생성 모드: --features 로 대상 결정 ──────────────────────────
        if args.features:
            target_features = [f.strip() for f in args.features.split(",") if f.strip()]
            if target_features:
                blueprints = [bp for bp in blueprints if bp.get("feature") in target_features]
                print(f"[!] TARGET MODE ENGAGED: Filtering to exclusively process {len(blueprints)} requested feature(s): {target_features}")

    if args.limit > 0:
        print(f"[!] TEST MODE ENGAGED: Hard limiting the loop to process only the first {args.limit} clusters.")
        blueprints = blueprints[:args.limit]
        
    for idx, bp in enumerate(blueprints):
        feat_name = bp.get("feature", "unknown")
        outline = bp.get("outline", [])
        packages = bp.get("packages", [])
        api_names = bp.get("apis", [])

        # 공통: Taxonomy 컨텍스트 조립
        tax_entry = taxonomy.get(feat_name, {})
        tree_decision = tax_entry.get("tree_decision", "flat")
        children = tax_entry.get("children", [])
        parent = tax_entry.get("parent", None)
        audience = tax_entry.get("audience", "app")

        taxonomy_context = ""
        if tree_decision == "tree" and children:
            child_list = ", ".join(f"`{c}`" for c in children)
            taxonomy_context = f"""
        DOCUMENT ROLE — PARENT OVERVIEW PAGE:
        This is the overview (parent) page for the '{feat_name}' feature family.
        Its child components ({child_list}) each have their own dedicated pages.
        Writing rules:
        - Introduce the overall concept and architecture of this feature family.
        - Describe each child component in 2-3 sentences and add a '→ See: [ChildName]' reference.
        - Do NOT write exhaustive API details for child components — just enough to understand when to use each.
        - Focus on how the parent and children relate structurally.
        """
        elif tree_decision == "leaf" and parent:
            taxonomy_context = f"""
        DOCUMENT ROLE — CHILD DETAIL PAGE:
        This is a focused detail page for '{feat_name}', which is a sub-component of '{parent}'.
        Writing rules:
        - Do NOT re-explain '{parent}' basics — readers have already read the parent page.
        - Focus entirely on what makes '{feat_name}' unique: its specific constructor, properties, signals.
        - Start with a 1-paragraph introduction explaining when to use '{feat_name}' over other {parent} variants.
        - Provide thorough code examples specific to '{feat_name}'.
        """
        elif audience == "platform":
            taxonomy_context = """
        DOCUMENT ROLE — PLATFORM DEVELOPER PAGE:
        This documentation targets platform/engine developers, NOT app developers.
        - Use technical C++ detail — do not simplify for beginners.
        - Explain internal architecture, thread safety, and lifecycle implications.
        - App developers use higher-level APIs (like View); this page covers the low-level layer.
        """

        view_context = ""
        if feat_name in ("actors", "views", "ui", "ui-components", "view") or \
           any("View" in n or "Actor" in n for n in api_names[:10]):
            view_context = """
        CRITICAL ARCHITECTURE CONTEXT:
        In DALi UI applications, developers use 'Dali::Ui::View' as the primary UI object,
        NOT 'Dali::Actor' directly. View inherits from Actor and wraps its transform,
        rendering, and signal capabilities - but View has its own distinct API surface,
        event model, and lifecycle that differs from raw Actor usage.
        Rules:
        - Explain Actor-level behaviors (position, size, parent/child, signals) ONLY as
          context for how View surfaces or inherits them.
        - Always show code examples using View (Dali::Ui::View), not raw Actor.
        - When an Actor API has no View equivalent, note it as a platform-level detail,
          not something app developers call directly.
        """

        # ── 패치 모드 (원칙 3) ─────────────────────────────────────────────
        if args.patch:
            existing_draft_path = VALIDATED_DRAFTS_DIR / f"{feat_name}.md"
            if not existing_draft_path.exists():
                print(f"\n[{idx+1}/{len(blueprints)}] PATCH SKIP '{feat_name}': No existing draft found. Run full mode first.")
                continue

            existing_draft = existing_draft_path.read_text(encoding="utf-8")

            # 이 피처와 관련된 변경 API 스펙만 필터링
            specs = get_api_specs(packages, api_names)
            # changed_apis_data 에서 이 피처 관련 항목만 추출
            changed_specs = [
                s for s in specs
                if any(
                    s.get("name", "") in changed_api_names_global or
                    s.get("name", "").split("::")[-1] in changed_api_names_global
                    for _ in [1]
                )
            ] or specs  # changed_api_names 매칭 실패 시 전체 specs 사용

            print(f"\n[{idx+1}/{len(blueprints)}] PATCHING '{feat_name}' ({len(changed_specs)} changed API specs)...")

            prompt = build_patch_prompt(
                feat_name, existing_draft, changed_specs, taxonomy_context, view_context
            )

        # ── Full 생성 모드 ─────────────────────────────────────────────────
        else:
            if not outline:
                print(f"\n[{idx+1}/{len(blueprints)}] Skipping '{feat_name}': No outline blueprints detected.")
                continue

            print(f"\n[{idx+1}/{len(blueprints)}] Drafting comprehensive Markdown page for '{feat_name}'...")

            specs = get_api_specs(packages, api_names)
            print(f"    [+] Joined {len(specs)} factual C++ parameter structures from Doxygen mappings.")

            prompt = f"""
        You are an elite C++ technical writer documenting the Samsung DALi GUI framework.
        Your task is to write the COMPLETE and DETAILED Markdown documentation for the '{feat_name}' module.
        {view_context}
        {taxonomy_context}
        Follow this Table of Contents structure exactly:
        {json.dumps(outline, indent=2)}

        ANTI-HALLUCINATION RULE:
        Use ONLY the C++ API specs below for all signatures, parameter types, and return values.
        Do NOT invent non-existent APIs or parameters:
        {json.dumps(specs, indent=2)}

        Writing Guidelines:
        - Write entirely in valid GitHub Flavored Markdown.
        - Use ## for section titles and ### for sub-sections.
        - Each section must be DETAILED and THOROUGH - do not summarize, explain fully.
        - For every important API method: explain WHAT it does, WHY you'd use it, and HOW
          to call it correctly (parameters, return value, side effects).
        - Include at least one complete, realistic C++ code example per section.
          Code examples MUST use only API signatures from the spec above.
        - Highlight important notes, warnings, or best practices using blockquotes (> Note:).
        - Target audience is application developers (not platform/engine developers).
        - Output raw markdown text only. Do NOT wrap in ```markdown blocks.
        """

        response_md = client.generate(prompt, use_think=False)
        clean_md = strip_markdown_wrapping(response_md)

        out_file = OUT_DRAFTS_DIR / f"{feat_name}.md"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(clean_md)

        mode_label = "[PATCH]" if args.patch else "[DRAFT]"
        print(f"    [+] {mode_label} Documentation exported → {out_file.name}")
        
    print(f"\n=================================================================")
    print(f" Stage C Complete! Native markdown drafts exported to:")
    print(f" {OUT_DRAFTS_DIR}")
    print("=================================================================")

if __name__ == "__main__":
    main()
