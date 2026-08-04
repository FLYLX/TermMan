import pathlib
for f in pathlib.Path("backend/skills/system").rglob("*"):
    if f.is_file() and f.suffix in {".yaml", ".yml", ".md", ".txt"}:
        t = f.read_text(encoding="utf-8")
        print("="*8, str(f), "chars:", len(t))
        print(t.encode("unicode_escape").decode("ascii")[:2500])
