import os
import json
import yaml
from pathlib import Path

# Paths Setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "repo_config.yaml"
CACHE_DIR = PROJECT_ROOT / "cache"
PARSED_DOXYGEN_DIR = CACHE_DIR / "parsed_doxygen"
CALLGRAPH_DIR = CACHE_DIR / "callgraph_json"
OUTPUT_DIR = CACHE_DIR / "feature_map"

def load_json(path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def extract_feature_name(file_path, api_tiers):
    """
    Given a file path and a list of api_tier paths (e.g., 'dali/public-api'),
    this extracts the immediate child directory as the feature name.
    """
    for tier in api_tiers:
        if tier in file_path:
            parts = file_path.split(tier + "/")
            if len(parts) > 1:
                sub_path = parts[1]
                sub_parts = sub_path.split("/")
                if len(sub_parts) > 1:
                    # e.g., "actors/actor.h" returns "actors"
                    return sub_parts[0]
                else:
                    # No sub-folder (e.g. root level inside the tier path directly like "common.h")
                    return None
    return None

def main():
    config = load_config()
    repos = config.get("repos", {})

    all_apis = []
    
    # 1. Load parsed_doxygen JSONs from Phase 0
    print("Loading extracted API definitions...")
    for pkg, info in repos.items():
        parsed_path = PARSED_DOXYGEN_DIR / f"{pkg}.json"
        data = load_json(parsed_path)
        if not data:
            continue
            
        api_tiers = info.get("api_dirs", [])
        
        compounds = data.get("compounds", [])
        for c in compounds:
            c["package"] = pkg
            c["config_tiers"] = api_tiers
            all_apis.append(c)

    # 2. Heuristic Clustering (Directory-driven)
    print("Clustering APIs by feature domains...")
    feature_map = {}
    
    for api in all_apis:
        pkg = api["package"]
        file_path = api.get("file", "")
        # The specific tier classification string (e.g. 'public-api')
        api_tier = api.get("api_tier", "unknown")
        
        # Determine the logical Feature bucket direction
        feature_name = extract_feature_name(file_path, api.get("config_tiers", []))
        
        ambiguous = False
        if not feature_name:
            feature_name = "uncategorized_ambiguous_root"
            ambiguous = True
            
        cluster_key = feature_name
        
        if cluster_key not in feature_map:
            feature_map[cluster_key] = {
                "feature": cluster_key,
                "packages": set(),
                "api_tiers": set(),
                "apis": [],
                "cross_package_links": set(),
                "ambiguous": True if ambiguous else False
            }
            
        cluster = feature_map[cluster_key]
        cluster["packages"].add(pkg)
        cluster["api_tiers"].add(api_tier)
        cluster["apis"].append(api.get("name"))
        
        # Mark whole cluster logic if it's strictly the ambiguous bucket
        if ambiguous:
            cluster["ambiguous"] = True

    # 3. Manual Feature Injection (Phase 1.5)
    # repo_config.yaml의 manual_features 항목을 강제 삽입/덮어쓰기
    manual_features = config.get("manual_features", [])
    if manual_features:
        print(f"Injecting {len(manual_features)} manual feature override(s)...")
        for mf in manual_features:
            feat_key = mf.get("feature")
            if not feat_key:
                continue
            if feat_key in feature_map:
                # 기존 클러스터에 메타데이터 보강
                feature_map[feat_key]["display_name"] = mf.get("display_name", feat_key)
                feature_map[feat_key]["description"] = mf.get("description", "")
                feature_map[feat_key]["base_class"] = mf.get("base_class", "")
                feature_map[feat_key]["force_tree_review"] = mf.get("force_tree_review", False)
                if "audience" in mf:
                    feature_map[feat_key]["audience"] = mf["audience"]
                print(f"  > Enriched existing feature '{feat_key}' with manual metadata.")
            else:
                # 신규로 강제 삽입
                feature_map[feat_key] = {
                    "feature": feat_key,
                    "display_name": mf.get("display_name", feat_key),
                    "packages": {mf.get("source_package", "unknown")},
                    "api_tiers": set(),
                    "apis": [],
                    "cross_package_links": set(),
                    "ambiguous": False,
                    "description": mf.get("description", ""),
                    "base_class": mf.get("base_class", ""),
                    "force_tree_review": mf.get("force_tree_review", False),
                    "audience": mf.get("audience", "app"),
                    "manual_injected": True
                }
                print(f"  > Force-injected new feature '{feat_key}'.")
    # The actual deep mapping will evaluate these clusters next phase.
    print("Cross-referencing logic skipped for heuristic bounds (to be completed in depth by LLM or later layers).")

    # 4. Serialize Output mappings
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "feature_map.json"
    
    feature_list = []
    for f in feature_map.values():
        f["packages"] = list(f["packages"])
        f["api_tiers"] = list(f["api_tiers"])
        f["cross_package_links"] = list(f["cross_package_links"])
        feature_list.append(f)
        
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(feature_list, f, indent=2, ensure_ascii=False)
        
    print(f"\\nSuccessfully clustered {len(all_apis)} unique APIs into {len(feature_list)} distinct feature themes.")
    print(f"Saved feature map schema to {out_path}")

if __name__ == "__main__":
    main()
