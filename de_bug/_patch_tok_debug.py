import pathlib
p = pathlib.Path("backend/app/api/routes/chat.py")
src = p.read_text(encoding="utf-8")
anchor = """                    _tt.record(
                        str(item_id),
                        str(handler.model or "unknown"),
                        int(getattr(_su, "prompt_tokens", 0) or 0),
                        int(getattr(_su, "completion_tokens", 0) or 0),
                        int(getattr(_su, "total_tokens", 0) or 0),
                        reply_ticket_id=str(
                            getattr(reply_ticket, "ticket_id", "") or ""
                        ),
                    )
"""
add = """                    logger.info(
                        "[Chat][TOK_DEBUG] iter=%d prompt=%s completion=%s msgs=%d msg_chars=%d tools_bound=%d per_msg=%s",
                        iteration_index,
                        getattr(_su, "prompt_tokens", None),
                        getattr(_su, "completion_tokens", None),
                        len(messages),
                        sum(len(str(m.get("content") or "")) for m in messages),
                        len(iteration_tools),
                        [(m.get("role"), len(str(m.get("content") or ""))) for m in messages],
                    )
"""
assert anchor in src, "anchor not found"
assert "TOK_DEBUG" not in src, "already patched"
src = src.replace(anchor, anchor + add, 1)
p.write_text(src, encoding="utf-8")
print("patched tok debug")