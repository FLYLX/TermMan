# -*- coding: utf-8 -*-
import re
from pathlib import Path

def patch_file(path_str, pairs):
    path = Path(path_str)
    src = path.read_text(encoding="utf-8")
    for old, new, count in pairs:
        n = src.count(old)
        assert n == count, f"{path_str}: expected {count}, found {n}: {old[:70]!r}"
        src = src.replace(old, new)
    path.write_text(src, encoding="utf-8")
    print(f"patched {path_str}")

def drop_range(path_str, start_marker, end_marker):
    path = Path(path_str)
    src = path.read_text(encoding="utf-8")
    i = src.find(start_marker)
    assert i >= 0, f"start not found: {start_marker[:60]!r}"
    j = src.find(end_marker, i)
    assert j >= 0, f"end not found: {end_marker[:60]!r}"
    src = src[:i] + src[j:]
    path.write_text(src, encoding="utf-8")
    print(f"dropped range in {path_str}")

# ---------- task_watchdog.py ----------
W = r"backend\app\services\agent\task_watchdog.py"
# constants block
patch_file(W, [
('''CLOSE_REASON = "任务长时间没有进展，已自动关闭"
# Grace period before declaring a background-job result callback lost.
WAITING_JOB_CALLBACK_GRACE_SECONDS = 60.0
# Maximum times a single workflow can be reconciled before being marked blocked.
MAX_RECONCILE_ATTEMPTS = 3
''', '', 1),
])
# drop the whole workflow helper block: from CLOSE_REASON usage fn to orphan ticket fn
drop_range(W, "def _closure_notice(", "def _close_stale_orphan_ticket(")
# run_once cleanup
patch_file(W, [
('''def run_once(now: datetime | None = None) -> dict[str, int]:
    from app.services.agent.task_workflow import (
        WORKFLOW_ACTIVE_STATUSES,
        task_workflow_manager,
    )

    now = now or _utcnow()
    stats = {
        "closed": 0,
        "reported": 0,
        "orphan_tickets_removed": 0,
        "stale_tickets_closed": 0,
        "reconciled": 0,
        "resumed": 0,
        "stalled_resumed": 0,
        "dispatch_reaped": 0,
        "memories_deduplicated": 0,
    }''',
'''def run_once(now: datetime | None = None) -> dict[str, int]:
    now = now or _utcnow()
    stats = {
        "orphan_tickets_removed": 0,
        "stale_tickets_closed": 0,
        "dispatch_reaped": 0,
        "memories_deduplicated": 0,
    }''', 1),
('''    # Disabled: job results are delivered by the poller thread callback.
    # Watchdog reconciliation caused ghost "result lost" failures and
    # auto-resumed workflows against the callback-driven design.
    try:
        _resume_stalled_active_workflows(now, stats)
    except Exception:
        logger.exception("[TaskWatchdog] Stalled-workflow resume failed")
    try:
        _reconcile_waiting_job_workflows(now, stats)
    except Exception:
        logger.exception("[TaskWatchdog] Waiting-job reconciliation failed")
    try:''',
'''    try:''', 1),
('''    with task_workflow_manager._lock:
        candidates = [
            workflow
            for workflow in task_workflow_manager._workflows.values()
            if workflow.status in WORKFLOW_ACTIVE_STATUSES
            and _as_utc(workflow.updated_at)
            < now - timedelta(seconds=_stale_timeout_seconds(workflow.status))
        ]
    for workflow in candidates:
        try:
            _close_stale_workflow(workflow, stats, now=now)
        except Exception:
            logger.exception(
                "[TaskWatchdog] Failed to close stale workflow=%s",
                workflow.workflow_id,
            )
    try:
        _remove_orphan_tickets(now, stats)''',
'''    try:
        _remove_orphan_tickets(now, stats)''', 1),
('''    if stats["closed"] or stats["orphan_tickets_removed"] or stats["stale_tickets_closed"] or stats["memories_deduplicated"]:''',
'''    if stats["orphan_tickets_removed"] or stats["stale_tickets_closed"] or stats["memories_deduplicated"]:''', 1),
])

# ---------- integration.py ----------
I = r"backend\app\plugins\robot\agent\integration.py"
drop_range(I, "    def _is_workflow_active(self, agent: Agent) -> bool:", "    def build_system_prompt(self, agent: Agent) -> str:")
patch_file(I, [
('''    ) -> bool:
        if self._is_workflow_active(agent):
            return False
        return (''',
'''    ) -> bool:
        return (''', 1),
('''    def delivery_correction_message(self, final_response: str, *, workflow_active: bool = False) -> dict[str, str]:
        from app.plugins.robot.prompts import build_robot_delivery_reflection_prompt

        reflection_prompt = build_robot_delivery_reflection_prompt(final_response, workflow_active=workflow_active)''',
'''    def delivery_correction_message(self, final_response: str) -> dict[str, str]:
        from app.plugins.robot.prompts import build_robot_delivery_reflection_prompt

        reflection_prompt = build_robot_delivery_reflection_prompt(final_response)''', 1),
])

# ---------- prompts.py ----------
patch_file(r"backend\app\plugins\robot\prompts.py", [
('''def build_robot_delivery_reflection_prompt(final_response: str, *, workflow_active: bool = False) -> str:
    if not is_robot_plugin_enabled():
        return ""
    if workflow_active:
        return ""
''',
'''def build_robot_delivery_reflection_prompt(final_response: str) -> str:
    if not is_robot_plugin_enabled():
        return ""
''', 1),
])
print("ALL OK")
