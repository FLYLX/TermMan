from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dist"

PACKAGES = [
    ROOT / "backend",
    ROOT / "packaging" / "frontend",
    ROOT / "daemon",
    ROOT / "packaging" / "meta",
]


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()

    for pkg in PACKAGES:
        print(f"==> building {pkg.relative_to(ROOT)}")
        subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(OUT), str(pkg)],
            check=True,
        )

    print(f"\nDone. Wheels in {OUT}:")
    for whl in sorted(OUT.glob("*.whl")):
        print(f"  {whl.name}")


if __name__ == "__main__":
    main()
