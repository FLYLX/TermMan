"""Best-effort SQLite state store for agent task state.

Persists task workflows, reply tickets, and queued robot dispatch jobs so a
backend restart does not silently lose in-flight tasks. This store is
intentionally separate from the main application database (which is managed
by Alembic): it owns its engine and creates its tables on demand.

Every public function is best-effort: persistence failures are logged and
swallowed so the in-memory execution path is never broken by the store.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from sqlalchemy import String, Text, create_engine, delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.core.config import settings

logger = logging.getLogger(__name__)


class _StateBase(DeclarativeBase):
    pass


class WorkflowStateRow(_StateBase):
    __tablename__ = "agent_workflow_state"

    workflow_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    status: Mapped[str] = mapped_column(String(32), index=True, default="")
    updated_at: Mapped[str] = mapped_column(String(64), index=True, default="")
    payload: Mapped[str] = mapped_column(Text, default="{}")


class TicketStateRow(_StateBase):
    __tablename__ = "agent_ticket_state"

    ticket_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    status: Mapped[str] = mapped_column(String(32), index=True, default="")
    pending_reply_active: Mapped[str] = mapped_column(String(8), default="")
    updated_at: Mapped[str] = mapped_column(String(64), index=True, default="")
    payload: Mapped[str] = mapped_column(Text, default="{}")


class KVStateRow(_StateBase):
    __tablename__ = "agent_kv_state"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    updated_at: Mapped[str] = mapped_column(String(64), default="")
    payload: Mapped[str] = mapped_column(Text, default="{}")


_engine: Engine | None = None
_engine_lock = threading.Lock()


def _state_db_path() -> str:
    return str(settings.AGENT_STATE_STORE_PATH or "").strip()


def _get_engine() -> Engine | None:
    global _engine
    path = _state_db_path()
    if not path:
        return None
    with _engine_lock:
        if _engine is None:
            try:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                _engine = create_engine(
                    f"sqlite:///{path}",
                    connect_args={"check_same_thread": False},
                )
                _StateBase.metadata.create_all(_engine)
            except Exception as exc:
                logger.warning("[AgentStateStore] Failed to init state store %s: %s", path, exc)
                _engine = None
    return _engine


def reset_state_store_engine() -> None:
    """Drop the cached engine (tests swap AGENT_STATE_STORE_PATH)."""
    global _engine
    with _engine_lock:
        if _engine is not None:
            try:
                _engine.dispose()
            except Exception:
                pass
        _engine = None


def _session() -> Session | None:
    engine = _get_engine()
    if engine is None:
        return None
    try:
        return Session(engine)
    except Exception as exc:
        logger.warning("[AgentStateStore] Failed to open session: %s", exc)
        return None


def _row_to_payload(row: Any) -> dict[str, Any] | None:
    import json

    try:
        payload = json.loads(str(getattr(row, "payload", "") or "{}"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


# ---------------------------------------------------------------------------
# Workflow rows
# ---------------------------------------------------------------------------

def save_workflow(payload: dict[str, Any]) -> None:
    import json

    session = _session()
    if session is None:
        return
    try:
        workflow_id = str(payload.get("workflow_id") or "")
        if not workflow_id:
            return
        with session:
            row = session.get(WorkflowStateRow, workflow_id)
            if row is None:
                row = WorkflowStateRow(workflow_id=workflow_id)
            row.item_id = str(payload.get("item_id") or "")
            row.status = str(payload.get("status") or "")
            row.updated_at = str(payload.get("updated_at") or "")
            row.payload = json.dumps(payload, ensure_ascii=False)
            session.add(row)
            session.commit()
    except Exception as exc:
        logger.warning("[AgentStateStore] save_workflow failed: %s", exc)
    finally:
        session.close()


def delete_workflow(workflow_id: str) -> None:
    session = _session()
    if session is None:
        return
    try:
        with session:
            session.execute(
                delete(WorkflowStateRow).where(
                    WorkflowStateRow.workflow_id == str(workflow_id)
                )
            )
            session.commit()
    except Exception as exc:
        logger.warning("[AgentStateStore] delete_workflow failed: %s", exc)
    finally:
        session.close()


def load_workflows() -> list[dict[str, Any]]:
    session = _session()
    if session is None:
        return []
    try:
        with session:
            rows = session.execute(select(WorkflowStateRow)).scalars().all()
            return [payload for row in rows if (payload := _row_to_payload(row))]
    except Exception as exc:
        logger.warning("[AgentStateStore] load_workflows failed: %s", exc)
        return []
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Ticket rows
# ---------------------------------------------------------------------------

def save_ticket(payload: dict[str, Any]) -> None:
    import json

    session = _session()
    if session is None:
        return
    try:
        ticket_id = str(payload.get("ticket_id") or "")
        if not ticket_id:
            return
        with session:
            row = session.get(TicketStateRow, ticket_id)
            if row is None:
                row = TicketStateRow(ticket_id=ticket_id)
            row.item_id = str(payload.get("item_id") or "")
            row.status = str(payload.get("status") or "")
            row.pending_reply_active = "1" if payload.get("pending_reply_active") else ""
            row.updated_at = str(payload.get("updated_at") or "")
            row.payload = json.dumps(payload, ensure_ascii=False)
            session.add(row)
            session.commit()
    except Exception as exc:
        logger.warning("[AgentStateStore] save_ticket failed: %s", exc)
    finally:
        session.close()


def delete_ticket(ticket_id: str) -> None:
    session = _session()
    if session is None:
        return
    try:
        with session:
            session.execute(
                delete(TicketStateRow).where(TicketStateRow.ticket_id == str(ticket_id))
            )
            session.commit()
    except Exception as exc:
        logger.warning("[AgentStateStore] delete_ticket failed: %s", exc)
    finally:
        session.close()


def load_tickets() -> list[dict[str, Any]]:
    session = _session()
    if session is None:
        return []
    try:
        with session:
            rows = session.execute(select(TicketStateRow)).scalars().all()
            return [payload for row in rows if (payload := _row_to_payload(row))]
    except Exception as exc:
        logger.warning("[AgentStateStore] load_tickets failed: %s", exc)
        return []
    finally:
        session.close()


# ---------------------------------------------------------------------------
# KV rows (ticket alias map, etc.)
# ---------------------------------------------------------------------------

def save_kv(key: str, payload: dict[str, Any]) -> None:
    import json
    from datetime import datetime, timezone

    session = _session()
    if session is None:
        return
    try:
        with session:
            row = session.get(KVStateRow, key)
            if row is None:
                row = KVStateRow(key=key)
            row.updated_at = datetime.now(timezone.utc).isoformat()
            row.payload = json.dumps(payload, ensure_ascii=False)
            session.add(row)
            session.commit()
    except Exception as exc:
        logger.warning("[AgentStateStore] save_kv failed: %s", exc)
    finally:
        session.close()


def load_kv(key: str) -> dict[str, Any]:
    session = _session()
    if session is None:
        return {}
    try:
        with session:
            row = session.get(KVStateRow, key)
            if row is None:
                return {}
            return _row_to_payload(row) or {}
    except Exception as exc:
        logger.warning("[AgentStateStore] load_kv failed: %s", exc)
        return {}
    finally:
        session.close()


def delete_kv(key: str) -> None:
    session = _session()
    if session is None:
        return
    try:
        with session:
            session.execute(delete(KVStateRow).where(KVStateRow.key == key))
            session.commit()
    except Exception as exc:
        logger.warning("[AgentStateStore] delete_kv failed: %s", exc)
    finally:
        session.close()


def clear_all() -> None:
    session = _session()
    if session is None:
        return
    try:
        with session:
            for model in (
                WorkflowStateRow,
                TicketStateRow,
                KVStateRow,
            ):
                session.execute(delete(model))
            session.commit()
    except Exception as exc:
        logger.warning("[AgentStateStore] clear_all failed: %s", exc)
    finally:
        session.close()


__all__ = [
    "clear_all",
    "delete_kv",
    "delete_ticket",
    "delete_workflow",
    "load_kv",
    "load_tickets",
    "load_workflows",
    "reset_state_store_engine",
    "save_kv",
    "save_ticket",
    "save_workflow",
]
