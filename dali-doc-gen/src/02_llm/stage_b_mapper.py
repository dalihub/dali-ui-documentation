import os
import re
import json
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

def load_json(path):
    if not path.exists():
        print(f"Error: Could not locate map inside '{path}'. Have you run Stage A?")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

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
    args = parser.parse_args()
    
    print("=================================================================")
    print(" Initiating Stage B: Generative Content Mapper (TOC Outlining)   ")
    print("=================================================================")

    feature_list = load_json(CLASSIFIED_MAP_PATH)
    if not feature_list:
        return
        
    client = LLMClient()
    
    if args.limit > 0:
        print(f"[!] TEST MODE ENGAGED: Hard limiting the loop to process only the first {args.limit} clusters.")
        feature_list = feature_list[:args.limit]
        
    for index, cluster in enumerate(feature_list):
        feat_name = cluster.get("feature", "Unknown")
        # Hard cap the tokens shown to prevent AI memory overflow/loss of track.
        apis = cluster.get("apis", [])[:50] 
        tiers = cluster.get("api_tiers", [])
        
        print(f"\n[{index+1}/{len(feature_list)}] Mapping structural outlines for feature module '{feat_name}' (Sampled APIs: {len(apis)})...")
        
        prompt = f"""
        You are a senior technical writer documenting a C++ Graphic/UI framework.
        Design a logical Table of Contents (TOC) layout for the feature '{feat_name}'.
        
        Context Vectors:
        - Target Audience API Tiers: {tiers}
        - Key API Methods/Classes: {json.dumps(apis, indent=2)}
        
        Design an intuitive document hierarchy targeting application developers.
        Output ONLY a valid pure JSON Array containing layout objects mapping "section_title" to a short "description". 
        Aim for 3 to 5 highly practical narrative sections (e.g. Overview, Core Architectures, Handling the API, Best Practices).
        Do NOT output Markdown wrappers. Produce exactly this output schema format:
        [
          {{"section_title": "Introduction to {feat_name}", "description": "A very brief 1 liner on what it does"}},
          {{"section_title": "Core Components", "description": "Exploring specific classes based on the method names"}}
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
    with open(OUT_BLUEPRINTS_PATH, "w", encoding="utf-8") as f:
        json.dump(feature_list, f, indent=2, ensure_ascii=False)
        
    print(f"\n=================================================================")
    print(f" Stage B Complete! Generative blueprints merged downstream.")
    print(f" JSON schema finalized at: {OUT_BLUEPRINTS_PATH}")
    print("=================================================================")

if __name__ == "__main__":
    main()
