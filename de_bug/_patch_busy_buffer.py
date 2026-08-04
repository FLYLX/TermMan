import pathlib, re
p = pathlib.Path("backend/app/services/agent/mcp/local_server.py")
src = p.read_text(encoding="utf-8")
assert "buffered while turn active" not in src, "already patched"

# 1) eviction safety net in buffer_background_job_result
old_buf = '''def buffer_background_job_result(item_id: str, entry: dict[str, Any]) -> None:
    input_merge_buffer.add(
        MergeBufferEntry(
            source_type=SOURCE_JOB_RESULT,
            item_id=str(item_id),
            scope_key=str(entry.get("conversation_key") or ""),
            sender_label="background_job",
            content=str(entry.get("command") or ""),
            reply_ticket_id=str(entry.get("reply_ticket_id") or ""),
            payload=entry,
        )
    )
'''
new_buf = '''def buffer_background_job_result(item_id: str, entry: dict[str, Any]) -> None:
    _pending_size, evicted = input_merge_buffer.add(
        MergeBufferEntry(
            source_type=SOURCE_JOB_RESULT,
            item_id=str(item_id),
            scope_key=str(entry.get("conversation_key") or ""),
            sender_label="background_job",
            content=str(entry.get("command") or ""),
            reply_ticket_id=str(entry.get("reply_ticket_id") or ""),
            payload=entry,
        )
    )
    if evicted:
        evicted_entries = [e.payload for e in evicted if e.payload is not None]
        debug_log(
            f"[LocalMCPServer] job result buffer overflow: flushing {len(evicted_entries)} "
            f"evicted result(s) immediately, item={item_id}"
        )
        if evicted_entries:
            flush_background_job_results_for_entries(item_id, evicted_entries)
'''
assert old_buf in src, "buffer anchor not found"
src = src.replace(old_buf, new_buf, 1)

# 2) busy-aware delivery: replace comment+flush tail via regex (avoids special chars)
tail_pattern = re.compile(
    r"            # Always deliver immediately.*?\n"
    r"            flush_background_job_results_for_entries\(item_id, \[entry\]\)\n",
    re.S,
)
new_tail = '''            if busy:
                # A turn is running: park the result in the merge buffer so
                # results finishing during this turn are merged into ONE
                # follow-up turn at turn end. Idle conversations still get an
                # immediate turn (else branch), so nothing waits artificially.
                buffer_background_job_result(item_id, entry)
                debug_log(
                    f"[LocalMCPServer] job result buffered while turn active: "
                    f"item={item_id}, command={command}"
                )
                if not _conversation_turn_busy(agent_session, robot_job_context):
                    flush_job_results_for_turn_end(
                        item_id,
                        str(entry.get("conversation_key") or ""),
                    )
            else:
                flush_background_job_results_for_entries(item_id, [entry])
'''
matches = tail_pattern.findall(src)
assert len(matches) == 1, f"tail pattern matches={len(matches)}"
src = tail_pattern.sub(new_tail, src, count=1)

# 3) refactor busy computation into helper
old_busy = '''            busy = _session_turn_busy(agent_session)
            if robot_job_context and not busy:
                try:
                    from app.services.agent.integrations.hooks import (
                        is_integration_conversation_processing,
                    )

                    busy = is_integration_conversation_processing(
                        robot_job_context.get("robot_id", ""),
                        robot_job_context.get("conversation_key", ""),
                    )
                except Exception:
                    busy = False
'''
new_busy = '''            busy = _conversation_turn_busy(agent_session, robot_job_context)
'''
assert old_busy in src, "busy anchor not found"
src = src.replace(old_busy, new_busy, 1)

# 4) helper next to _session_turn_busy
helper_anchor = "def _session_turn_busy(agent_session) -> bool:"
assert helper_anchor in src
helper = '''def _conversation_turn_busy(agent_session, robot_job_context: dict | None) -> bool:
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
src = src.replace(helper_anchor, helper + helper_anchor, 1)

p.write_text(src, encoding="utf-8")
print("busy-buffer delivery implemented")