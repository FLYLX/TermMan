# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ---------- 1) input_merge_buffer.distinct_item_ids ----------
p = r"E:\dev\TermMan\dev\TermMan\backend\app\services\agent\input_merge_buffer.py"
s = open(p, encoding="utf-8").read()
old = '''    def peek(self, item_id: str, scope_key: str = "") -> list[MergeBufferEntry]:'''
new = '''    def distinct_item_ids(self) -> list[str]:
        """Item ids that currently have buffered entries (any scope)."""
        with self._lock:
            ids: set[str] = set()
            for key in self._entries:
                ids.add(key.split("|", 1)[0])
            return sorted(ids)

    def peek(self, item_id: str, scope_key: str = "") -> list[MergeBufferEntry]:'''
assert s.count(old) == 1, f"buffer anchor={s.count(old)}"
s = s.replace(old, new)
open(p, "w", encoding="utf-8", newline="").write(s)
print("1 buffer distinct_item_ids: OK")

# ---------- 2) robot_service.sweep_pending_conversations ----------
p = r"E:\dev\TermMan\dev\TermMan\backend\app\plugins\robot\service.py"
s = open(p, encoding="utf-8").read()
old = '''    def reap_stuck_dispatch_jobs(self) -> int:'''
new = '''    def sweep_pending_conversations(self) -> dict[str, int]:
        """Global invariant: no active LLM turn + pending input -> start a turn.

        Safety net for races/crashes where the turn-end drain never fired
        (e.g. a job result buffered right after the last flush, or a worker
        that died before its finally hook). Runs from the task watchdog every
        pass. Busy conversations are skipped; buffered job results re-buffer
        themselves if their conversation turns out to be busy, so this can
        never force concurrent turns on one conversation.
        """
        stats = {"pending_turns_kicked": 0, "buffered_results_flushed": 0}
        with self._lock:
            pending_keys = [
                (robot_id, conversation_key)
                for (robot_id, conversation_key), entries
                in self._pending_task_replies.items()
                if entries
            ]
        for robot_id, conversation_key in pending_keys:
            try:
                if self.conversation_has_active_dispatch(robot_id, conversation_key):
                    continue
                with Session(engine) as session:
                    robot = session.get(Robot, uuid.UUID(robot_id))
                if robot is None or not robot.is_enabled:
                    continue
                if self._enqueue_pending_chat_followup(
                    robot=robot, conversation_key=conversation_key
                ):
                    stats["pending_turns_kicked"] += 1
                    logger.info(
                        "[RobotService] Sweep kicked pending turn: robot=%s conversation=%s",
                        robot_id,
                        conversation_key,
                    )
            except Exception:
                logger.exception(
                    "[RobotService] Sweep failed for pending conversation robot=%s conversation=%s",
                    robot_id,
                    conversation_key,
                )
        try:
            from app.services.agent.input_merge_buffer import input_merge_buffer
            from app.services.agent.mcp.local_server import (
                flush_all_job_results_for_item,
            )

            for item_id in input_merge_buffer.distinct_item_ids():
                if item_id == "qq":
                    continue
                try:
                    uuid.UUID(item_id)
                except ValueError:
                    continue
                flushed = flush_all_job_results_for_item(item_id)
                if flushed:
                    stats["buffered_results_flushed"] += flushed
        except Exception:
            logger.exception("[RobotService] Sweep buffer flush failed")
        return stats

    def reap_stuck_dispatch_jobs(self) -> int:'''
assert s.count(old) == 1, f"service anchor={s.count(old)}"
s = s.replace(old, new)
open(p, "w", encoding="utf-8", newline="").write(s)
print("2 service sweep: OK")

# ---------- 3) integration hook ----------
p = r"E:\dev\TermMan\dev\TermMan\backend\app\plugins\robot\agent\integration.py"
s = open(p, encoding="utf-8").read()
old = '''    def reap_stuck_dispatch_jobs(self) -> int:
        from app.plugins.robot.service import robot_service

        return robot_service.reap_stuck_dispatch_jobs()'''
new = '''    def reap_stuck_dispatch_jobs(self) -> int:
        from app.plugins.robot.service import robot_service

        return robot_service.reap_stuck_dispatch_jobs()

    def sweep_pending_inputs(self) -> dict[str, int]:
        from app.plugins.robot.service import robot_service

        return robot_service.sweep_pending_conversations()'''
assert s.count(old) == 1, f"integration anchor={s.count(old)}"
s = s.replace(old, new)
open(p, "w", encoding="utf-8", newline="").write(s)
print("3 integration hook: OK")

# ---------- 4) watchdog pass ----------
p = r"E:\dev\TermMan\dev\TermMan\backend\app\services\agent\task_watchdog.py"
s = open(p, encoding="utf-8").read()
old = '''    try:
        from app.services.agent.integrations.registry import get_agent_integrations

        for integration in get_agent_integrations():
            if hasattr(integration, "reap_stuck_dispatch_jobs"):
                stats["dispatch_reaped"] = integration.reap_stuck_dispatch_jobs()
    except Exception:
        logger.exception("[TaskWatchdog] Dispatch reaper failed")'''
new = '''    try:
        from app.services.agent.integrations.registry import get_agent_integrations

        for integration in get_agent_integrations():
            if hasattr(integration, "reap_stuck_dispatch_jobs"):
                stats["dispatch_reaped"] = integration.reap_stuck_dispatch_jobs()
    except Exception:
        logger.exception("[TaskWatchdog] Dispatch reaper failed")
    try:
        from app.services.agent.integrations.registry import get_agent_integrations

        for integration in get_agent_integrations():
            if hasattr(integration, "sweep_pending_inputs"):
                swept = integration.sweep_pending_inputs() or {}
                stats["pending_turns_kicked"] = (
                    stats.get("pending_turns_kicked", 0)
                    + int(swept.get("pending_turns_kicked") or 0)
                )
                stats["buffered_results_flushed"] = (
                    stats.get("buffered_results_flushed", 0)
                    + int(swept.get("buffered_results_flushed") or 0)
                )
    except Exception:
        logger.exception("[TaskWatchdog] Pending input sweep failed")'''
assert s.count(old) == 1, f"watchdog anchor={s.count(old)}"
s = s.replace(old, new)
open(p, "w", encoding="utf-8", newline="").write(s)
print("4 watchdog sweep: OK")
