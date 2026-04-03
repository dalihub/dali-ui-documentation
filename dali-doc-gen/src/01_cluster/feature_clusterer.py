import re
import json
import yaml
from pathlib import Path

# Paths Setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "repo_config.yaml"
DOC_CONFIG_PATH = PROJECT_ROOT / "config" / "doc_config.yaml"
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

def load_doc_config():
    if not DOC_CONFIG_PATH.exists():
        return {}
    with open(DOC_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def compute_split_candidates(api_names):
    """
    클래스 이름 목록을 네임스페이스 기반으로 그룹화하여 후보 서브 그룹을 반환한다.

    그룹화 우선순위:
      1. 3레벨 네임스페이스가 있는 경우 (예: Dali::Addon::Manager → 'Addon::Manager')
         같은 2레벨 네임스페이스(Dali::Addon) 아래 3레벨 컴포넌트를 기준으로 묶음
      2. 2레벨 네임스페이스만 있는 경우 (예: Dali::Actor)
         'Impl', 'Devel', 'Property', 'Internal' 접미사를 제거한 기본 이름으로 묶음

    반환: [{"group_name": str, "apis": [str, ...]}, ...]  (그룹 수 >= 2인 경우만)
    """
    groups = {}
    for name in api_names:
        if not name:
            continue
        parts = name.split("::")
        if len(parts) >= 3:
            # Dali::Addon::Manager → key: "Addon::Manager" (3레벨 네임스페이스 컴포넌트)
            # 같은 2레벨(Dali::Addon) 아래 3레벨 컴포넌트별로 그룹화
            key = parts[2]
        else:
            # Dali::Actor, Dali::DevelActor, Dali::ActorProperty → key: "Actor"
            base = parts[-1]
            key = re.sub(r"(Impl|Property|Devel|Internal)$", "", base) or base
        groups.setdefault(key, []).append(name)

    # 그룹명을 feature slug 형식으로 변환 (CamelCase → kebab-case)
    candidates = []
    for key, apis in groups.items():
        slug = re.sub(r"([A-Z])", r"-\1", key).lstrip("-").lower()
        candidates.append({"group_name": slug, "apis": apis})

    return candidates

def count_feature_specs(api_names, all_compounds_by_name):
    """
    feature에 속한 클래스들의 전체 멤버(스펙) 수를 반환한다.
    클래스 자체도 1개로 카운트한다.
    """
    total = 0
    for name in api_names:
        compound = all_compounds_by_name.get(name)
        if compound:
            total += 1 + len(compound.get("members", []))
        else:
            total += 1
    return total

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
    doc_config = load_doc_config()
    repos = config.get("repos", {})
    max_specs = doc_config.get("token_overflow", {}).get("max_specs_per_feature", 2000)

    all_apis = []
    all_compounds_by_name = {}  # class name → compound dict (멤버 수 카운팅용)

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
            # 이름으로 빠른 조회를 위해 인덱싱 (멤버 수 카운팅용)
            all_compounds_by_name[c.get("name", "")] = c

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
                # suppress_doc / merge_into 플래그 전파
                if "suppress_doc" in mf:
                    feature_map[feat_key]["suppress_doc"] = mf["suppress_doc"]
                if "merge_into" in mf:
                    feature_map[feat_key]["merge_into"] = mf["merge_into"]
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
                # suppress_doc / merge_into 플래그 전파
                if "suppress_doc" in mf:
                    feature_map[feat_key]["suppress_doc"] = mf["suppress_doc"]
                if "merge_into" in mf:
                    feature_map[feat_key]["merge_into"] = mf["merge_into"]
                print(f"  > Force-injected new feature '{feat_key}'.")
    # The actual deep mapping will evaluate these clusters next phase.
    print("Cross-referencing logic skipped for heuristic bounds (to be completed in depth by LLM or later layers).")

    # 4. Oversized Feature 감지 및 마킹
    oversized_count = 0
    for cluster in feature_map.values():
        spec_count = count_feature_specs(cluster["apis"], all_compounds_by_name)
        if spec_count > max_specs:
            candidates = compute_split_candidates(cluster["apis"])
            cluster["oversized"] = True
            cluster["total_spec_count"] = spec_count
            cluster["split_candidates"] = candidates if len(candidates) >= 3 else []
            oversized_count += 1
            split_info = f"{len(candidates)} candidate groups" if len(candidates) >= 3 else "no split (single doc)"
            print(f"  [Oversized] '{cluster['feature']}': {spec_count} specs — {split_info}")

    if oversized_count:
        print(f">> {oversized_count} oversized feature(s) detected and marked.")

    # 5. class_feature_map 생성 — 클래스 이름 → 소속 feature 역매핑
    # 동일 클래스가 여러 feature에 중복 등록된 경우 suppress_doc이 없는 feature를 우선
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    class_feature_map = {}
    for feat_name, cluster in feature_map.items():
        is_suppressed = cluster.get("suppress_doc", False)
        for cls_name in cluster.get("apis", []):
            if not cls_name:
                continue
            existing = class_feature_map.get(cls_name)
            if existing is None:
                class_feature_map[cls_name] = feat_name
            elif is_suppressed and not feature_map.get(existing, {}).get("suppress_doc", False):
                pass  # 이미 suppress 아닌 feature가 소유 중 — 유지
            elif not is_suppressed and feature_map.get(existing, {}).get("suppress_doc", False):
                class_feature_map[cls_name] = feat_name  # suppress 아닌 것으로 교체

    class_map_path = OUTPUT_DIR / "class_feature_map.json"
    with open(class_map_path, "w", encoding="utf-8") as f:
        json.dump(class_feature_map, f, indent=2, ensure_ascii=False)
    print(f"Saved class→feature map ({len(class_feature_map)} entries) to {class_map_path}")

    # 6. Serialize Output mappings
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

    suppressed = sum(1 for f in feature_list if f.get("suppress_doc"))
    print(f"\nSuccessfully clustered {len(all_apis)} unique APIs into {len(feature_list)} distinct feature themes.")
    print(f"  {suppressed} feature(s) marked suppress_doc=true.")
    print(f"Saved feature map schema to {out_path}")

if __name__ == "__main__":
    main()
