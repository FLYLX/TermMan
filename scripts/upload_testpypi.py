"""Upload TermPaws wheels to TestPyPI. Works on Windows/Linux/macOS.

1. Paste your token into TOKEN below (this file is gitignored, never commit it)
2. Run: python scripts/upload_testpypi.py
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

TOKEN = "pypi-AgENdGVzdC5weXBpLm9yZwIkM2Q3ZmI3NjctYWI0OS00MjM0LWJlY2MtODk0YzM2Yjc1YjIyAAIqWzMsImRmYjU0MTM4LTEyNmUtNDBiNi05OTgzLWFiOWY1YWEzMmQ2OCJdAAAGIO_qZJgQCdwb5wnJGgaH76dj3ZZunhSxQVU3HtTxyz6a"

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

def find_wheels() -> tuple[list[Path], list[Path]]:
    wheels = sorted(DIST.glob("*.whl"))
    meta = [w for w in wheels if w.name.startswith("termpaws-0")]
    first = [w for w in wheels if w not in meta]
    if not wheels or not meta:
        sys.exit(f"wheels missing in {DIST}, build first")
    return first, meta


def run(cmd: list[str]) -> None:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    subprocess.run(cmd, check=True, cwd=ROOT, env=env)


def main() -> None:
    if not TOKEN.startswith("pypi-"):
        sys.exit("Edit this script first: put your TestPyPI token in TOKEN")

    if shutil.which("twine") is None:
        run([sys.executable, "-m", "pip", "install", "twine"])

    run([sys.executable, "scripts/build_wheels.py"])

    def upload(wheels: list[Path]) -> None:
        run([
            sys.executable, "-m", "twine", "upload", "--repository", "testpypi",
            *[str(w) for w in wheels],
            "-u", "__token__", "-p", TOKEN,
        ])

    first, meta = find_wheels()
    upload(first)  # independent packages first
    upload(meta)   # meta depends on the others

    print("\nDone. Verify install with:")
    print("  pip install --index-url https://test.pypi.org/simple "
          "--extra-index-url https://pypi.org/simple termpaws")


if __name__ == "__main__":
    main()
