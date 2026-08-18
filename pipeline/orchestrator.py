"""Pipeline orchestrator with LangGraph checkpointer and execution controls."""

import logging
from pathlib import Path
from typing import Any, Dict, Optional
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from config import settings
from db.database import get_db_connection
from pipeline.graph import build_outreach_graph
from pipeline.state import OpportunityPipelineState

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Orchestrates LangGraph graph execution, checkpointing, and human resume commands."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.DATABASE_PATH
        # Use MemorySaver checkpointer for thread pause/resume state
        self.checkpointer = MemorySaver()
        self.graph = build_outreach_graph().compile(checkpointer=self.checkpointer)

    async def process_opportunity(
        self, opportunity_id: int
    ) -> Optional[Dict[str, Any]]:
        """Run an opportunity through the pipeline until it reaches interrupt or finishes."""
        # 1. Fetch opportunity & company details from SQLite
        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT o.*, c.name as company_name, c.domain as company_domain, c.stage as company_stage
                FROM opportunities o
                JOIN companies c ON o.company_id = c.id
                WHERE o.id = ?
                """,
                (opportunity_id,),
            )
            row = cursor.fetchone()
            if not row:
                logger.error(f"Opportunity ID {opportunity_id} not found in database.")
                return None

        thread_id = f"opp_thread_{opportunity_id}"
        config = {"configurable": {"thread_id": thread_id}}

        initial_state = OpportunityPipelineState(
            opportunity_id=row["id"],
            company_id=row["company_id"],
            thread_id=thread_id,
            db_path=str(self.db_path),
            opportunity_title=row["title"],
            opportunity_type=row["type"],
            opportunity_url=row["url"],
            opportunity_location=row["location"] or "Remote",
            is_remote=bool(row["is_remote"]),
            raw_content=row["raw_content"],
            company_name=row["company_name"],
            company_domain=row["company_domain"],
            enriched_stage=row["company_stage"] or "seed",
        )

        logger.info(f"Starting pipeline execution for opportunity [{opportunity_id}] on thread {thread_id}")

        # Run graph until interrupt or END
        state = await self.graph.ainvoke(initial_state.model_dump(), config=config)

        # Check if the graph paused at an interrupt (human_gate)
        thread_state = self.graph.get_state(config)
        if thread_state.tasks and any(t.interrupts for t in thread_state.tasks):
            interrupt_data = thread_state.tasks[0].interrupts[0].value
            logger.info(f"Opportunity [{opportunity_id}] paused at human gate: {interrupt_data}")
            return interrupt_data

        logger.info(f"Opportunity [{opportunity_id}] execution completed without interrupt.")
        return None

    async def resume_opportunity(
        self,
        opportunity_id: int,
        action: str,  # 'approve', 'reject', 'skip'
        edited_subject: Optional[str] = None,
        edited_body: Optional[str] = None,
        provided_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resume a paused opportunity graph with human action."""
        thread_id = f"opp_thread_{opportunity_id}"
        config = {"configurable": {"thread_id": thread_id}}

        resume_payload = {
            "action": action,
            "edited_subject": edited_subject,
            "edited_body": edited_body,
            "provided_email": provided_email,
        }

        logger.info(f"Resuming thread {thread_id} with command: {resume_payload}")

        # Resume paused graph
        res = await self.graph.ainvoke(
            Command(resume=resume_payload),
            config=config,
        )
        return res
