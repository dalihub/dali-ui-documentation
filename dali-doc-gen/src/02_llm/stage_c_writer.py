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
    max_apidocs_to_extract = 20
    
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
        prompt = f"""
        You are an elite C++ technical writer documenting the Samsung DALi GUI framework. 
        Your task is to write the complete Markdown documentation content for the module '{feat_name}'.
        
        You MUST follow this exact mapped Table of Contents structure seamlessly:
        {json.dumps(outline, indent=2)}
        
        CRITICAL ANTI-HALLUCINATION RULE: 
        Use ONLY the following extracted C++ API Reference to write the code parameters and functional descriptions. Do not invent non-existent APIs:
        {json.dumps(specs, indent=2)}
        
        Guidelines:
        - Write entirely in valid GitHub Flavored Markdown (.md).
        - Use logical header depth (##, ###) respecting the outlined section titles.
        - Include brief dummy C++ code snippet examples demonstrating expected usage to help App developers.
        - Output the raw markdown text directly (Do not enclose inside a global markdown graphic wrap).
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
