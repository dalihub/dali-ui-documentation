import os
import re
import json
from pathlib import Path

# Important: Append module path so it can import llm_client natively
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from llm_client import LLMClient

# Context Directories
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = PROJECT_ROOT / "cache"
FEATURE_MAP_PATH = CACHE_DIR / "feature_map" / "feature_map.json"
OUT_MAP_PATH = CACHE_DIR / "feature_map" / "feature_map_classified.json"

def load_json(path):
    if not path.exists():
        print(f"Error: Could not find dependency map '{path}'")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def extract_json_from_text(text):
    """
    Strips away markdown wrappers or LLM reasoning artifacts
    ensuring only pure JSON structures are absorbed into the pipeline.
    """
    match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        text_to_parse = match.group(1)
    else:
        # Fallback raw parser logic
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end != -1:
            text_to_parse = text[start:end]
        else:
            text_to_parse = text
            
    try:
        return json.loads(text_to_parse)
    except Exception as e:
        print(f"JSON Parsing Error: {e} | Text: {text_to_parse}")
        return None

def _rebuild_class_feature_map(final_classified_map, out_map_path):
    """
    classified feature map 기반으로 class_feature_map.json을 재생성한다.
    ambiguous 해소 결과 및 taxonomy_reviewer의 split/merge 반영이 목적.
    조기 반환 경로와 정상 경로 모두에서 호출된다.
    """
    class_feature_map = {}
    for feat in final_classified_map:
        feat_id = feat.get("feature", "")
        if not feat_id or feat.get("suppress_doc"):
            continue
        for cls_name in feat.get("apis", []):
            if cls_name and cls_name not in class_feature_map:
                class_feature_map[cls_name] = feat_id

    # suppress_doc feature의 클래스는 merge_into target으로 재매핑
    # (classified에는 suppress_doc feature가 포함되지 않으므로 feature_map에서 로드)
    feature_map_path = out_map_path.parent / "feature_map.json"
    if feature_map_path.exists():
        with open(feature_map_path, "r", encoding="utf-8") as f:
            raw_feature_map = json.load(f)
        for feat in raw_feature_map:
            if feat.get("suppress_doc") and feat.get("merge_into"):
                target = feat["merge_into"]
                for cls_name in feat.get("apis", []):
                    if cls_name:
                        class_feature_map[cls_name] = target

    class_map_path = out_map_path.parent / "class_feature_map.json"
    with open(class_map_path, "w", encoding="utf-8") as f:
        json.dump(class_feature_map, f, indent=2, ensure_ascii=False)
    print(f"[ClassMap] Rebuilt class→feature map ({len(class_feature_map)} entries) "
          f"from classified → {class_map_path.name}")


def main():
    print("=================================================================")
    print(" Initiating Stage A: Intelligent Classification of Features")
    print("=================================================================")
    
    feature_list = load_json(FEATURE_MAP_PATH)
    if not feature_list:
        return
        
    client = LLMClient()
    
    # 1. Pipeline Isolation
    stable_clusters = []
    ambiguous_clusters = []
    
    for cluster in feature_list:
        if cluster.get("ambiguous") == True:
            ambiguous_clusters.append(cluster)
        else:
            stable_clusters.append(cluster)
            
    if not ambiguous_clusters:
        print(">> No ambiguous clusters detected. The map is fully classified natively.")
        OUT_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT_MAP_PATH, "w", encoding="utf-8") as f:
            json.dump(feature_list, f, indent=2, ensure_ascii=False)
        print(f"Final feature map schema output securely tied to {OUT_MAP_PATH}")
        # taxonomy_reviewer의 split/merge 결과가 feature_map.json에 반영됐으므로
        # ambiguous cluster가 없어도 class_feature_map은 반드시 재생성해야 한다.
        _rebuild_class_feature_map(feature_list, OUT_MAP_PATH)
        return

    # Extract clean target candidate namespaces
    # _split_root: True인 feature는 split 후 apis가 비워진 overview 껍데기이므로
    # ambiguous API 분류 대상에서 제외 (A1/A2/A3 등 실제 자식에게 분류되도록)
    target_candidates = [
        c["feature"] for c in stable_clusters
        if not c.get("_split_root")
    ]
    
    if not target_candidates:
        print("Fatal Error: No stable cluster rooms exist to merge target orphans toward.")
        return
        
    print(f">> Scanned {len(target_candidates)} structurally stable categories and {len(ambiguous_clusters)} ambiguous entity chunks.")
    
    # Map dictionary tracking
    stable_dict = {c["feature"]: c for c in stable_clusters}
    
    for amb_cluster in ambiguous_clusters:
        # Heavily cap the LLM context bounds to preserve tokens
        apis_sample = amb_cluster.get("apis", [])[:15] 
        pkg = amb_cluster.get("packages", [])
        original_name = amb_cluster.get("feature", "unknown")
        
        prompt = f"""
        You are a senior C++ framework architect specializing in API taxonomy.
        We have a set of uncategorized (ambiguous) APIs exported from the packages: {pkg}
        These APIs function signatures/names are:
        {json.dumps(apis_sample, indent=2)}
        
        Your ONLY job is to merge them into EXACTLY ONE of the following existing stable categories (choose exactly one string):
        {json.dumps(target_candidates, indent=2)}
        
        Analyze the typical GUI/rendering semantics of these names and select the strongest logical category fit.
        Reply ONLY with a raw JSON object matching this schema exactly (No markdown, no pre-text):
        {{
          "target_feature": "category_name_from_list",
          "reason": "A highly concise 1 sentence explanation of why this belongs here"
        }}
        """
        
        print(f"\n -> Connecting to Think AI for classifying orphan cluster '{original_name}' (APIs Count: {len(amb_cluster.get('apis', []))})...")
        # Utilize Think AI layer routing explicitly
        response = client.generate(prompt, use_think=True)
        
        ans_json = extract_json_from_text(response)
        
        merged = False
        if ans_json and "target_feature" in ans_json:
            target = ans_json["target_feature"]
            reason = ans_json.get("reason", "No reason provided")
            
            if target in stable_dict:
                print(f"    [+] AI Classification Match: Moving API node to '{target}' group.")
                print(f"        Reasoning: {reason}")
                
                # Perform logical array merge operation
                dest = stable_dict[target]
                dest["apis"].extend(amb_cluster.get("apis", []))
                dest["apis"] = list(set(dest["apis"]))
                
                dest["packages"] = list(set(dest.get("packages", []) + amb_cluster.get("packages", [])))
                dest["api_tiers"] = list(set(dest.get("api_tiers", []) + amb_cluster.get("api_tiers", [])))
                merged = True
            else:
                print(f"    [-] AI Error Context: Model hallucinatively pointed toward unlisted room ('{target}'). Fallback engaged.")
                
        if not merged:
            print(f"    [!] Failed to classify effectively. Escalating the cluster into its own isolated independent group instance.")
            amb_cluster["ambiguous"] = False
            amb_cluster["feature"] = f"unclassified_isolation_{original_name}"
            stable_dict[amb_cluster["feature"]] = amb_cluster
            
    # Serialize definitive data maps into export lists
    final_classified_map = list(stable_dict.values())

    OUT_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(final_classified_map, f, indent=2, ensure_ascii=False)

    # ── class_feature_map 재계산 (classified 기반 최종본) ──────────────────────
    _rebuild_class_feature_map(final_classified_map, OUT_MAP_PATH)
    # ──────────────────────────────────────────────────────────────────────────

    print(f"\n=================================================================")
    print(f" Stage A Complete! Ambiguous elements permanently structured.")
    print(f" Clean exported schema successfully routed to {OUT_MAP_PATH}")
    print("=================================================================")

if __name__ == "__main__":
    main()
