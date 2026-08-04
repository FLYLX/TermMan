import io, pathlib
p = pathlib.Path("backend/app/api/routes/chat.py")
src = p.read_text(encoding="utf-8")
anchor = """            iteration_tools = (
                []
                if finalization_only
                else select_tools_for_turn(
                    agent.get_tools_for_litellm(),
                    source=turn_source,
                    agent=agent,
                    reply_ticket_id=reply_ticket.ticket_id,
                )
            )
"""
add = """            logger.info(
                "[Chat][TOOLS_DEBUG] iter=%d source=%s bound=%d names=%s",
                iteration_index,
                turn_source,
                len(iteration_tools),
                [t.get("function", {}).get("name") for t in iteration_tools],
            )
"""
assert anchor in src, "anchor not found"
assert "TOOLS_DEBUG" not in src, "already patched"
src = src.replace(anchor, anchor + add, 1)
p.write_text(src, encoding="utf-8")
print("patched chat.py")