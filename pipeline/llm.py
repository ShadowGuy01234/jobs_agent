"""Unified LLM Gateway client supporting TokenRouter (GLM 5.3), OpenRouter, and Groq with structured output."""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel

from config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_PROVIDER_FAILOVER_ORDER = ("tokenrouter", "groq", "openrouter")
_GATEWAY_HEADERS = {
    "HTTP-Referer": "https://github.com/anurag/job_outreach",
    "X-Title": "Personal Job Outreach System",
}


def extract_json_from_text(text: str) -> str:
    """Robustly extract valid JSON from LLM output containing reasoning tags, markdown fences, or draft commentary."""
    if not text:
        return ""

    # 1. Clean closed thinking / reasoning tags (<think>...</think> or orphaned </think>)
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()
    if "</think>" in cleaned:
        cleaned = cleaned.split("</think>")[-1].strip()

    # 2. Extract content within markdown code fences ```json ... ``` or ``` ... ``` (search from end)
    fences = list(re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE))
    if fences:
        for fence in reversed(fences):
            candidate = fence.group(1).strip()
            try:
                json.loads(candidate)
                return candidate
            except Exception:
                pass

    # 3. Find valid JSON object by scanning '{' from bottom to top
    last_brace = cleaned.rfind("}")
    if last_brace != -1:
        brace_indices = [i for i, c in enumerate(cleaned) if c == "{"]
        for first_brace in reversed(brace_indices):
            if first_brace < last_brace:
                candidate = cleaned[first_brace : last_brace + 1].strip()
                try:
                    json.loads(candidate)
                    return candidate
                except Exception:
                    continue

    # 4. Find valid JSON array by scanning '[' from bottom to top
    last_bracket = cleaned.rfind("]")
    if last_bracket != -1:
        bracket_indices = [i for i, c in enumerate(cleaned) if c == "["]
        for first_bracket in reversed(bracket_indices):
            if first_bracket < last_bracket:
                candidate = cleaned[first_bracket : last_bracket + 1].strip()
                try:
                    json.loads(candidate)
                    return candidate
                except Exception:
                    continue

    # 5. Outermost fallback
    first_brace = cleaned.find("{")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return cleaned[first_brace : last_brace + 1].strip()

    return cleaned.strip()


class LLMClient:
    """Unified LLM client supporting TokenRouter, OpenRouter, and Groq providers."""

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        fast_model: Optional[str] = None,
        smart_model: Optional[str] = None,
    ):
        self.provider = (provider or settings.LLM_PROVIDER).lower()

        if self.provider == "tokenrouter":
            self.api_key = api_key or settings.TOKENROUTER_API_KEY or ""
            self.base_url = base_url or settings.TOKENROUTER_BASE_URL
            self.fast_model = fast_model or settings.TOKENROUTER_FAST_MODEL
            self.smart_model = smart_model or settings.TOKENROUTER_SMART_MODEL
        elif self.provider == "groq":
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
        if self.provider in ("openrouter", "tokenrouter"):
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
            timeout=90,  # fail fast on a stuck reasoning-model call instead of stalling
            # the hourly sweep (default SDK timeout is 10min) past its next scheduled run
            default_headers=headers if headers else None,
        )

    def get_openai_client(self) -> OpenAI:
        """Return an OpenAI client configured for the active provider and endpoint."""
        return OpenAI(
            base_url=self.base_url,
            api_key=self.api_key or "sk-dummy-key",
        )

    def get_async_openai_client(self) -> AsyncOpenAI:
        """Return an AsyncOpenAI client configured for the active provider and endpoint."""
        return AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key or "sk-dummy-key",
        )

    def get_fast_llm(self, temperature: float = 0.1) -> ChatOpenAI:
        """Fast model for extraction, JSON formatting, and classification."""
        return self.get_chat_model(self.fast_model, temperature=temperature)

    def get_smart_llm(self, temperature: float = 0.3) -> ChatOpenAI:
        """Smart reasoning model for candidate fit scoring and hyper-personalized drafting."""
        return self.get_chat_model(self.smart_model, temperature=temperature)

    def _provider_config(self, provider: str) -> tuple[str, str, str, str]:
        """Return (api_key, base_url, fast_model, smart_model) for a named provider."""
        p = provider.lower()
        if p == "tokenrouter":
            return (
                settings.TOKENROUTER_API_KEY or "",
                settings.TOKENROUTER_BASE_URL,
                settings.TOKENROUTER_FAST_MODEL,
                settings.TOKENROUTER_SMART_MODEL,
            )
        if p == "groq":
            return (
                settings.GROQ_API_KEY or "",
                settings.GROQ_BASE_URL,
                settings.GROQ_FAST_MODEL,
                settings.GROQ_SMART_MODEL,
            )
        return (
            settings.OPENROUTER_API_KEY or "",
            settings.OPENROUTER_BASE_URL,
            settings.OPENROUTER_FAST_MODEL,
            settings.OPENROUTER_SMART_MODEL,
        )

    def _build_fallback_chat_model(
        self, provider: str, use_smart: bool, temperature: float
    ) -> Optional[ChatOpenAI]:
        """Construct a ChatOpenAI instance for a configured fallback provider."""
        api_key, base_url, fast_model, smart_model = self._provider_config(provider)
        if not api_key or api_key.startswith("your_") or api_key.startswith("gsk_your_"):
            return None
        headers = (
            {
                "HTTP-Referer": "https://github.com/anurag/job_outreach",
                "X-Title": "Personal Job Outreach System",
            }
            if provider in ("openrouter", "tokenrouter")
            else None
        )
        return ChatOpenAI(
            model=smart_model if use_smart else fast_model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            timeout=90,
            default_headers=headers,
        )

    async def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        use_smart: bool = True,
        system_prompt: Optional[str] = None,
    ) -> T:
        """Generate structured JSON and parse into Pydantic model, failing over across configured providers."""
        primary_llm = self.get_smart_llm() if use_smart else self.get_fast_llm()

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

        fallback_order = [p for p in ("groq", "openrouter", "tokenrouter") if p != self.provider]
        attempts: List[tuple[str, ChatOpenAI]] = [(self.provider, primary_llm)]
        temperature = getattr(primary_llm, "temperature", 0.3 if use_smart else 0.1)
        for prov in fallback_order:
            fb = self._build_fallback_chat_model(prov, use_smart=use_smart, temperature=temperature)
            if fb is not None:
                attempts.append((prov, fb))

        last_error: Optional[Exception] = None
        for idx, (prov_name, llm) in enumerate(attempts):
            try:
                response = await llm.ainvoke(messages)
                raw_content = (response.content or "").strip()
                extracted_json = extract_json_from_text(raw_content)
                data = json.loads(extracted_json)
                return response_schema.model_validate(data)
            except Exception as e:
                last_error = e
                has_next = idx + 1 < len(attempts)
                model_label = getattr(llm, "model_name", "unknown")
                if has_next:
                    next_prov = attempts[idx + 1][0]
                    logger.warning(
                        f"LLM call failed on {prov_name}/{model_label} ({type(e).__name__}: {e}). "
                        f"Failing over to {next_prov}..."
                    )
                else:
                    logger.error(
                        f"Failed LLM structured JSON on {prov_name}/{model_label}: {e}"
                    )

        raise ValueError(
            f"All configured LLM providers failed for schema {response_schema.__name__}: {last_error}"
        )
