import os
import json
import yaml
import argparse
from pathlib import Path
import git

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "repo_config.yaml"
CACHE_PARSED_DIR = PROJECT_ROOT / "cache" / "parsed_doxygen"

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def get_changed_files(repo_path, from_commit, to_commit):
    try:
        if not (repo_path / ".git").exists():
            print(f"Directory {repo_path} is not a git repository.")
            return []
            
        repo = git.Repo(repo_path)
        # return list of modified files
        diffs = repo.git.diff("--name-only", from_commit, to_commit)
        if not diffs:
            return []
        # Exclude empty strings
        return [f.strip() for f in diffs.strip().split('\n') if f.strip()]
    except git.exc.GitCommandError as ge:
        print(f"Git command error in {repo_path}: {ge}")
        return []
    except Exception as e:
        print(f"Error checking git diff in {repo_path}: {e}")
        return []

def extract_changed_apis(package_name, changed_files):
    parsed_json_path = CACHE_PARSED_DIR / f"{package_name}.json"
    if not parsed_json_path.exists():
        print(f"Parsed JSON not found for {package_name} at {parsed_json_path}")
        return []
        
    with open(parsed_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    changed_apis = []
    compounds = data.get("compounds", [])
    
    # We check if the compound's 'file' matches any changed file
    for compound in compounds:
        c_file = compound.get("file", "")
        if not c_file:
            continue
            
        is_changed = False
        # The file paths in doxygen json are typically absolute inside the environment
        # or relative. Git diff returns paths relative to the repo root.
        # Checking substring is a robust way to match Git paths against Doxygen parsed paths.
        for chf in changed_files:
            if chf in c_file:
                is_changed = True
                break
                
        if is_changed:
            changed_apis.append({
                "name": compound.get("name"),
                "kind": compound.get("kind"),
                "api_tier": compound.get("api_tier", "unknown")
            })
            
    return changed_apis

def main():
    parser = argparse.ArgumentParser(description="Extract changed APIs based on Git Diff")
    parser.add_argument("--from-commit", type=str, default="HEAD~5", help="Previous commit or tag (default: HEAD~5)")
    parser.add_argument("--to-commit", type=str, default="HEAD", help="Current commit or tag (default: HEAD)")
    parser.add_argument("--package", type=str, help="Specific package to check (e.g., dali-core). If omitted, runs all.")
    args = parser.parse_args()
    
    config = load_config()
    repos = config.get("repos", {})
    
    packages_to_check = [args.package] if args.package else repos.keys()
    
    all_changes = {}
    
    for pkg in packages_to_check:
        if pkg not in repos:
            print(f"Warning: {pkg} not registered in repo_config.yaml")
            continue
            
        repo_info = repos[pkg]
        repo_path = PROJECT_ROOT / repo_info.get("path", "")
        
        print(f"Detecting differences in {pkg} ({args.from_commit} .. {args.to_commit})")
        changed_files = get_changed_files(repo_path, args.from_commit, args.to_commit)
        
        if changed_files:
            print(f"  Found {len(changed_files)} changed files in Git.")
            apis = extract_changed_apis(pkg, changed_files)
            all_changes[pkg] = apis
            print(f"  Mapped to {len(apis)} API compounds.")
        else:
            print("  No files changed or invalid commit range.")
            all_changes[pkg] = []
            
    # Save the output to root cache/ folder so it's ignored by Git but accessible pipeline-wide  
    out_path = PROJECT_ROOT / "cache" / "changed_apis.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_changes, f, indent=2, ensure_ascii=False)
        
    print(f"\\nChanged APIs summary saved to {out_path}")

if __name__ == "__main__":
    main()
