import os
import sys
import json
import yaml
import re
from pathlib import Path
import xml.etree.ElementTree as ET

# Configure standard paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "repo_config.yaml"
CACHE_DOXYGEN_ROOT = PROJECT_ROOT / "cache" / "doxygen_json"
PARSED_DOXYGEN_ROOT = PROJECT_ROOT / "cache" / "parsed_doxygen"

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def clean_text(text):
    if not text:
        return ""
    text = text.replace('\n', ' ')
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_text_recursive(element, skip_tags=None):
    if skip_tags is None:
        skip_tags = []
        
    if element is None:
        return ""
        
    parts = []
    if element.text and element.tag not in skip_tags:
        parts.append(element.text)
        
    for child in element:
        if child.tag in skip_tags:
            # Skip this element but keep its tail
            if child.tail:
                parts.append(child.tail)
            continue
            
        parts.append(extract_text_recursive(child, skip_tags))
        if child.tail:
            parts.append(child.tail)
            
    return "".join(parts)

def parse_description(desc_elem):
    notes = []
    warnings = []
    returns = ""
    param_docs = {}
    code_examples = []

    if desc_elem is None:
        return "", param_docs, notes, warnings, returns, "", code_examples

    for child in desc_elem.findall(".//simplesect"):
        kind = child.get("kind")
        sect_text = clean_text(extract_text_recursive(child))
        if kind == "note":
            notes.append(sect_text)
        elif kind == "warning":
            warnings.append(sect_text)
        elif kind == "return":
            returns = sect_text

    for item in desc_elem.findall(".//parameteritem"):
        name_elem = item.find("parameternamelist/parametername")
        desc_elem_inner = item.find("parameterdescription")
        if name_elem is not None and desc_elem_inner is not None:
            param_name = extract_text_recursive(name_elem)
            param_desc = clean_text(extract_text_recursive(desc_elem_inner))
            param_docs[param_name] = param_desc

    # @code~@endcode 블록 추출 (<programlisting> 태그)
    for listing in desc_elem.findall(".//programlisting"):
        code_lines = []
        for codeline in listing.findall("codeline"):
            line_text = extract_text_recursive(codeline)
            code_lines.append(line_text)
        code_text = "\n".join(code_lines).strip()
        if code_text:
            code_examples.append(code_text)

    # Clean text without simplesect and parameterlist
    main_text = clean_text(extract_text_recursive(desc_elem, skip_tags=["simplesect", "parameterlist"]))

    since = ""
    since_match = re.search(r'@?SINCE_?([\d_\.]+)', main_text)
    if since_match:
        since = since_match.group(1).replace("_", ".")
        main_text = re.sub(r'\s*@?SINCE_?[\d_\.]+\s*', ' ', main_text).strip()

    return main_text, param_docs, notes, warnings, returns, since, code_examples

def parse_member(memberdef, api_dirs):
    kind = memberdef.get("kind")
    name = extract_text_recursive(memberdef.find("name"))
    
    # Extract file location to determine tier
    location = memberdef.find("location")
    api_tier = "unknown"
    file_path = ""
    if location is not None:
        file_path = location.get("file", "")
        for t in api_dirs:
            if t in file_path:
                api_tier = t.split("/")[-1]
                break

    brief_elem = memberdef.find("briefdescription")
    brief, _, _, _, _, brief_since, _ = parse_description(brief_elem)

    detailed_elem = memberdef.find("detaileddescription")
    detailed, param_docs, notes, warnings, returns, detailed_since, code_examples = parse_description(detailed_elem)
    
    since = brief_since if brief_since else detailed_since

    member_data = {
        "name": name,
        "kind": kind,
        "api_tier": api_tier,
        "brief": brief,
        "detailed": detailed,
    }

    if since:
        member_data["since"] = since
    if notes:
        member_data["notes"] = notes
    if warnings:
        member_data["warnings"] = warnings

    if kind == "typedef":
        # `using Alias = OriginalType` 선언의 원본 타입을 저장.
        # stage_c가 이를 읽어 alias 심볼(Text::FontWeight::BOLD 등)을 full_names에 등록한다.
        type_elem = memberdef.find("type")
        if type_elem is not None:
            aliased = "".join(type_elem.itertext()).strip()
            if aliased:
                member_data["aliased_type"] = aliased

    if kind == "enum":
        # named enum (non-anonymous)의 enumvalue를 저장.
        # stage_c DB 빌드 시 Class::VALUE 단축형 alias 등록에 사용된다.
        # (anonymous enum은 parse_compound에서 별도 처리되므로 여기는 named enum만 해당)
        enumvalues = []
        for ev in memberdef.findall("enumvalue"):
            ev_name = extract_text_recursive(ev.find("name"))
            if ev_name:
                ev_brief = ""
                ev_brief_elem = ev.find("briefdescription")
                if ev_brief_elem is not None:
                    ev_brief, _, _, _, _, _, _ = parse_description(ev_brief_elem)
                enumvalues.append({"name": ev_name, "brief": ev_brief})
        if enumvalues:
            member_data["enumvalues"] = enumvalues

    if kind == "function":
        type_elem = memberdef.find("type")
        args_elem = memberdef.find("argsstring")
        member_data["type"] = extract_text_recursive(type_elem)
        
        args = extract_text_recursive(args_elem)
        type_str = member_data['type'] + " " if member_data['type'] else ""
        member_data["signature"] = f"{type_str}{name}{args}"
        
        if returns:
            member_data["returns"] = returns
        
        params = []
        for param in memberdef.findall("param"):
            p_type = extract_text_recursive(param.find("type"))
            p_declname = extract_text_recursive(param.find("declname"))
            if not p_declname and extract_text_recursive(param.find("defname")):
                p_declname = extract_text_recursive(param.find("defname"))
            
            p_desc = param_docs.get(p_declname, "")
            params.append({
                "type": clean_text(p_type),
                "name": clean_text(p_declname),
                "description": p_desc
            })
        if params:
            member_data["params"] = params
        if code_examples:
            member_data["code_examples"] = code_examples

    return member_data

def extract_enum_synthetics(compounddef, namespace_name, api_dirs):
    """namespace compound에서 kind="enum" memberdef를 synthetic compound 목록으로 추출.

    Doxygen은 enum class를 별도 compound로 생성하지 않고 namespace compound의
    memberdef로 처리한다. 이 함수는 그런 enum memberdef를 독립 compound처럼 추출해
    feature_clusterer가 파일 경로 기반으로 올바른 feature에 라우팅할 수 있게 한다.
    """
    synthetics = []
    for sectiondef in compounddef.findall("sectiondef"):
        sec_kind = sectiondef.get("kind", "")
        if "private" in sec_kind or "internal" in sec_kind:
            continue
        for memberdef in sectiondef.findall("memberdef"):
            if memberdef.get("kind") != "enum":
                continue
            if memberdef.get("prot") == "private":
                continue

            enum_name = extract_text_recursive(memberdef.find("name"))
            qualified_name = f"{namespace_name}::{enum_name}"

            location = memberdef.find("location")
            file_path = ""
            api_tier = "unknown"
            if location is not None:
                file_path = location.get("file", "")
                for t in api_dirs:
                    if t in file_path:
                        api_tier = t.split("/")[-1]
                        break

            if not file_path:
                continue  # location 없으면 feature 라우팅 불가 — 스킵

            brief_elem = memberdef.find("briefdescription")
            brief, _, _, _, _, _, _ = parse_description(brief_elem)

            # enumvalue 자식 추출 (이름 + brief)
            members = []
            for ev in memberdef.findall("enumvalue"):
                ev_name = extract_text_recursive(ev.find("name"))
                ev_brief = ""
                ev_brief_elem = ev.find("briefdescription")
                if ev_brief_elem is not None:
                    ev_brief, _, _, _, _, _, _ = parse_description(ev_brief_elem)
                members.append({
                    "name": ev_name,
                    "kind": "enumvalue",
                    "brief": ev_brief,
                })

            synthetics.append({
                "name": qualified_name,
                "kind": "enum",
                "file": file_path,
                "api_tier": api_tier,
                "brief": brief,
                "detailed": "",
                "members": members,
                "synthetic": True,
            })

    return synthetics


def parse_compound(xml_path, api_dirs):
    tree = ET.parse(xml_path)
    root = tree.getroot()
    compounddef = root.find("compounddef")
    if compounddef is None:
        return []

    compound_kind = compounddef.get("kind")
    compound_name = extract_text_recursive(compounddef.find("compoundname"))
    
    location = compounddef.find("location")
    api_tier = "unknown"
    file_path = ""
    if location is not None:
        file_path = location.get("file", "")
        for t in api_dirs:
            if t in file_path:
                api_tier = t.split("/")[-1]
                break

    brief_elem = compounddef.find("briefdescription")
    brief, _, _, _, _, brief_since, _ = parse_description(brief_elem)

    detailed_elem = compounddef.find("detaileddescription")
    detailed, _, notes, warnings, _, detailed_since, _ = parse_description(detailed_elem)

    since = brief_since if brief_since else detailed_since

    compound_data = {
        "name": compound_name,
        "kind": compound_kind,
        "file": file_path,
        "api_tier": api_tier,
        "brief": brief,
        "detailed": detailed,
        "members": []
    }
    
    if since:
        compound_data["since"] = since
    if notes:
        compound_data["notes"] = notes
    if warnings:
        compound_data["warnings"] = warnings

    # ── 상속 관계 추출 (Phase 1.5 taxonomy_reviewer 용) ──────────────
    base_classes = []
    for base_ref in compounddef.findall("basecompoundref"):
        base_name = (base_ref.text or "").strip()
        if base_name:
            base_classes.append(base_name)
    if base_classes:
        compound_data["base_classes"] = base_classes

    derived_classes = []
    for derived_ref in compounddef.findall("derivedcompoundref"):
        derived_name = (derived_ref.text or "").strip()
        if derived_name:
            derived_classes.append(derived_name)
    if derived_classes:
        compound_data["derived_classes"] = derived_classes
    # ─────────────────────────────────────────────────────────────────

    for sectiondef in compounddef.findall("sectiondef"):
        kind = sectiondef.get("kind")
        if "private" in kind or "internal" in kind:
            continue
        
        for memberdef in sectiondef.findall("memberdef"):
            prot = memberdef.get("prot")
            if prot == "private":
                continue

            mb_kind = memberdef.get("kind", "")
            mb_name = (extract_text_recursive(memberdef.find("name")) or "").strip()

            # ── 익명 enum 특수 처리 ─────────────────────────────────────────
            # struct Property { enum { SIZE, POSITION, ... }; } 패턴:
            # Doxygen은 익명 enum을 name=""인 memberdef로 기록하고,
            # 실제 값(SIZE, POSITION 등)은 하위 enumvalue로만 저장한다.
            # 빈 이름 그대로 members에 추가하면 DB에 등록할 수 없으므로,
            # enumvalue들을 부모 compound 이름 기준의 개별 member로 펼쳐서 추가한다.
            # 예: Dali::Actor::Property compound → members에 "SIZE", "POSITION" 추가
            #   → build_doxygen_symbol_set()이 "Dali::Actor::Property::SIZE"를 full_names에 등록
            if mb_kind == "enum" and not mb_name:
                # memberdef 자신의 location에서 api_tier 결정 (compound tier 폴백)
                mb_location = memberdef.find("location")
                mb_api_tier = api_tier  # default: inherit from compound
                if mb_location is not None:
                    mb_file_path = mb_location.get("file", "")
                    for t in api_dirs:
                        if t in mb_file_path:
                            mb_api_tier = t.split("/")[-1]
                            break

                for ev in memberdef.findall("enumvalue"):
                    ev_name = extract_text_recursive(ev.find("name"))
                    if not ev_name:
                        continue
                    ev_brief = ""
                    ev_brief_elem = ev.find("briefdescription")
                    if ev_brief_elem is not None:
                        ev_brief, _, _, _, _, _, _ = parse_description(ev_brief_elem)
                    compound_data["members"].append({
                        "name": ev_name,
                        "kind": "enumvalue",
                        "api_tier": mb_api_tier,
                        "brief": ev_brief,
                    })
                continue  # 빈 이름의 enum member 자체는 추가하지 않음
            # ───────────────────────────────────────────────────────────────

            member_data = parse_member(memberdef, api_dirs)
            compound_data["members"].append(member_data)

    # namespace compound의 경우 enum memberdef를 synthetic compound로 추출해 함께 반환
    if compound_kind == "namespace":
        synthetics = extract_enum_synthetics(compounddef, compound_name, api_dirs)
        return [compound_data] + synthetics

    return [compound_data]

def process_package(package_name, repo_config):
    xml_dir = CACHE_DOXYGEN_ROOT / package_name / "xml"
    index_path = xml_dir / "index.xml"
    
    if not index_path.exists():
        print(f"Skipping {package_name}: index.xml not found at {index_path}")
        return False
        
    print(f"Processing package: {package_name}")
    api_dirs = repo_config.get("api_dirs", [])
    
    tree = ET.parse(index_path)
    root = tree.getroot()
    
    results = {
        "package": package_name,
        "compounds": []
    }
    
    target_kinds = ["class", "struct", "namespace", "file"]
    
    total_parsed = 0
    for compound in root.findall("compound"):
        kind = compound.get("kind")
        if kind not in target_kinds:
            continue
            
        refid = compound.get("refid")
        compound_xml_path = xml_dir / f"{refid}.xml"
        
        if compound_xml_path.exists():
            parsed_list = parse_compound(compound_xml_path, api_dirs)
            if parsed_list:
                results["compounds"].extend(parsed_list)
                total_parsed += len(parsed_list)

    PARSED_DOXYGEN_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = PARSED_DOXYGEN_ROOT / f"{package_name}.json"
    
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
        
    print(f"Successfully processed {package_name}: {total_parsed} compounds saved to {out_path}")
    return True

def main():
    config = load_config()
    repos = config.get("repos", {})
    
    success_count = 0
    for repo_name, repo_info in repos.items():
        if process_package(repo_name, repo_info):
            success_count += 1
            
    print(f"\\nDoxygen parsing complete. Processed {success_count}/{len(repos)} packages.")

if __name__ == "__main__":
    main()
