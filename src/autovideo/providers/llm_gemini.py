import os
import time

from google import genai
from google.genai import errors, types

RETRYABLE = {429, 500, 503}


class GeminiLLM:
    def __init__(self, model: str, max_retries: int = 3, base_delay: float = 15.0):
        self.model = model
        self.max_retries = max_retries
        self.base_delay = base_delay

    def generate_json(self, system: str, prompt: str, schema: dict) -> str:
        # Checked here, not in __init__, so jobs that already have a script run without a key.
        if not self.model:
            raise ValueError("ยังไม่ได้ตั้งค่า llm.model ใน config.yaml")
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise ValueError("ยังไม่ได้ใส่ GEMINI_API_KEY ใน .env")
        client = genai.Client(api_key=key)
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
        )
        for attempt in range(self.max_retries + 1):
            try:
                resp = client.models.generate_content(model=self.model, contents=prompt, config=config)
                return resp.text or ""
            except errors.APIError as e:
                if e.code not in RETRYABLE or attempt == self.max_retries:
                    raise
                # Free-tier quota (429) resets per minute; back off 15s, 30s, 60s...
                time.sleep(self.base_delay * 2**attempt)
