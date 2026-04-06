import os
import time
import json
import yaml
import requests
import urllib3
from pathlib import Path
from collections import deque

# Disable SSL warnings for internal networks with self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Absolute Path Context Setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "doc_config.yaml"


SESSION_STATS_PATH = PROJECT_ROOT / "cache" / "llm_session_stats.json"


def estimate_prompt_tokens(text):
    """프롬프트 문자열의 토큰 수를 근사 추정한다 (chars / 3.5)."""
    return int(len(text) / 3.5)


def _record_session_stats(input_tokens):
    """
    세션 통계 파일에 입력 토큰 수와 요청 횟수를 누적한다.
    subprocess 경계를 넘어 pipeline.py가 최종 집계할 수 있도록 파일 기반으로 공유한다.
    실패해도 파이프라인을 중단하지 않는다.
    """
    try:
        if SESSION_STATS_PATH.exists():
            with open(SESSION_STATS_PATH, "r", encoding="utf-8") as f:
                stats = json.load(f)
        else:
            stats = {"total_input_tokens": 0, "total_requests": 0}
        stats["total_input_tokens"] += input_tokens
        stats["total_requests"] += 1
        SESSION_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SESSION_STATS_PATH, "w", encoding="utf-8") as f:
            json.dump(stats, f)
    except Exception:
        pass


class TokenRateLimiter:
    """
    슬라이딩 윈도우 기반 분당 입력 토큰 제한기.

    각 LLM 호출 전에 wait_if_needed()를 호출하면,
    최근 60초간 전송한 토큰 합계가 한도를 초과하지 않도록 자동으로 대기한다.
    호출 후 record_actual()로 실제 토큰 수를 업데이트한다.
    """

    def __init__(self, tokens_per_minute):
        self.tokens_per_minute = tokens_per_minute
        # deque 항목: (send_time: float, token_count: int)
        self._window = deque()

    def _evict_expired(self):
        now = time.time()
        while self._window and now - self._window[0][0] >= 60:
            self._window.popleft()

    def used_tokens(self):
        self._evict_expired()
        return sum(c for _, c in self._window)

    def wait_if_needed(self, estimated_tokens):
        """
        한도 초과 시 가장 오래된 항목이 만료될 때까지 대기한 뒤 슬롯을 예약한다.
        예약된 슬롯은 record_actual()로 실제값으로 교체된다.
        """
        while True:
            self._evict_expired()
            used = self.used_tokens()
            remaining = self.tokens_per_minute - used

            if estimated_tokens <= remaining:
                break

            # 가장 오래된 항목이 만료될 때까지의 대기 시간 계산
            oldest_time = self._window[0][0]
            wait_sec = max(0.5, (oldest_time + 60) - time.time() + 0.5)
            print(f"  [Token Limiter] Used {used:,}/{self.tokens_per_minute:,} tok/min. "
                  f"Need {estimated_tokens:,} more. Waiting {wait_sec:.1f}s...")
            time.sleep(wait_sec)

        # 예약 슬롯 추가 (실제값 수신 전 플레이스홀더)
        self._window.append((time.time(), estimated_tokens))

    def record_actual(self, actual_tokens):
        """
        API 응답에서 얻은 실제 토큰 수로 마지막 예약 슬롯을 업데이트한다.
        추정값과 실제값의 오차를 보정해 다음 호출의 대기 시간 계산을 정확하게 한다.
        """
        if self._window:
            send_time, _ = self._window[-1]
            self._window[-1] = (send_time, actual_tokens)


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
        
        # 고정 딜레이 (0이면 비활성)
        self.delay_sec = self.settings.get("rate_limit_delay_sec", 4)
        self.max_retries = self.settings.get("max_retries", 3)

        # 토큰 기반 분당 제한 (설정된 경우)
        tpm = self.settings.get("tokens_per_minute", 0)
        self.token_limiter = TokenRateLimiter(tpm) if tpm > 0 else None

        # 최소 대기 기준 시각 (첫 호출은 대기 없이 바로 실행)
        self._last_call_time = 0.0
        
        # Assign configured credentials
        key_env_var = self.settings.get("api_key_env", "")
        self.api_key = os.environ.get(key_env_var, "")
        if not self.api_key:
            print(f"Warning: Authentication API Key '{key_env_var}' not found in current environment variables.")

    def _call_gemini(self, prompt, model_name):
        """
        Private dispatcher routing standard requests toward Google AI Endpoints.
        Returns (text, actual_input_tokens).
        """
        url = f"{self.api_base}/{model_name}:generateContent?key={self.api_key}"
        headers = {'Content-Type': 'application/json'}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }

        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        res_json = response.json()

        # 실제 토큰 수 추출 (Gemini usageMetadata)
        usage = res_json.get("usageMetadata", {})
        actual_input_tokens = usage.get("promptTokenCount", 0)
        actual_output_tokens = usage.get("candidatesTokenCount", 0)
        if actual_input_tokens:
            print(f"  [Token Usage] input={actual_input_tokens:,}  output={actual_output_tokens:,}  "
                  f"total={actual_input_tokens + actual_output_tokens:,}")

        try:
            text = res_json["candidates"][0]["content"]["parts"][0]["text"]
            return text, actual_input_tokens
        except (KeyError, IndexError):
            return f"Error extracting Gemini Content payload: {res_json}", actual_input_tokens

    def _call_internal(self, prompt, model_name, use_think=False):
        """
        Private dispatcher routing toward Internal Custom OpenAI format clusters.
        Supports Shuttle API with Basic Auth and per-model endpoints.
        Returns (text, actual_input_tokens).
        """
        if self.think_endpoint and self.instruct_endpoint:
            endpoint = self.think_endpoint if use_think else self.instruct_endpoint
            url = f"{self.api_base}/{endpoint}/v1/chat/completions"
        else:
            url = f"{self.api_base}/v1/chat/completions"

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

        # 실제 토큰 수 추출 (OpenAI-compatible usage 필드)
        usage = res_json.get("usage", {})
        actual_input_tokens = usage.get("prompt_tokens", 0)
        actual_output_tokens = usage.get("completion_tokens", 0)
        if actual_input_tokens:
            print(f"  [Token Usage] input={actual_input_tokens:,}  output={actual_output_tokens:,}  "
                  f"total={actual_input_tokens + actual_output_tokens:,}")

        try:
            text = res_json["choices"][0]["message"]["content"]
            return text, actual_input_tokens
        except (KeyError, IndexError):
            return f"Error parsing internal payload data: {res_json}", actual_input_tokens

    def generate(self, prompt, use_think=False):
        """
        Exposed public method simplifying generation requests while hiding limits.
        토큰 기반 분당 제한이 설정된 경우 호출 전 자동으로 대기한다.
        """
        model_name = self.think_model if use_think else self.instruct_model

        # 1. 최소 대기 (rate_limit_delay_sec) — 항상 적용
        if self.delay_sec > 0:
            elapsed = time.time() - self._last_call_time
            remaining = self.delay_sec - elapsed
            if remaining > 0:
                print(f"  [LLM Guard] Minimum delay: waiting {remaining:.1f}s...")
                time.sleep(remaining)

        # 2. 토큰 기반 분당 제한 — 설정된 경우 추가로 적용
        estimated_tokens = estimate_prompt_tokens(prompt)
        if self.token_limiter:
            print(f"  [Token Limiter] Estimated input tokens: {estimated_tokens:,} "
                  f"(window used: {self.token_limiter.used_tokens():,}/{self.token_limiter.tokens_per_minute:,})")
            self.token_limiter.wait_if_needed(estimated_tokens)

        self._last_call_time = time.time()

        for attempt in range(self.max_retries):
            try:
                print(f"  [LLM Network] Firing prompt across '{self.env}' environment using '{model_name}' (Attempt {attempt+1}/{self.max_retries})...")

                if self.env == "external":
                    response_text, actual_tokens = self._call_gemini(prompt, model_name)
                else:
                    response_text, actual_tokens = self._call_internal(prompt, model_name, use_think)

                # 실제 토큰 수로 슬롯 업데이트 (다음 호출의 대기 계산 정확도 향상)
                if self.token_limiter and actual_tokens > 0:
                    self.token_limiter.record_actual(actual_tokens)

                # 세션 통계 누적 (실제값 우선, 없으면 추정값)
                _record_session_stats(actual_tokens if actual_tokens > 0 else estimated_tokens)

                return response_text

            except requests.exceptions.HTTPError as http_err:
                status = http_err.response.status_code
                print(f"  [LLM Protocol Error] Server rejected request: {status}")
                print(f"  Details: {http_err.response.text}")

                # 429: 서버가 알려주는 retry-after를 우선 사용
                if status == 429 and self.token_limiter:
                    try:
                        err_body = http_err.response.json()
                        retry_delay = (err_body.get("error", {})
                                               .get("details", [{}])[-1]
                                               .get("retryDelay", "10s"))
                        wait_sec = int(retry_delay.replace("s", "")) + 2
                    except Exception:
                        wait_sec = 30
                    print(f"  [Token Limiter] 429 received. Waiting {wait_sec}s before retry...")
                    time.sleep(wait_sec)
                    continue

            except Exception as e:
                print(f"  [LLM System Error] Critical pipeline execution fault: {e}")

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
