import os
import json
import yaml
from pathlib import Path
import xml.etree.ElementTree as ET

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "repo_config.yaml"
CACHE_DOXYGEN_ROOT = PROJECT_ROOT / "cache" / "doxygen_json"
CALLGRAPH_JSON_ROOT = PROJECT_ROOT / "cache" / "callgraph_json"

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def extract_text(element):
    if element is None:
        return ""
    # "".join(element.itertext()) correctly handles nested text inside elements
    return "".join(element.itertext()).strip()

def process_package(package_name):
    xml_dir = CACHE_DOXYGEN_ROOT / package_name / "xml"
    index_path = xml_dir / "index.xml"
    
    if not index_path.exists():
        print(f"Skipping {package_name}: index.xml not found at {index_path}")
        return False

    print(f"Processing callgraph for package: {package_name}")
    
    # 1. Build refid to qualified_name lookup map
    # We do a fast initial pass over the XMLs to map EVERY refid so we can 
    # resolve references effectively, including private/internal ones.
    ref_map = {}
    
    tree = ET.parse(index_path)
    root = tree.getroot()
    
    for compound in root.findall("compound"):
        refid = compound.get("refid")
        kind = compound.get("kind")
        
        # In Doxygen, file and namespace can also contain standalone memberdefs (functions, enums)
        if kind not in ["class", "struct", "namespace", "file"]:
            continue
            
        xml_file = xml_dir / f"{refid}.xml"
        if not xml_file.exists():
            continue
            
        try:
            ctree = ET.parse(xml_file)
            croot = ctree.getroot()
            compounddef = croot.find("compounddef")
            if compounddef is None:
                continue
                
            c_name = extract_text(compounddef.find("compoundname"))
            
            for sectiondef in compounddef.findall("sectiondef"):
                for memberdef in sectiondef.findall("memberdef"):
                    m_id = memberdef.get("id")
                    m_name = extract_text(memberdef.find("name"))
                    q_name = extract_text(memberdef.find("qualifiedname"))
                    
                    if not q_name:
                        # Fallback if qualifiedname doesn't exist
                        q_name = f"{c_name}::{m_name}" if c_name else m_name
                    
                    if m_id:
                        ref_map[m_id] = q_name
        except Exception as e:
            print(f"  Error reading {xml_file} in Phase 1: {e}")
            
    # 2. Extract references & referencedby for target functions
    call_graphs = {}
    
    for compound in root.findall("compound"):
        refid = compound.get("refid")
        kind = compound.get("kind")
        if kind not in ["class", "struct", "namespace", "file"]:
            continue
            
        xml_file = xml_dir / f"{refid}.xml"
        if not xml_file.exists():
            continue
            
        try:
            ctree = ET.parse(xml_file)
            compounddef = ctree.getroot().find("compounddef")
            if compounddef is None:
                continue
            
            for sectiondef in compounddef.findall("sectiondef"):
                sk = sectiondef.get("kind", "")
                if "private" in sk or "internal" in sk:
                    continue
                    
                for memberdef in sectiondef.findall("memberdef"):
                    prot = memberdef.get("prot", "")
                    if prot == "private":
                        continue
                        
                    m_id = memberdef.get("id")
                    # If it's a target API, we expect it in our ref_map
                    q_name = ref_map.get(m_id, extract_text(memberdef.find("name")))
                    
                    calls = []
                    for ref in memberdef.findall("references"):
                        r_id = ref.get("refid")
                        if r_id in ref_map:
                            calls.append(ref_map[r_id])
                        else:
                            # if not in map, just use text
                            calls.append(extract_text(ref))
                            
                    called_by = []
                    for ref in memberdef.findall("referencedby"):
                        r_id = ref.get("refid")
                        if r_id in ref_map:
                            called_by.append(ref_map[r_id])
                        else:
                            called_by.append(extract_text(ref))
                            
                    if calls or called_by:
                        call_graphs[q_name] = {
                            "calls": list(set(calls)),
                            "called_by": list(set(called_by))
                        }
        except Exception as e:
            # We silently skip malformed ones to gracefully continue
            pass
            
    # 3. Write output JSON
    CALLGRAPH_JSON_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = CALLGRAPH_JSON_ROOT / f"{package_name}.json"
    
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "package": package_name,
            "call_graphs": call_graphs
        }, f, indent=2, ensure_ascii=False)
        
    print(f"Successfully processed {package_name}: {len(call_graphs)} function call graphs saved to {out_path}")
    return True

def main():
    config = load_config()
    repos = config.get("repos", {})
    
    success_count = 0
    for repo_name in repos.keys():
        if process_package(repo_name):
            success_count += 1
            
    print(f"\\nCallgraph parsing complete. Processed {success_count}/{len(repos)} packages.")

if __name__ == "__main__":
    main()
