"""Unified LLM Gateway client supporting OpenRouter and Groq with structured output."""

import json
import logging
import re
from typing import Any, Dict, Optional, Type, TypeVar
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def extract_json_from_text(text: str) -> str:
    """Robustly extract valid JSON from LLM output containing reasoning tags, markdown fences, or preamble."""
    if not text:
        return ""

    # 1. Remove thinking / reasoning tags (<think>...</think> or orphaned </think>)
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()
    if "</think>" in cleaned:
        cleaned = cleaned.split("</think>")[-1].strip()

    # 2. Extract content within markdown code fences ```json ... ``` or ``` ... ```
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()

    # 3. Extract outermost JSON object { ... }
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return cleaned[first_brace : last_brace + 1].strip()

    # 4. Extract outermost JSON array [ ... ]
    first_bracket = cleaned.find("[")
    last_bracket = cleaned.rfind("]")
    if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
        return cleaned[first_bracket : last_bracket + 1].strip()

    return cleaned.strip()


class LLMClient:
    """Unified LLM client supporting OpenRouter and Groq providers."""

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        fast_model: Optional[str] = None,
        smart_model: Optional[str] = None,
    ):
        self.provider = (provider or settings.LLM_PROVIDER).lower()

        if self.provider == "groq":
            self.api_key = api_key or settings.GROQ_API_KEY or ""
            self.base_url = base_url or settings.GROQ_BASE_URL
            self.fast_model = fast_model or settings.GROQ_FAST_MODEL
            self.smart_model = smart_model or settings.GROQ_SMART_MODEL
        else:
            # Default to OpenRouter
            self.provider = "openrouter"
            self.api_key = api_key or settings.OPENROUTER_API_KEY or ""
            self.base_url = base_url or settings.OPENROUTER_BASE_URL
            self.fast_model = fast_model or settings.OPENROUTER_FAST_MODEL
            self.smart_model = smart_model or settings.OPENROUTER_SMART_MODEL

    def get_chat_model(
        self,
        model_name: str,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> ChatOpenAI:
        """Create a ChatOpenAI instance configured for the active provider."""
        headers = {}
        if self.provider == "openrouter":
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
            default_headers=headers if headers else None,
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
        raw_content = response.content.strip()

        # Clean reasoning tokens (<think>...</think>), markdown fences, preamble
        extracted_json = extract_json_from_text(raw_content)

        try:
            data = json.loads(extracted_json)
            return response_schema.model_validate(data)
        except Exception as e:
            logger.error(
                f"Failed to parse LLM structured JSON ({self.provider}/{llm.model_name}): {e}\n"
                f"Extracted JSON:\n{extracted_json}\n"
                f"Raw Content:\n{raw_content}"
            )
            raise ValueError(
                f"LLM did not return valid JSON for schema {response_schema.__name__}: {e}"
            )
