from pathlib import Path

DIST_DIR = Path(__file__).resolve().parent / "dist"


def dist_path() -> str:
    return str(DIST_DIR)
