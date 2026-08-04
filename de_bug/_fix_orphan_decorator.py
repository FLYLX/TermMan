import pathlib
p = pathlib.Path(r"E:\dev\TermMan\dev\TermMan\backend\app\services\agent\prompts\policy.py")
text = p.read_text(encoding="utf-8")
old = "\n\n@dataclass(frozen=True)\n\nEXPLICIT_MEMORY_CUES = ("
new = "\n\n\nEXPLICIT_MEMORY_CUES = ("
assert text.count(old) == 1
text = text.replace(old, new)
p.write_text(text, encoding="utf-8")
print("orphan decorator removed")
