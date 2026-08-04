import pathlib
p = pathlib.Path(r"E:\dev\TermMan\dev\TermMan\backend\app\api\routes\chat.py")
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
# 1-based lines 1458..1533 -> 0-based 1457..1532
start, end = 1457, 1533
assert lines[start].startswith("                    if normalized_source_type == SOURCE_WEB"), lines[start][:60]
assert lines[end-1].strip() == ")", lines[end-1]
for i in range(start, end):
    if lines[i].strip():
        assert lines[i].startswith("    "), f"line {i+1} has no indent"
        lines[i] = lines[i][4:]
p.write_text("".join(lines), encoding="utf-8")
print("dedented final-response block")
