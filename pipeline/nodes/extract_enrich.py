"""Enrichment node: normalizes raw opportunity data and extracts company details."""

import logging
import re
from typing import Optional

from discovery.models import RawOpportunity
from pipeline.llm import LLMClient
from pipeline.schemas import EnrichedCompanyData

logger = logging.getLogger(__name__)


def clean_raw_company_name(name: str) -> str:
    """Strip news headlines and descriptors from company names."""
    cleaned = re.sub(
        r"^(Geospatial|AI|Fintech|SaaS|Edtech|Healthtech|Deeptech|Lend-tech|E-commerce)\s+(startup|firm|platform|company)\s+",
        "",
        name,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+raises\s+.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+secures\s+.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+\(India Tech\)$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+\(Product Hunt Launch\)$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


async def extract_and_enrich(
    opportunity: RawOpportunity, llm_client: Optional[LLMClient] = None
) -> EnrichedCompanyData:
    """Use fast LLM to extract structured company information and tech stack from raw content."""
    client = llm_client or LLMClient()
    cleaned_initial_name = clean_raw_company_name(opportunity.company.name or opportunity.title)

    prompt = f"""
Analyze the following startup/job opportunity and extract structured company details.

OPPORTUNITY TITLE: {opportunity.title}
SOURCE: {opportunity.source.value}
URL: {opportunity.url}
RAW COMPANY NAME: {opportunity.company.name} (Suggested clean name: {cleaned_initial_name})
RAW CONTENT / DESCRIPTION:
{opportunity.raw_content or opportunity.title}

Instructions:
1. Extract the CLEAN, official startup name (e.g. 'NeoGeo' or 'Rezolv', do NOT include words like 'Geospatial startup' or 'raises funding').
2. Identify the root domain/website (e.g. 'neogeoinfo.com', 'rezolv.in') if mentioned in the text.
3. Identify what the company actually builds (concise 1-sentence one-liner).
4. Extract the technical stack, programming languages, and infrastructure tools mentioned.
5. Infer the company stage (pre_seed, seed, series_a, series_b, series_c, growth, unknown).
6. Extract founder names or key executives (Founders, CEO, CTO, Head of Growth) if mentioned.
7. Determine if this company is operating in stealth.
"""

    enriched = await client.generate_structured(
        prompt=prompt,
        response_schema=EnrichedCompanyData,
        use_smart=False,
    )

    # Ensure clean name
    enriched.name = clean_raw_company_name(enriched.name)
    return enriched
