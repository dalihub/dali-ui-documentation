import os
import time
import json
import yaml
import requests
import urllib3
from pathlib import Path

# Disable SSL warnings for internal networks with self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Absolute Path Context Setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "doc_config.yaml"

def load_env():
    """
    Manually parses a strict .env file to inject variables 
    without needing external libraries like python-dotenv.
    """
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip() and not line.startswith("#"):
                    parts = line.strip().split("=", 1)
                    if len(parts) == 2:
                        os.environ[parts[0]] = parts[1]

class LLMClient:
    def __init__(self):
        load_env()
        
        # Load environment routing map
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            
        self.env = config.get("llm_environment", "external")
        self.settings = config.get("models", {}).get(self.env, {})
        
        self.api_base = self.settings.get("api_base")
        self.think_model = self.settings.get("think")
        self.instruct_model = self.settings.get("instruct")
        
        # Shuttle API uses separate endpoints per model type
        self.think_endpoint = self.settings.get("think_endpoint", "")
        self.instruct_endpoint = self.settings.get("instruct_endpoint", "")
        
        # Auth type: "basic" for Shuttle API, "bearer" for others
        self.auth_type = self.settings.get("auth_type", "bearer")
        
        # Pull defensive limits (Rate Limiting)
        self.delay_sec = self.settings.get("rate_limit_delay_sec", 4)
        self.max_retries = self.settings.get("max_retries", 3)
        
        # Assign configured credentials
        key_env_var = self.settings.get("api_key_env", "")
        self.api_key = os.environ.get(key_env_var, "")
        if not self.api_key:
            print(f"Warning: Authentication API Key '{key_env_var}' not found in current environment variables.")

    def _call_gemini(self, prompt, model_name):
        """
        Private dispatcher routing standard requests toward Google AI Endpoints.
        """
        url = f"{self.api_base}/{model_name}:generateContent?key={self.api_key}"
        headers = {'Content-Type': 'application/json'}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        
        res_json = response.json()
        try:
            return res_json["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            return f"Error extracting Gemini Content payload: {res_json}"

    def _call_internal(self, prompt, model_name, use_think=False):
        """
        Private dispatcher routing toward Internal Custom OpenAI format clusters.
        Supports Shuttle API with Basic Auth and per-model endpoints.
        """
        # Determine endpoint based on model type (Shuttle API uses separate endpoints)
        if self.think_endpoint and self.instruct_endpoint:
            endpoint = self.think_endpoint if use_think else self.instruct_endpoint
            url = f"{self.api_base}/{endpoint}/v1/chat/completions"
        else:
            url = f"{self.api_base}/v1/chat/completions"
        
        # Set authorization header based on auth_type
        if self.auth_type == "basic":
            auth_header = f'Basic {self.api_key}'
        else:
            auth_header = f'Bearer {self.api_key}'
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': auth_header
        }
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=120, verify=False)
        response.raise_for_status()
        
        res_json = response.json()
        try:
            return res_json["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            return f"Error parsing internal payload data: {res_json}"

    def generate(self, prompt, use_think=False):
        """
        Exposed public method simplifying generation requests while hiding limits.
        """
        # Determine strict persona selection
        model_name = self.think_model if use_think else self.instruct_model
        
        for attempt in range(self.max_retries):
            try:
                # 1. Mandatory Rate Limiting Pause Barrier
                if self.delay_sec > 0:
                    print(f"  [LLM Guard] Rate limiting active: pausing execution for {self.delay_sec} seconds...")
                    time.sleep(self.delay_sec)
                    
                # 2. Execution Routing Log
                print(f"  [LLM Network] Firing prompt across '{self.env}' environment using '{model_name}' (Attempt {attempt+1}/{self.max_retries})...")
                
                # Dynamic Routing
                if self.env == "external":
                    response_text = self._call_gemini(prompt, model_name)
                else:
                    response_text = self._call_internal(prompt, model_name, use_think)
                    
                return response_text
                
            except requests.exceptions.HTTPError as http_err:
                print(f"  [LLM Protocol Error] Server rejected request: {http_err.response.status_code}")
                print(f"  Details: {http_err.response.text}")
                
            except Exception as e:
                print(f"  [LLM System Error] Critical pipeline execution fault: {e}")
                
            # If a strict failure happens, gracefully escalate Backoff
            backoff_penalty = (attempt + 1) * 5 
            print(f"  [LLM Defense Mechanism] Engine failure. Backing off for {backoff_penalty} seconds before retrying...")
            time.sleep(backoff_penalty)
            
        return "FATAL ERROR: LLM Generation failed un-recoverably after maximum retry iterations."

if __name__ == "__main__":
    # Internal component debugging suite
    print("Initialize LLM Client Subsystem Interface...")
    try:
        client = LLMClient()
        print(f"Environment Mode Detected: {client.env}")
        print(f"Delay Threshold Check:     {client.delay_sec} seconds")
        
        print("\nFiring Sandbox Test 1 (Basic Instruct Payload)...")
        res1 = client.generate("Please say exactly 'Hello DALi Phase 2' and nothing else.")
        print(f"  > Received Output: {res1.strip()}")
        
        print("\nFiring Sandbox Test 2 (Complex Think Analytics Protocol)...")
        res2 = client.generate("Please logic check this sentence: 'Water is very dry.' Output only your verdict (True or False) and why, concisely.", use_think=True)
        print(f"  > Received Output: {res2.strip()}")
        
    except Exception as e:
        print(f"Catastrophic test failure directly within client runtime: {e}")
