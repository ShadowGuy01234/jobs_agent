"""Pipeline orchestrator with LangGraph checkpointer and execution controls."""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from config import settings
from db.database import get_db_connection
from pipeline.graph import build_outreach_graph
from pipeline.state import OpportunityPipelineState

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Orchestrates LangGraph graph execution, checkpointing, and human resume commands.

    IMPORTANT: the human-approval step uses LangGraph's `interrupt()`, which pauses a run
    mid-graph until a *separate* call resumes it with `Command(resume=...)`. In this app that
    resume call always comes from a different `PipelineOrchestrator` instance than the one that
    started the run (the scheduler process drafts outreach; the Telegram bot process resumes it
    after you tap Approve). That means the checkpointer MUST be durable and shared by file path
    rather than held in-process memory - an in-memory checkpointer (e.g. `MemorySaver`) loses the
    paused state the instant a different instance (or a restart) tries to resume it, which is why
    "Approve & Send" used to silently fail 100% of the time. We use `AsyncSqliteSaver` backed by a
    checkpoints.db file instead, so any orchestrator instance pointed at the same file can resume
    a run that another instance paused.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or settings.DATABASE_PATH)
        # Durable, file-backed checkpoint store shared across process/instance boundaries.
        # Named after the main db (not a fixed "checkpoints.db") so that tests using unique
        # temp db paths get isolated checkpoint files instead of colliding in a shared temp dir.
        self.checkpoint_db_path = self.db_path.parent / f"{self.db_path.stem}_checkpoints.db"
        self._conn: Optional[aiosqlite.Connection] = None
        self._checkpointer: Optional[AsyncSqliteSaver] = None
        self._graph = None
        self._init_lock = asyncio.Lock()

    async def _ensure_graph(self):
        """Lazily open the shared sqlite checkpoint connection and compile the graph (async-safe)."""
        if self._graph is not None:
            return self._graph
        async with self._init_lock:
            if self._graph is None:
                self.checkpoint_db_path.parent.mkdir(parents=True, exist_ok=True)
                conn = await aiosqlite.connect(str(self.checkpoint_db_path))
                await conn.execute("PRAGMA journal_mode=WAL;")
                await conn.execute("PRAGMA busy_timeout=30000;")
                self._conn = conn
                self._checkpointer = AsyncSqliteSaver(conn)
                await self._checkpointer.setup()
                self._graph = build_outreach_graph().compile(checkpointer=self._checkpointer)
        return self._graph

    async def close(self) -> None:
        """Close the underlying sqlite connection (call on app shutdown)."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            self._graph = None
            self._checkpointer = None

    async def process_opportunity(
        self, opportunity_id: int
    ) -> Optional[Dict[str, Any]]:
        """Run an opportunity through the pipeline until it reaches interrupt or finishes."""
        graph = await self._ensure_graph()

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
        state = await graph.ainvoke(initial_state.model_dump(), config=config)

        # Check if the graph paused at an interrupt (human_gate)
        thread_state = await graph.aget_state(config)
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
        graph = await self._ensure_graph()
        thread_id = f"opp_thread_{opportunity_id}"
        config = {"configurable": {"thread_id": thread_id}}

        # Guard against resuming a thread with no durable checkpoint (e.g. it was never drafted,
        # or the checkpoint file was wiped) so callers get a clear error instead of a stack trace.
        existing_state = await graph.aget_state(config)
        if not existing_state or not existing_state.next:
            msg = (
                f"No paused checkpoint found for opportunity #{opportunity_id} "
                f"(thread {thread_id}). It may have already been resolved, or its state expired."
            )
            logger.error(msg)
            return {"is_sent": False, "error_message": msg}

        resume_payload = {
            "action": action,
            "edited_subject": edited_subject,
            "edited_body": edited_body,
            "provided_email": provided_email,
        }

        logger.info(f"Resuming thread {thread_id} with command: {resume_payload}")

        try:
            res = await graph.ainvoke(
                Command(resume=resume_payload),
                config=config,
            )
        except Exception as e:
            logger.error(f"Resume failed for opportunity #{opportunity_id}: {e}", exc_info=True)
            return {"is_sent": False, "error_message": f"Resume failed: {e}"}
        return res
