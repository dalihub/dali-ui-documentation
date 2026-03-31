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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Terminal isolation debug boundary.")
    args = parser.parse_args()
    
    print("=================================================================")
    print(" Initiating Stage C: Instruct Writer (Markdown Generation)       ")
    print("=================================================================")

    blueprints = load_json(BLUEPRINTS_PATH)
    if not blueprints:
        print("Blueprints corrupted. Aborting Markdown Generation.")
        return
        
    client = LLMClient()
    OUT_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    
    if args.limit > 0:
        print(f"[!] TEST MODE ENGAGED: Hard limiting the loop to process only the first {args.limit} clusters.")
        blueprints = blueprints[:args.limit]
        
    for idx, bp in enumerate(blueprints):
        feat_name = bp.get("feature", "unknown")
        outline = bp.get("outline", [])
        packages = bp.get("packages", [])
        api_names = bp.get("apis", [])
        
        # Omit logic processing if outline failed in Stage B
        if not outline:
            print(f"\\n[{idx+1}/{len(blueprints)}] Skipping '{feat_name}': No outline blueprints detected.")
            continue
            
        print(f"\n[{idx+1}/{len(blueprints)}] Drafting comprehensive Markdown page for '{feat_name}'...")
        
        # 1. Reverse lookup physical C++ facts 
        specs = get_api_specs(packages, api_names)
        print(f"    [+] Joined {len(specs)} factual C++ parameter structures from Doxygen mappings.")
        
        # 2. Strict Generation Frame Prompting
        # View/Actor context for dali-ui app developers
        view_context = ""
        if feat_name in ("actors", "views", "ui", "ui-components") or \
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

        prompt = f"""
        You are an elite C++ technical writer documenting the Samsung DALi GUI framework.
        Your task is to write the COMPLETE and DETAILED Markdown documentation for the '{feat_name}' module.
        {view_context}
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
        
        # Utilize 'Instruct' persona for writing mass textual payloads
        response_md = client.generate(prompt, use_think=False)
        
        clean_md = strip_markdown_wrapping(response_md)
        
        # 3. Export to filesystem Native Node
        out_file = OUT_DRAFTS_DIR / f"{feat_name}.md"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(clean_md)
            
        print(f"    [+] Documentation draft synthesized and exported -> {out_file.name}")
        
    print(f"\n=================================================================")
    print(f" Stage C Complete! Native markdown drafts exported to:")
    print(f" {OUT_DRAFTS_DIR}")
    print("=================================================================")

if __name__ == "__main__":
    main()
