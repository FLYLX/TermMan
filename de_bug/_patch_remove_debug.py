import pathlib
p = pathlib.Path("backend/app/api/routes/chat.py")
src = p.read_text(encoding="utf-8")
tools_dbg = """            logger.info(
                "[Chat][TOOLS_DEBUG] iter=%d source=%s bound=%d names=%s",
                iteration_index,
                turn_source,
                len(iteration_tools),
                [t.get("function", {}).get("name") for t in iteration_tools],
            )
"""
tok_dbg = """                    logger.info(
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
assert tools_dbg in src, "tools dbg not found"
assert tok_dbg in src, "tok dbg not found"
src = src.replace(tools_dbg, "", 1).replace(tok_dbg, "", 1)
p.write_text(src, encoding="utf-8")
print("debug logs removed")