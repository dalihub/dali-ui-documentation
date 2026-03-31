import os
import subprocess
import yaml
from pathlib import Path

def load_config():
    config_path = Path(__file__).parent.parent.parent / "config" / "repo_config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def generate_doxyfile(package_name: str, package_info: dict, output_dir: Path):
    """
    Generate a Doxyfile for the given package to extract XML and Call Graph.
    """
    base_dir = Path(__file__).parent.parent.parent
    repo_path = base_dir / package_info["path"]
    api_dirs = package_info.get("api_dirs", [])
    
    # Create input string (absolute paths)
    inputs = " ".join([str(repo_path / d) for d in api_dirs])
    
    doxyfile_content = f"""
PROJECT_NAME           = "{package_name}"
OUTPUT_DIRECTORY       = "{output_dir}"
INPUT                  = {inputs}
RECURSIVE              = YES
GENERATE_XML           = YES
XML_OUTPUT             = xml
GENERATE_HTML          = NO
GENERATE_LATEX         = NO
EXTRACT_ALL            = YES
EXTRACT_PRIVATE        = NO
EXTRACT_STATIC         = YES
MACRO_EXPANSION        = YES
EXPAND_ONLY_PREDEF     = YES
SEARCH_INCLUDES        = YES
INCLUDE_PATH           = {repo_path}
CALL_GRAPH             = YES
CALLER_GRAPH           = YES
HAVE_DOT               = YES
QUIET                  = YES
WARNINGS               = YES
"""
    doxyfile_path = output_dir / "Doxyfile"
    with open(doxyfile_path, "w", encoding="utf-8") as f:
        f.write(doxyfile_content)
    
    return doxyfile_path

def run_doxygen(package_name: str):
    config = load_config()
    package_info = config["repos"].get(package_name)
    if not package_info:
        print(f"Error: {package_name} not found in repo_config.yaml")
        return
    
    base_dir = Path(__file__).parent.parent.parent
    cache_dir = base_dir / "cache" / "doxygen_json" / package_name
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Generating Doxyfile for {package_name}...")
    doxyfile_path = generate_doxyfile(package_name, package_info, cache_dir)
    
    print(f"Running doxygen for {package_name} (this may take a while)...")
    try:
        subprocess.run(["doxygen", str(doxyfile_path)], cwd=cache_dir, check=True)
        print(f"Doxygen completed successfully for {package_name}. XML output is at {cache_dir / 'xml'}")
    except subprocess.CalledProcessError as e:
        print(f"Error running doxygen: {e}")
    except FileNotFoundError:
        print("Error: 'doxygen' command not found. Please install doxygen.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run Doxygen for DALi packages")
    parser.add_argument("--package", type=str, required=True, help="Package name (e.g., dali-core)")
    args = parser.parse_args()
    
    run_doxygen(args.package)
