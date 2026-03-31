import asyncio
import aiohttp
import sys
from pathlib import Path

# Add project root to sys.path to allow running as script
root_path = Path(__file__).parent.parent.parent
if str(root_path) not in sys.path:
    sys.path.append(str(root_path))

from src.config import settings
from src.logger import setup_logger

logger = setup_logger(__name__)

class LLMClient:
    def __init__(self, role: str = "think"):
        self.role = role
        if role == "think":
            self.settings = settings.think
        elif role == "instruct":
            self.settings = settings.instruct
        else:
            raise ValueError(f"Unknown role '{role}'. Must be 'think' or 'instruct'.")
        
        self.endpoint = self.settings.endpoint
        self.api_key = self.settings.api_key
        self.model = self.settings.model
        
    async def ping(self) -> bool:
        """
        Simple ping test to verify LLM API connectivity.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": "Ping"}],
            "max_tokens": 10
        }
        
        try:
            # Assume it's an OpenAI-compatible /chat/completions endpoint if it ends with /v1
            url = self.endpoint
            if not url.endswith("/chat/completions"):
                url = f"{url.rstrip('/')}/chat/completions"
                
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=5) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"Ping successful for {self.role} model. Response: {data['choices'][0]['message']['content']}")
                        return True
                    else:
                        text = await response.text()
                        logger.error(f"Ping failed for {self.role} model. Status: {response.status}, Error: {text}")
                        return False
        except Exception as e:
            logger.error(f"Ping failed for {self.role} model. Exception: {e}")
            return False

if __name__ == "__main__":
    async def main():
        think_client = LLMClient("think")
        instruct_client = LLMClient("instruct")
        
        logger.info(f"Think model endpoint: {think_client.endpoint}")
        logger.info(f"Instruct model endpoint: {instruct_client.endpoint}")
        
        print("Testing Think model...")
        await think_client.ping()
        
        print("Testing Instruct model...")
        await instruct_client.ping()

    asyncio.run(main())
