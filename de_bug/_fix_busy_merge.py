# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

def patch(path, repls):
    src = open(path, encoding="utf-8").read()
    for old, new in repls:
        n = src.count(old)
        if n != 1:
            print(f"FAIL {path}: anchor count={n} for {old[:70]!r}")
            sys.exit(1)
        src = src.replace(old, new)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(src)
    print(f"OK {path}: {len(repls)} replacement(s)")

LS = r"backend\app\services\agent\mcp\local_server.py"
SVC = r"backend\app\plugins\robot\service.py"
INT = r"backend\app\plugins\robot\agent\integration.py"

patch(SVC, [
# constant
(
'''PENDING_CHAT_QUEUE_LIMIT = 5''',
'''PENDING_CHAT_QUEUE_LIMIT = 5
BACKGROUND_JOB_ROUTE_KEY = "background_job"'''
),
# route_key literal -> constant
(
'''                item_id=item.id,
                route_key="background_job",''',
'''                item_id=item.id,
                route_key=BACKGROUND_JOB_ROUTE_KEY,'''
),
# new authoritative busy signal after conversation_is_processing
(
'''    def conversation_is_processing(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
    ) -> bool:
        key = self._conversation_controller_key(robot_id, conversation_key)
        with self._lock:
            controller = self._conversation_controllers.get(key)
            return bool(controller and controller.processing)
''',
'''    def conversation_is_processing(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
    ) -> bool:
        key = self._conversation_controller_key(robot_id, conversation_key)
        with self._lock:
            controller = self._conversation_controllers.get(key)
            return bool(controller and controller.processing)

    def conversation_has_active_dispatch(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
    ) -> bool:
        """Whether a dispatch job for this conversation is running or queued.

        This is the authoritative "a turn is in flight" signal used to decide
        whether background job results should be buffered and merged into the
        running turn instead of starting a new turn immediately. Unlike the
        raw controller `processing` flag, an active/queued dispatch job
        guarantees the turn-end flush hook will drain the buffer, so buffered
        results can never linger.
        """
        if not conversation_key:
            return False
        robot_id_text = str(robot_id)
        with self._lock:
            for _started, job in self._active_dispatch_jobs.items():
                queued_job = job[1]
                if (
                    str(queued_job.robot_id) == robot_id_text
                    and queued_job.conversation_key == conversation_key
                ):
                    return True
        try:
            with self._dispatch_queue.mutex:
                queued_snapshot = list(self._dispatch_queue.queue)
        except Exception:
            queued_snapshot = []
        for queued_job in queued_snapshot:
            if (
                str(queued_job.robot_id) == robot_id_text
                and queued_job.conversation_key == conversation_key
            ):
                return True
        return False
'''
),
# session-based running-jobs helper before _item_has_running_jobs
(
'''    def _item_has_running_jobs(self, item_id: str) -> bool:
        """Check if the daemon has running background jobs for this item."""''',
'''    def _session_has_running_terminal_jobs(self, item_id: str) -> bool:
        """In-process check for running terminal jobs (no daemon round-trip).

        The daemon list lookup races with freshly started jobs; the session
        bookkeeping is updated synchronously when run_job starts, so it is
        the reliable signal right after a dispatch turn.
        """
        try:
            from app.services.agent.session import agent_session_manager

            session = agent_session_manager.get_session(item_id)
            return bool(session and session.has_running_terminal_job())
        except Exception:
            return False

    def _item_has_running_jobs(self, item_id: str) -> bool:
        """Check if the daemon has running background jobs for this item."""'''
),
# extend condition: session check first, daemon fallback
(
'''                if self._item_has_running_jobs(str(job.item_id)):
                    self._extend_processing_for_active_jobs(
                        robot, job.conversation_key,
                    )''',
'''                if (
                    self._session_has_running_terminal_jobs(str(job.item_id))
                    or self._item_has_running_jobs(str(job.item_id))
                ):
                    self._extend_processing_for_active_jobs(
                        robot, job.conversation_key,
                    )'''
),
# skip corrective retry for background-job callback rounds
(
'''                if (
                    not response_text
                    and not robot_message_sent
                    and job.direct_reply_trigger
                    and not (_agent_sess and _agent_sess.has_running_terminal_job())
                ):''',
'''                if (
                    not response_text
                    and not robot_message_sent
                    and job.direct_reply_trigger
                    and job.route_key != BACKGROUND_JOB_ROUTE_KEY
                    and not (_agent_sess and _agent_sess.has_running_terminal_job())
                ):'''
),
# flush hook: run in finally after popping active job, so results are
# drained even when the job errored, and the finished job no longer counts
# as active for concurrent busy checks
(
'''            else:
                try:
                    from app.services.agent.mcp.local_server import (
                        flush_job_results_for_turn_end,
                    )

                    flush_job_results_for_turn_end(
                        str(job.item_id),
                        conversation_key=job.conversation_key,
                    )
                except Exception:
                    logger.debug(
                        "[RobotService] Failed to flush buffered job results for item=%s",
                        job.item_id,
                    )
            finally:
                with self._lock:
                    self._active_dispatch_jobs.pop(tracking_key, None)
                self._dispatch_queue.task_done()''',
'''            finally:
                with self._lock:
                    self._active_dispatch_jobs.pop(tracking_key, None)
                try:
                    from app.services.agent.mcp.local_server import (
                        flush_job_results_for_turn_end,
                    )

                    flush_job_results_for_turn_end(
                        str(job.item_id),
                        conversation_key=job.conversation_key,
                    )
                except Exception:
                    logger.debug(
                        "[RobotService] Failed to flush buffered job results for item=%s",
                        job.item_id,
                    )
                self._dispatch_queue.task_done()'''
),
])

patch(INT, [
(
'''    def is_conversation_processing(self, integration_id: str, conversation_key: str) -> bool:
        from app.plugins.robot.service import robot_service

        return robot_service.conversation_is_processing(integration_id, conversation_key)
''',
'''    def is_conversation_processing(self, integration_id: str, conversation_key: str) -> bool:
        from app.plugins.robot.service import robot_service

        # A conversation counts as processing when a dispatch job is running
        # or queued for it. The raw controller `processing` flag is not used
        # here: job-result buffering relies on the turn-end flush hook, which
        # only fires for dispatch jobs, so only an active/queued dispatch job
        # guarantees buffered results get drained.
        return robot_service.conversation_has_active_dispatch(
            integration_id, conversation_key
        )
'''
),
])

patch(LS, [
(
'''            flushed_any = server._deliver_background_job_to_robot(
                item_id=item_id,
                command=first["command"],
                result=first["result"],
                robot_job_context=first["robot_job_context"],
                pending_reply_id=first.get("pending_robot_reply_id") or "",
                reply_ticket_id=robot_ticket,
                message_override=message,
            ) or flushed_any''',
'''            delivered = server._deliver_background_job_to_robot(
                item_id=item_id,
                command=first["command"],
                result=first["result"],
                robot_job_context=first["robot_job_context"],
                pending_reply_id=first.get("pending_robot_reply_id") or "",
                reply_ticket_id=robot_ticket,
                message_override=message,
            )
            flushed_any = delivered or flushed_any
            if delivered and len(robot_entries) > 1:
                # The batch message covers every entry; clear the per-job
                # pending replies of the non-first entries so they do not
                # linger as orphaned queue items.
                for extra in robot_entries[1:]:
                    if extra.get("pending_robot_reply_id"):
                        server._clear_background_job_robot_reply(
                            robot_job_context=extra.get("robot_job_context"),
                            pending_reply_id=extra.get("pending_robot_reply_id") or "",
                        )'''
),
])
print("ALL FIXED")
