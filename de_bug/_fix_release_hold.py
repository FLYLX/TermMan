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

SVC = r"backend\app\plugins\robot\service.py"

patch(SVC, [
# release helper after conversation_has_active_dispatch
(
'''        for queued_job in queued_snapshot:
            if (
                str(queued_job.robot_id) == robot_id_text
                and queued_job.conversation_key == conversation_key
            ):
                return True
        return False

    def conversation_controller_allows_reply(''',
'''        for queued_job in queued_snapshot:
            if (
                str(queued_job.robot_id) == robot_id_text
                and queued_job.conversation_key == conversation_key
            ):
                return True
        return False

    def _release_processing_hold(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
    ) -> None:
        """Clear the job-scoped processing hold once no background jobs remain.

        Callback rounds carry a stale conversation generation, so the normal
        reply-context bookkeeping (guarded by generation) never clears the
        processing flag set by `_extend_processing_for_active_jobs`. Without
        this release the conversation stays "processing" until the hard
        timeout, and new inbound messages pile up in the pending queue with
        no turn to drain them.
        """
        if not conversation_key:
            return
        key = self._conversation_controller_key(robot_id, conversation_key)
        with self._lock:
            controller = self._conversation_controllers.get(key)
            if controller is None or not controller.processing:
                return
            controller.processing = False
            controller.processing_expires_at = None
            controller.updated_at = self._now()

    def conversation_controller_allows_reply('''
),
# extend-or-release after each dispatch job
(
'''                if (
                    self._session_has_running_terminal_jobs(str(job.item_id))
                    or self._item_has_running_jobs(str(job.item_id))
                ):
                    self._extend_processing_for_active_jobs(
                        robot, job.conversation_key,
                    )''',
'''                if (
                    self._session_has_running_terminal_jobs(str(job.item_id))
                    or self._item_has_running_jobs(str(job.item_id))
                ):
                    self._extend_processing_for_active_jobs(
                        robot, job.conversation_key,
                    )
                else:
                    self._release_processing_hold(
                        robot.id, job.conversation_key,
                    )'''
),
])
print("RELEASE FIX APPLIED")
