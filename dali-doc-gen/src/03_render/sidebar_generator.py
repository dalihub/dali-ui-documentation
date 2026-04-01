import os
import json
import argparse
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = PROJECT_ROOT / "cache"
TAXONOMY_PATH = CACHE_DIR / "feature_taxonomy" / "feature_taxonomy.json"

APP_GUIDE_OUT = PROJECT_ROOT / "output" / "app-guide"
PLATFORM_GUIDE_OUT = PROJECT_ROOT / "output" / "platform-guide"

def load_json(path):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def build_sidebar(taxonomy, docs_dir):
    """
    Docusaurus v3 formats Sidebars as a JSON object:
    {
      "daliSidebar": [ ...items... ]
    }
    """
    if not docs_dir.exists():
        print(f"Docs directory {docs_dir} not found. Returning empty layout.")
        return []

    # Only include MD files that were actually generated in this tier
    valid_doc_ids = {p.stem for p in docs_dir.glob("*.md")}
    sidebar_items = []

    # Collect all root features (parent == null or empty)
    roots = [k for k, v in taxonomy.items() if not v.get("parent")]

    # Sort roots by display_name or ID for consistent ordering (alphabetical)
    roots.sort(key=lambda k: taxonomy[k].get("display_name", k).lower())

    for root_id in roots:
        tax_info = taxonomy[root_id]
        display_name = tax_info.get("display_name", root_id.title())
        children = tax_info.get("children", [])

        # Filter valid children that successfully compiled to .md
        valid_children = [c for c in children if c in valid_doc_ids]
        
        # Sort children alphabetically by display_name
        valid_children.sort(key=lambda c: taxonomy.get(c, {}).get("display_name", c).lower())

        is_root_valid = root_id in valid_doc_ids

        # If it has children (tree structure), turn into a category
        if valid_children:
            category = {
                "type": "category",
                "label": display_name,
                "items": valid_children
            }
            # If the parent document also exists, make the category text itself clickable
            if is_root_valid:
                category["link"] = {"type": "doc", "id": root_id}

            sidebar_items.append(category)
        else:
            # Flat feature (or its children didn't pass tier validation)
            if is_root_valid:
                sidebar_items.append(root_id)

    return sidebar_items

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", type=str, choices=["app", "platform"], default="app", help="Target output tier")
    args = parser.parse_args()

    print("=================================================================")
    print(f" Sidebar Generator: Building navigation for '{args.tier}-guide'    ")
    print("=================================================================")

    taxonomy = load_json(TAXONOMY_PATH)
    if not taxonomy:
        print("Error: feature_taxonomy.json missing. Cannot build sidebar.")
        return

    output_dir = APP_GUIDE_OUT if args.tier == "app" else PLATFORM_GUIDE_OUT
    output_dir.mkdir(parents=True, exist_ok=True)
    docs_dir = output_dir / "docs"
    
    sidebar_items = build_sidebar(taxonomy, docs_dir)

    # Wrap in Docusaurus top-level object alias
    # This structure maps easily into Docusaurus `sidebars.js`
    sidebar_container = {
        "tutorialSidebar": sidebar_items
    }

    # Write to sidebar.json
    out_file = output_dir / "sidebar.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(sidebar_container, f, indent=2, ensure_ascii=False)

    print(f"[Sidebar] Sidebar mapping created: {out_file}")
    print(f"[Sidebar] Total category/doc items placed at root level: {len(sidebar_items)}")
    print("=================================================================")

if __name__ == "__main__":
    main()
