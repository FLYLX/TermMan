from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import BACKEND_DIR

logger = logging.getLogger(__name__)

_SCHEDULED_TASKS_DIR = BACKEND_DIR.parent / ".runtime" / "scheduled_tasks"
_LOCK = threading.RLock()
_SAFE_ITEM_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_SCHEDULE_TYPES = {"once", "interval", "daily"}
_DEFAULT_TIMEZONE = "Asia/Shanghai"
_MIN_INTERVAL_SECONDS = 10
_MAX_INTERVAL_SECONDS = 365 * 24 * 60 * 60


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _clean_text(value: Any, *, max_length: int) -> str:
    return str(value or "").strip()[:max_length]


def _item_file(item_id: str) -> Path:
    safe_item_id = _SAFE_ITEM_ID_RE.sub("_", str(item_id).strip()) or "unknown"
    return _SCHEDULED_TASKS_DIR / f"{safe_item_id}.json"


def _empty_data() -> dict[str, Any]:
    return {"version": 1, "tasks": []}


def _load_data(item_id: str) -> dict[str, Any]:
    path = _item_file(item_id)
    if not path.exists():
        return _empty_data()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("[ScheduledTasks] Failed to read %s", path)
        return _empty_data()
    if not isinstance(payload, dict):
        return _empty_data()
    if not isinstance(payload.get("tasks"), list):
        payload["tasks"] = []
    payload["version"] = 1
    return payload


def _save_data(item_id: str, data: dict[str, Any]) -> None:
    path = _item_file(item_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _resolve_timezone(value: Any) -> tuple[str, tzinfo]:
    name = _clean_text(value, max_length=80) or _DEFAULT_TIMEZONE
    try:
        return name, ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        if name in {"Asia/Shanghai", "PRC"}:
            return "Asia/Shanghai", timezone(timedelta(hours=8), "Asia/Shanghai")
        if name in {"UTC", "Etc/UTC", "GMT"}:
            return "UTC", timezone.utc
        raise ValueError(f"unknown timezone: {name}") from exc


def _parse_datetime(value: Any, timezone_name: str) -> datetime:
    text = _clean_text(value, max_length=80)
    if not text:
        raise ValueError("run_at is required for a once task")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("run_at must be an ISO datetime") from exc
    if parsed.tzinfo is None:
        _, local_timezone = _resolve_timezone(timezone_name)
        parsed = parsed.replace(tzinfo=local_timezone)
    return parsed.astimezone(timezone.utc)


def _parse_time_of_day(value: Any) -> time:
    text = _clean_text(value, max_length=16)
    try:
        parsed = time.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("time_of_day must use HH:MM") from exc
    return parsed.replace(second=0, microsecond=0, tzinfo=None)


def _next_daily_run(
    *,
    time_of_day: str,
    timezone_name: str,
    after: datetime,
) -> datetime:
    _, local_timezone = _resolve_timezone(timezone_name)
    local_after = after.astimezone(local_timezone)
    local_time = _parse_time_of_day(time_of_day)
    candidate = datetime.combine(local_after.date(), local_time, tzinfo=local_timezone)
    if candidate <= local_after:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def _next_run_for_task(task: dict[str, Any], *, after: datetime) -> datetime | None:
    schedule_type = str(task.get("schedule_type") or "")
    if schedule_type == "once":
        return _parse_datetime(task.get("run_at"), str(task.get("timezone") or ""))
    if schedule_type == "interval":
        interval_seconds = int(task.get("interval_seconds") or 0)
        return after + timedelta(seconds=interval_seconds)
    if schedule_type == "daily":
        return _next_daily_run(
            time_of_day=str(task.get("time_of_day") or ""),
            timezone_name=str(task.get("timezone") or ""),
            after=after,
        )
    return None


def _normalize_task_payload(
    *,
    name: Any,
    instruction: Any,
    schedule_type: Any,
    run_at: Any = "",
    interval_seconds: Any = 0,
    time_of_day: Any = "",
    timezone_name: Any = _DEFAULT_TIMEZONE,
    enabled: Any = True,
) -> dict[str, Any]:
    clean_name = _clean_text(name, max_length=160)
    clean_instruction = _clean_text(instruction, max_length=4000)
    clean_schedule_type = _clean_text(schedule_type, max_length=24).lower()
    if not clean_name:
        raise ValueError("task name is required")
    if not clean_instruction:
        raise ValueError("task instruction is required")
    if clean_schedule_type not in _SCHEDULE_TYPES:
        raise ValueError("schedule_type must be once, interval, or daily")

    normalized_timezone, _ = _resolve_timezone(timezone_name)
    payload: dict[str, Any] = {
        "name": clean_name,
        "instruction": clean_instruction,
        "schedule_type": clean_schedule_type,
        "timezone": normalized_timezone,
        "enabled": bool(enabled),
        "run_at": "",
        "interval_seconds": 0,
        "time_of_day": "",
    }
    if clean_schedule_type == "once":
        payload["run_at"] = _iso_utc(_parse_datetime(run_at, normalized_timezone))
    elif clean_schedule_type == "interval":
        try:
            seconds = int(interval_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("interval_seconds must be an integer") from exc
        if not _MIN_INTERVAL_SECONDS <= seconds <= _MAX_INTERVAL_SECONDS:
            raise ValueError(
                f"interval_seconds must be between {_MIN_INTERVAL_SECONDS} and {_MAX_INTERVAL_SECONDS}"
            )
        payload["interval_seconds"] = seconds
    else:
        payload["time_of_day"] = _parse_time_of_day(time_of_day).strftime("%H:%M")
    return payload


def list_scheduled_tasks(item_id: str) -> list[dict[str, Any]]:
    with _LOCK:
        tasks = _load_data(item_id).get("tasks") or []
        return sorted(
            [dict(task) for task in tasks if isinstance(task, dict) and task.get("id")],
            key=lambda task: (
                not bool(task.get("enabled")),
                str(task.get("next_run_at") or "9999"),
                str(task.get("name") or "").lower(),
            ),
        )


def write_scheduled_task(
    item_id: str,
    *,
    task_id: str = "",
    name: str,
    instruction: str,
    schedule_type: str,
    run_at: str = "",
    interval_seconds: int = 0,
    time_of_day: str = "",
    timezone_name: str = _DEFAULT_TIMEZONE,
    enabled: bool = True,
) -> dict[str, Any]:
    normalized = _normalize_task_payload(
        name=name,
        instruction=instruction,
        schedule_type=schedule_type,
        run_at=run_at,
        interval_seconds=interval_seconds,
        time_of_day=time_of_day,
        timezone_name=timezone_name,
        enabled=enabled,
    )
    now = _utc_now()
    clean_task_id = _clean_text(task_id, max_length=80)

    with _LOCK:
        data = _load_data(item_id)
        tasks = data.setdefault("tasks", [])
        existing = next(
            (
                task
                for task in tasks
                if isinstance(task, dict)
                and clean_task_id
                and str(task.get("id") or "") == clean_task_id
            ),
            None,
        )
        if clean_task_id and existing is None:
            raise KeyError(f"scheduled task not found: {clean_task_id}")
        if existing is None:
            existing = {
                "id": uuid.uuid4().hex,
                "created_at": _iso_utc(now),
                "run_count": 0,
                "failure_count": 0,
                "last_status": "never",
            }
            tasks.append(existing)

        existing.update(normalized)
        existing.update(
            {
                "updated_at": _iso_utc(now),
                "running": False,
                "last_error": "",
            }
        )
        existing["next_run_at"] = (
            _iso_utc(_next_run_for_task(existing, after=now))
            if existing.get("enabled")
            else None
        )
        _save_data(item_id, data)

    scheduled_task_manager.wake()
    return dict(existing)


def delete_scheduled_task(
    item_id: str,
    *,
    task_id: str,
    reason: str = "",
) -> dict[str, Any]:
    clean_task_id = _clean_text(task_id, max_length=80)
    if not clean_task_id:
        raise ValueError("task_id is required")
    with _LOCK:
        data = _load_data(item_id)
        tasks = data.get("tasks") if isinstance(data.get("tasks"), list) else []
        removed = [
            dict(task)
            for task in tasks
            if isinstance(task, dict) and str(task.get("id") or "") == clean_task_id
        ]
        data["tasks"] = [
            task
            for task in tasks
            if not (
                isinstance(task, dict)
                and str(task.get("id") or "") == clean_task_id
            )
        ]
        if removed:
            data["last_deleted_at"] = _iso_utc(_utc_now())
            if clean_reason := _clean_text(reason, max_length=500):
                data["last_delete_reason"] = clean_reason
            _save_data(item_id, data)
        return {"count": len(removed), "removed": removed}


def _claim_due_tasks(now: datetime) -> list[tuple[str, dict[str, Any]]]:
    claimed: list[tuple[str, dict[str, Any]]] = []
    with _LOCK:
        if not _SCHEDULED_TASKS_DIR.exists():
            return claimed
        for path in _SCHEDULED_TASKS_DIR.glob("*.json"):
            item_id = path.stem
            data = _load_data(item_id)
            changed = False
            for task in data.get("tasks") or []:
                if not isinstance(task, dict) or not task.get("enabled") or task.get("running"):
                    continue
                next_run_text = str(task.get("next_run_at") or "")
                if not next_run_text:
                    continue
                try:
                    next_run = _parse_datetime(next_run_text, "UTC")
                except ValueError:
                    task["last_status"] = "failed"
                    task["last_error"] = "invalid next_run_at"
                    task["enabled"] = False
                    changed = True
                    continue
                if next_run > now:
                    continue
                task["running"] = True
                task["last_status"] = "running"
                task["last_started_at"] = _iso_utc(now)
                task["execution_id"] = uuid.uuid4().hex
                changed = True
                claimed.append((item_id, dict(task)))
            if changed:
                _save_data(item_id, data)
    return claimed


def _recover_interrupted_tasks() -> int:
    recovered = 0
    now = _utc_now()
    with _LOCK:
        if not _SCHEDULED_TASKS_DIR.exists():
            return recovered
        for path in _SCHEDULED_TASKS_DIR.glob("*.json"):
            item_id = path.stem
            data = _load_data(item_id)
            changed = False
            for task in data.get("tasks") or []:
                if not isinstance(task, dict) or not task.get("running"):
                    continue
                task["running"] = False
                task["last_status"] = "failed"
                task["last_error"] = "Backend restarted before the scheduled run completed"
                task["updated_at"] = _iso_utc(now)
                recovered += 1
                changed = True
            if changed:
                _save_data(item_id, data)
    return recovered


def _finish_task(
    item_id: str,
    task_id: str,
    *,
    success: bool,
    error: str = "",
) -> None:
    now = _utc_now()
    with _LOCK:
        data = _load_data(item_id)
        task = next(
            (
                entry
                for entry in data.get("tasks") or []
                if isinstance(entry, dict) and str(entry.get("id") or "") == task_id
            ),
            None,
        )
        if task is None:
            return
        task["running"] = False
        task["last_finished_at"] = _iso_utc(now)
        task["last_status"] = "success" if success else "failed"
        task["last_error"] = "" if success else _clean_text(error, max_length=1000)
        task["run_count"] = int(task.get("run_count") or 0) + 1
        if not success:
            task["failure_count"] = int(task.get("failure_count") or 0) + 1

        if task.get("schedule_type") == "once":
            task["enabled"] = False
            task["next_run_at"] = None
        elif task.get("enabled"):
            next_run = _next_run_for_task(task, after=now)
            task["next_run_at"] = _iso_utc(next_run) if next_run else None
        else:
            task["next_run_at"] = None
        task["updated_at"] = _iso_utc(now)
        _save_data(item_id, data)


def record_scheduled_ticket_result(
    reply_ticket_id: str,
    *,
    success: bool,
    error: str = "",
) -> bool:
    if not reply_ticket_id:
        return False
    try:
        from app.services.agent.reply_ticket import reply_ticket_manager

        ticket = reply_ticket_manager.get(reply_ticket_id)
    except Exception:
        return False
    if not ticket or not ticket.scheduled_task_id:
        return False

    now = _utc_now()
    with _LOCK:
        data = _load_data(ticket.item_id)
        task = next(
            (
                entry
                for entry in data.get("tasks") or []
                if isinstance(entry, dict)
                and str(entry.get("id") or "") == ticket.scheduled_task_id
            ),
            None,
        )
        if task is None:
            return False
        task["last_status"] = "success" if success else "failed"
        task["last_error"] = "" if success else _clean_text(error, max_length=1000)
        task["last_finished_at"] = _iso_utc(now)
        task["updated_at"] = _iso_utc(now)
        if not success:
            task["failure_count"] = int(task.get("failure_count") or 0) + 1
        _save_data(ticket.item_id, data)
    return True


def _handler_id_for_item(item_id: str) -> str:
    from sqlmodel import Session, select

    from app.core.db import engine
    from app.models import ItemHandlerItem

    try:
        item_uuid = uuid.UUID(item_id)
    except ValueError as exc:
        raise ValueError(f"invalid item id: {item_id}") from exc
    with Session(engine) as session:
        link = session.exec(
            select(ItemHandlerItem).where(ItemHandlerItem.item_id == item_uuid)
        ).first()
        if not link:
            raise ValueError("no Agent handler is attached to this terminal")
        return str(link.item_handler_id)


def _scheduled_agent_message(task: dict[str, Any]) -> str:
    return (
        "[Scheduled task]\n"
        f"schedule_id: {task.get('id')}\n"
        f"execution_id: {task.get('execution_id')}\n"
        f"name: {task.get('name')}\n"
        "This message was generated by the TermPaws scheduler, not by a user. "
        "Treat it as a live scheduled task and execute the instruction now.\n"
        f"Instruction: {task.get('instruction')}\n\n"
        "Failure policy: inspect the real failure first. Keep the schedule for transient "
        "network, package mirror, service availability, or temporary terminal failures. "
        "Delete it with mcp_local_delete_scheduled_task only when the schedule is obsolete, "
        "invalid, unsafe, or cannot succeed without a permanent configuration change. "
        "Any visible response must state that it came from a scheduled task."
    )


def _scheduled_display_message(task: dict[str, Any]) -> str:
    return f"{task.get('name')}\n{task.get('instruction')}"


class ScheduledTaskManager:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        recovered = _recover_interrupted_tasks()
        if recovered:
            logger.warning(
                "[ScheduledTasks] Recovered %s interrupted scheduled task run(s)",
                recovered,
            )
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="TermPaws-scheduled-tasks",
            daemon=True,
        )
        self._thread.start()
        logger.info("[ScheduledTasks] Scheduler started")

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        logger.info("[ScheduledTasks] Scheduler stopped")

    def wake(self) -> None:
        self._wake_event.set()

    def run_due_once(self, now: datetime | None = None) -> int:
        due = _claim_due_tasks(now or _utc_now())
        for item_id, task in due:
            threading.Thread(
                target=self._dispatch,
                args=(item_id, task),
                name=f"TermPaws-schedule-{item_id[:8]}",
                daemon=True,
            ).start()
        return len(due)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_due_once()
            except Exception:
                logger.exception("[ScheduledTasks] Scheduler iteration failed")
            self._wake_event.wait(timeout=1.0)
            self._wake_event.clear()

    def _dispatch(self, item_id: str, task: dict[str, Any]) -> None:
        task_id = str(task.get("id") or "")
        collected_errors: list[str] = []
        session = None

        try:
            from app.services.agent.session import (
                InputMessage,
                InputType,
                agent_session_manager,
            )

            handler_id = _handler_id_for_item(item_id)
            session = agent_session_manager.get_or_create_session(item_id, handler_id)

            def collect_event(event: dict[str, Any]) -> None:
                if str(event.get("type") or "") in {"agent_error", "agent_warning"}:
                    collected_errors.append(str(event.get("content") or "Agent error"))

            def complete(processed: bool, process_error: str) -> None:
                if session is not None:
                    session.remove_output_callback(collect_event)
                effective_error = process_error or "\n".join(collected_errors)
                _finish_task(
                    item_id,
                    task_id,
                    success=bool(processed and not effective_error),
                    error=effective_error,
                )

            session.emit_output(
                _scheduled_display_message(task),
                "scheduled_task",
                extra={
                    "scheduled_task_id": task_id,
                    "scheduled_task_name": str(task.get("name") or ""),
                    "execution_id": str(task.get("execution_id") or ""),
                },
            )
            session.process_input(
                InputMessage(
                    input_type=InputType.SCHEDULED_TASK,
                    content=_scheduled_agent_message(task),
                    query=f"scheduled task {task.get('name')}: {task.get('instruction')}",
                    callback=collect_event,
                    completion_callback=complete,
                    scheduled_task_id=task_id,
                    scheduled_execution_id=str(task.get("execution_id") or ""),
                    request_display=_scheduled_display_message(task),
                )
            )
        except Exception as exc:
            if session is not None:
                try:
                    session.remove_output_callback(collect_event)
                except Exception:
                    pass
            logger.exception(
                "[ScheduledTasks] Failed to dispatch item=%s task=%s",
                item_id,
                task_id,
            )
            _finish_task(item_id, task_id, success=False, error=str(exc))


scheduled_task_manager = ScheduledTaskManager()


def format_scheduled_tasks(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "No scheduled tasks."
    lines: list[str] = []
    for task in tasks:
        schedule_type = str(task.get("schedule_type") or "")
        if schedule_type == "once":
            schedule = f"once at {task.get('run_at')}"
        elif schedule_type == "interval":
            schedule = f"every {task.get('interval_seconds')} seconds"
        else:
            schedule = f"daily at {task.get('time_of_day')} {task.get('timezone')}"
        lines.append(
            f"- id={task.get('id')} name={task.get('name')!r} enabled={bool(task.get('enabled'))} "
            f"schedule={schedule}; next={task.get('next_run_at') or 'none'}; "
            f"last_status={task.get('last_status') or 'never'}; instruction={task.get('instruction')}"
        )
    return "\n".join(lines)
