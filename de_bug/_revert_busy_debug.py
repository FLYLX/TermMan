# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

def patch(path, repls):
    src = open(path, encoding="utf-8").read()
    for old, new in repls:
        n = src.count(old)
        if n != 1:
            print(f"FAIL {path}: anchor count={n} for {old[:60]!r}")
            sys.exit(1)
        src = src.replace(old, new)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(src)
    print(f"OK {path}: {len(repls)} replacement(s)")

LS = r"backend\app\services\agent\mcp\local_server.py"
SVC = r"backend\app\plugins\robot\service.py"

patch(LS, [
(
'''def _conversation_turn_busy(agent_session, robot_job_context: dict | None) -> bool:
    sess_busy = _session_turn_busy(agent_session)
    conv_busy = False
    busy_err = ""
    if robot_job_context:
        try:
            from app.services.agent.integrations.hooks import (
                is_integration_conversation_processing,
            )

            conv_busy = bool(
                is_integration_conversation_processing(
                    robot_job_context.get("robot_id", ""),
                    robot_job_context.get("conversation_key", ""),
                )
            )
        except Exception as exc:
            busy_err = str(exc)
    debug_log(
        f"[BUSYCHECK] sess_busy={sess_busy} conv_busy={conv_busy} "
        f"has_ctx={bool(robot_job_context)} "
        f"robot_id={str((robot_job_context or {}).get('robot_id', ''))[:8]} "
        f"conv_key={str((robot_job_context or {}).get('conversation_key', ''))} "
        f"err={busy_err}"
    )
    return sess_busy or conv_busy
''',
'''def _conversation_turn_busy(agent_session, robot_job_context: dict | None) -> bool:
    if _session_turn_busy(agent_session):
        return True
    if not robot_job_context:
        return False
    try:
        from app.services.agent.integrations.hooks import (
            is_integration_conversation_processing,
        )

        return bool(
            is_integration_conversation_processing(
                robot_job_context.get("robot_id", ""),
                robot_job_context.get("conversation_key", ""),
            )
        )
    except Exception:
        return False
'''
),
(
'''def flush_job_results_for_turn_end(item_id: str, conversation_key: str = "") -> bool:
    entries = _pop_buffered_job_results(item_id, conversation_key)
    debug_log(
        f"[BUSYCHECK] flush_job_results_for_turn_end item={item_id} "
        f"conv_key={conversation_key} popped={len(entries)}"
    )
    return flush_background_job_results_for_entries(item_id, entries)
''',
'''def flush_job_results_for_turn_end(item_id: str, conversation_key: str = "") -> bool:
    entries = _pop_buffered_job_results(item_id, conversation_key)
    return flush_background_job_results_for_entries(item_id, entries)
'''
),
])

patch(SVC, [
(
'''        timeout = timedelta(seconds=CONVERSATION_PROCESSING_MAX_TIMEOUT_SECONDS)
        with self._lock:
            controller = self._conversation_controllers.get(key)
            if controller is None:
                logger.info("[DBGPROC] extend_processing: controller MISSING conv=%s", conversation_key)
                return
            controller.processing = True
            controller.processing_expires_at = now + timeout
            controller.updated_at = now
            logger.info("[DBGPROC] extend_processing: SET processing=True conv=%s", conversation_key)
''',
'''        timeout = timedelta(seconds=CONVERSATION_PROCESSING_MAX_TIMEOUT_SECONDS)
        with self._lock:
            controller = self._conversation_controllers.get(key)
            if controller is None:
                return
            controller.processing = True
            controller.processing_expires_at = now + timeout
            controller.updated_at = now
'''
),
(
'''        sleep_when_no_reply: bool = False,
    ) -> None:
        logger.info(
            "[DBGPROC] apply_reply_context_result conv=%s sent=%s gen=%s sleep_no_reply=%s",
            conversation_key, robot_message_sent, conversation_generation, sleep_when_no_reply,
        )
        if robot_message_sent:
            self._remember_reply_context_window_for_key(
''',
'''        sleep_when_no_reply: bool = False,
    ) -> None:
        if robot_message_sent:
            self._remember_reply_context_window_for_key(
'''
),
(
'''            if expected_generation is not None and controller.generation != expected_generation:
                logger.info(
                    "[DBGPROC] remember_window: GEN MISMATCH conv=%s expected=%s current=%s (no state change)",
                    conversation_key, expected_generation, controller.generation,
                )
                return
            controller.expires_at = expires_at
            controller.processing_expires_at = None
            controller.sleeping = False
            controller.processing = False
            controller.updated_at = now
            logger.info("[DBGPROC] remember_window: SET processing=False conv=%s gen=%s", conversation_key, controller.generation)
''',
'''            if expected_generation is not None and controller.generation != expected_generation:
                return
            controller.expires_at = expires_at
            controller.processing_expires_at = None
            controller.sleeping = False
            controller.processing = False
            controller.updated_at = now
'''
),
(
'''            result = connection.list_jobs_http(item_uuid=item_id)
            if not isinstance(result, dict) or not result.get("success"):
                logger.info("[DBGPROC] item_has_running_jobs item=%s -> False (list failed)", item_id)
                return False
            for job in result.get("jobs") or []:
                if isinstance(job, dict) and str(job.get("status") or "") == "running":
                    logger.info("[DBGPROC] item_has_running_jobs item=%s -> True", item_id)
                    return True
            logger.info("[DBGPROC] item_has_running_jobs item=%s -> False (no running)", item_id)
            return False
        except Exception as exc:
            logger.info("[DBGPROC] item_has_running_jobs item=%s -> False (error %s)", item_id, exc)
            return False
''',
'''            result = connection.list_jobs_http(item_uuid=item_id)
            if not isinstance(result, dict) or not result.get("success"):
                return False
            for job in result.get("jobs") or []:
                if isinstance(job, dict) and str(job.get("status") or "") == "running":
                    return True
            return False
        except Exception:
            return False
'''
),
(
'''                    flushed = flush_job_results_for_turn_end(
                        str(job.item_id),
                        conversation_key=job.conversation_key,
                    )
                    logger.info(
                        "[DBGPROC] turn_end flush item=%s conv=%s flushed=%s",
                        job.item_id, job.conversation_key, flushed,
                    )
''',
'''                    flush_job_results_for_turn_end(
                        str(job.item_id),
                        conversation_key=job.conversation_key,
                    )
'''
),
])
print("ALL REVERTED")
