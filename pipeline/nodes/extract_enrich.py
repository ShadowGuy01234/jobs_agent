"""Enrichment node: normalizes raw opportunity data and extracts company details."""

import logging
from typing import Optional

from discovery.models import RawOpportunity
from pipeline.llm import LLMClient
from pipeline.schemas import EnrichedCompanyData

logger = logging.getLogger(__name__)


async def extract_and_enrich(
    opportunity: RawOpportunity, llm_client: Optional[LLMClient] = None
) -> EnrichedCompanyData:
    """Use fast LLM to extract structured company information and tech stack from raw content."""
    client = llm_client or LLMClient()

    prompt = f"""
Analyze the following startup/job opportunity and extract structured company details.

OPPORTUNITY TITLE: {opportunity.title}
SOURCE: {opportunity.source.value}
URL: {opportunity.url}
COMPANY NAME: {opportunity.company.name}
RAW CONTENT / DESCRIPTION:
{opportunity.raw_content or opportunity.title}

Instructions:
1. Identify what the company actually builds (concise 1-sentence one-liner).
2. Extract the technical stack, programming languages, and infrastructure tools mentioned.
3. Infer the company stage (pre_seed, seed, series_a, series_b, series_c, growth, unknown).
4. Extract founder names or key executives if mentioned in the text.
5. Determine if this company is operating in stealth.
"""

    return await client.generate_structured(
        prompt=prompt,
        response_schema=EnrichedCompanyData,
        use_smart=False,
    )
