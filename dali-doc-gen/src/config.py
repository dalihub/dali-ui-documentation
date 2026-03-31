import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml

def load_yaml_config(file_name: str) -> dict:
    config_path = Path(__file__).parent.parent / "config" / file_name
    if not config_path.exists():
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

llm_data = load_yaml_config("llm_config.yaml").get("llm", {})

class LLMSettings(BaseSettings):
    endpoint: str = ""
    model: str = ""
    api_key: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096

class ThinkSettings(LLMSettings):
    endpoint: str = llm_data.get("think", {}).get("endpoint", "http://localhost:8080/v1")
    model: str = llm_data.get("think", {}).get("model", "dummy-think")
    api_key: str = llm_data.get("think", {}).get("api_key", "dummy")
    temperature: float = llm_data.get("think", {}).get("temperature", 0.7)
    
    model_config = SettingsConfigDict(env_prefix="LLM_THINK_")

class InstructSettings(LLMSettings):
    endpoint: str = llm_data.get("instruct", {}).get("endpoint", "http://localhost:8080/v1")
    model: str = llm_data.get("instruct", {}).get("model", "dummy-instruct")
    api_key: str = llm_data.get("instruct", {}).get("api_key", "dummy")
    temperature: float = llm_data.get("instruct", {}).get("temperature", 0.3)
    
    model_config = SettingsConfigDict(env_prefix="LLM_INSTRUCT_")

class Settings(BaseSettings):
    think: ThinkSettings = ThinkSettings()
    instruct: InstructSettings = InstructSettings()
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
