import os
import sys
import yaml
from pathlib import Path
import git

# Add project root to sys.path to allow running as script
root_path = Path(__file__).parent.parent.parent
if str(root_path) not in sys.path:
    sys.path.append(str(root_path))

from src.logger import setup_logger

logger = setup_logger(__name__)

def load_repo_config():
    config_path = root_path / "config" / "repo_config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def manage_repos():
    config = load_repo_config()
    repos = config.get("repos", {})
    
    for package_name, info in repos.items():
        url = info.get("url")
        branch = info.get("branch", "master")
        rel_path = info.get("path")
        
        if not url or not rel_path:
            logger.warning(f"Skipping {package_name}: Missing 'url' or 'path' in config.")
            continue
        
        # Resolve target path relative to dali-doc-gen root
        target_path = root_path / rel_path
        
        try:
            if (target_path / ".git").exists():
                logger.info(f"Repository {package_name} already exists at {target_path}. Updating...")
                repo = git.Repo(target_path)
                origin = repo.remotes.origin
                origin.fetch()
                
                # Checkout and pull
                repo.git.checkout(branch)
                origin.pull(branch)
                
                logger.info(f"Successfully updated {package_name} (branch: {branch}).")
            else:
                logger.info(f"Cloning {package_name} from {url} (branch: {branch}) into {target_path}...")
                target_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Clone specific branch natively
                git.Repo.clone_from(url, target_path, branch=branch)
                
                logger.info(f"Successfully cloned {package_name}.")
                
        except Exception as e:
            logger.error(f"Failed to manage repository {package_name}: {e}")

if __name__ == "__main__":
    manage_repos()
