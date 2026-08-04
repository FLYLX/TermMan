import pathlib
p = pathlib.Path("backend/app/services/agent/tool_selection.py")
src = p.read_text(encoding="utf-8")

old_header = '''    lines = [
        "## On-demand capabilities (progressive loading)",
        (
            "The capabilities below are NOT loaded yet. Before using one, call "
            f"`{PREPARE_CAPABILITIES_TOOL}` with item_id and the exact names you "
            "need; the full tool schemas / guide text are returned and stay "
            "available for this item afterwards."
        ),
    ]'''
new_header = '''    lines = [
        "## On-demand capabilities (not loaded yet)",
        (
            f"To use one, call `{PREPARE_CAPABILITIES_TOOL}` with item_id and the "
            "exact names; full schemas/guides are returned and stay loaded for this item."
        ),
    ]'''
assert old_header in src, "header anchor not found"
src = src.replace(old_header, new_header, 1)

old_trunc = '            if len(description) > 120:\n                description = description[:117] + "..."'
new_trunc = '            if len(description) > 60:\n                description = description[:57] + "..."'
count = src.count(old_trunc)
assert count == 2, f"trunc anchor count={count}"
src = src.replace(old_trunc, new_trunc)

p.write_text(src, encoding="utf-8")
print("tool_selection catalog trimmed")