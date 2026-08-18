"""OpenRouter LLM Gateway client with structured output support."""

import json
import logging
from typing import Any, Dict, Optional, Type, TypeVar
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    """Unified OpenRouter LLM client supporting fast and smart reasoning models."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        fast_model: Optional[str] = None,
        smart_model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.OPENROUTER_API_KEY
        self.base_url = base_url or settings.OPENROUTER_BASE_URL
        self.fast_model = fast_model or settings.OPENROUTER_FAST_MODEL
        self.smart_model = smart_model or settings.OPENROUTER_SMART_MODEL

    def get_chat_model(
        self,
        model_name: str,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> ChatOpenAI:
        """Create a ChatOpenAI instance configured for OpenRouter."""
        headers = {
            "HTTP-Referer": "https://github.com/anurag/job_outreach",
            "X-Title": "Personal Job Outreach System",
        }
        return ChatOpenAI(
            model=model_name,
            api_key=self.api_key or "sk-dummy-key",
            base_url=self.base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            default_headers=headers,
        )

    def get_fast_llm(self, temperature: float = 0.1) -> ChatOpenAI:
        """Fast model for extraction, JSON formatting, and classification."""
        return self.get_chat_model(self.fast_model, temperature=temperature)

    def get_smart_llm(self, temperature: float = 0.3) -> ChatOpenAI:
        """Smart reasoning model for candidate fit scoring and hyper-personalized drafting."""
        return self.get_chat_model(self.smart_model, temperature=temperature)

    async def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        use_smart: bool = True,
        system_prompt: Optional[str] = None,
    ) -> T:
        """Generate structured JSON and parse into Pydantic model."""
        llm = self.get_smart_llm() if use_smart else self.get_fast_llm()

        schema_json = json.dumps(response_schema.model_json_schema(), indent=2)
        system = system_prompt or (
            "You are an expert technical recruiter, executive headhunter, and startup talent evaluator. "
            "Always return strictly valid JSON conforming exactly to the requested JSON schema. "
            "Do not include any conversational preamble or markdown code fence if possible; output raw JSON."
        )

        full_prompt = (
            f"{prompt}\n\n"
            f"REQUIRED OUTPUT JSON SCHEMA:\n{schema_json}\n\n"
            "Return ONLY the valid JSON object matching the schema above."
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": full_prompt},
        ]

        response = await llm.ainvoke(messages)
        content = response.content.strip()

        # Clean potential markdown wrapping ```json ... ```
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        try:
            data = json.loads(content)
            return response_schema.model_validate(data)
        except Exception as e:
            logger.error(f"Failed to parse LLM structured JSON: {e}\nRaw Content:\n{content}")
            raise ValueError(f"LLM did not return valid JSON for schema {response_schema.__name__}: {e}")
