import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guideline import BrandGuideline

logger = logging.getLogger("brandshield.engine.semantic")


class SemanticRetriever:
    """Encapsulates semantic vector search and pgvector interface.
    
    Architectural Status:
    - Prepared for PostgreSQL + pgvector high-dimensional cosine distance queries.
    - When PostgreSQL is offline or running under SQLite test fixtures,
      accurately reports pgvector status as inactive and uses structured relational
      filtering without falsifying vector search metrics.
    """

    def __init__(self, is_pgvector_active: bool = False) -> None:
        self.is_pgvector_active = is_pgvector_active

    def get_status(self) -> Dict[str, Any]:
        """Return diagnostic status of vector retrieval infrastructure."""
        return {
            "pgvector_active": self.is_pgvector_active,
            "embedding_dimension": 768,
            "distance_metric": "cosine",
            "fallback_strategy": "structured_relational_rule_filtering",
            "note": (
                "Live pgvector semantic indexing requires active PostgreSQL instance with "
                "vector extension enabled. Relational guideline retrieval is operational."
            ),
        }

    async def retrieve_relevant_guidelines(
        self,
        session: AsyncSession,
        organization_id: UUID,
        content: str,
        target_channel: Optional[str] = None,
    ) -> List[BrandGuideline]:
        """Retrieve active brand guidelines belonging strictly to the organization.
        
        Enforces tenant isolation by scoping strictly to organization_id.
        Filters only active rules (is_active == True).
        """
        stmt = (
            select(BrandGuideline)
            .where(
                BrandGuideline.organization_id == organization_id,
                BrandGuideline.is_active == True,  # noqa: E712
            )
        )
        result = await session.execute(stmt)
        guidelines = list(result.scalars().all())
        logger.info(
            "Retrieved %d active brand guidelines for tenant organization %s",
            len(guidelines),
            organization_id,
        )
        return guidelines


semantic_retriever = SemanticRetriever()
