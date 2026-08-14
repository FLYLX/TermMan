import pathlib
p = pathlib.Path(r"E:\dev\TermPaws\dev\TermPaws\backend\app\api\routes\chat.py")
text = p.read_text(encoding="utf-8")
old = "@dataclass\ndef get_relevant_memories("
assert text.count(old) == 1
text = text.replace(old, "def get_relevant_memories(")
old_imp = "from dataclasses import dataclass\n"
assert text.count(old_imp) == 1
text = text.replace(old_imp, "")
p.write_text(text, encoding="utf-8")
print("fixed stray @dataclass")
