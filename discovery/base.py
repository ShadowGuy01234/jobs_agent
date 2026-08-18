"""Abstract base class for all discovery connectors."""

import abc
import logging
from typing import List
from discovery.models import RawOpportunity, DiscoverySource

logger = logging.getLogger(__name__)


class BaseDiscoveryConnector(abc.ABC):
    """Base connector interface for discovery feeds and job boards."""

    source_name: DiscoverySource

    @abc.abstractmethod
    async def fetch_opportunities(self, limit: int = 20) -> List[RawOpportunity]:
        """Fetch and return normalized RawOpportunity items."""
        pass
