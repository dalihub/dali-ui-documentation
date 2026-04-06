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

def load_environment():
    """git clone에 사용할 환경(internal/external)을 결정한다.

    우선순위:
    1. CI=true  → 항상 external (GitHub Actions에서 SSH 키 없음)
    2. DALI_LLM_ENV 환경변수 → pipeline.py --llm 인자에서 설정
    3. doc_config.yaml llm_environment
    4. 기본값 external
    """
    # CI 환경에서는 항상 external (git clone 기준)
    if os.environ.get("CI", "").lower() == "true":
        return "external"

    # pipeline.py --llm 인자 전달용 환경변수
    env_override = os.environ.get("DALI_LLM_ENV")
    if env_override:
        return env_override

    doc_config_path = root_path / "config" / "doc_config.yaml"
    try:
        with open(doc_config_path, "r", encoding="utf-8") as f:
            doc_config = yaml.safe_load(f)
        return doc_config.get("llm_environment", "external")
    except Exception:
        return "external"

def manage_repos():
    config = load_repo_config()
    repos = config.get("repos", {})
    env = load_environment()
    logger.info(f"Repository environment: {env}")

    for package_name, info in repos.items():
        url = info.get(f"{env}_url") or info.get("url")
        branch = info.get(f"{env}_branch") or info.get("branch", "master")
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
