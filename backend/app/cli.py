from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

import uvicorn

BACKEND_DIR = Path(__file__).resolve().parent.parent

ENV_TEMPLATE = """\
# TermPaws configuration
PROJECT_NAME=TermPaws
SECRET_KEY={secret_key}
FIRST_SUPERUSER=admin@example.com
FIRST_SUPERUSER_PASSWORD={admin_password}
SQLITE_DATABASE_URL=sqlite:///{db_path}
# BACKEND_PORT=8000
# BACKEND_CORS_ORIGINS=http://localhost:5173
"""


def _ensure_config() -> Path:
    home = Path(os.environ.get("TERMPAWS_HOME", Path.home() / ".termpaws"))
    env_file = home / ".env"
    if not env_file.exists():
        home.mkdir(parents=True, exist_ok=True)
        (home / "data").mkdir(exist_ok=True)
        admin_password = secrets.token_urlsafe(12)
        db_path = (home / "data" / "sql_app.db").as_posix()
        env_file.write_text(
            ENV_TEMPLATE.format(
                secret_key=secrets.token_urlsafe(32),
                admin_password=admin_password,
                db_path=db_path,
            ),
            encoding="utf-8",
        )
        print(f"[TermPaws] First run: created config at {env_file}")
        print(f"[TermPaws] Admin account: admin@example.com / {admin_password}")
        print("[TermPaws] Edit the .env file and restart to apply changes.")
    os.environ["TERMPAWS_ENV_FILE"] = str(env_file)
    return home


def _run_prestart() -> None:
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    from app.backend_pre_start import init as wait_for_db
    from app.core.db import engine
    from app.initial_data import init as init_data

    wait_for_db(engine)

    alembic_ini = BACKEND_DIR / "alembic.ini"
    if alembic_ini.exists():
        alembic_cfg = AlembicConfig(str(alembic_ini))
        alembic_cfg.set_main_option("script_location", str(BACKEND_DIR / "app" / "alembic"))
        alembic_command.upgrade(alembic_cfg, "head")

    init_data()


def main() -> None:
    args = sys.argv[1:]
    command = args[0] if args else "serve"

    if command in {"serve", "run"}:
        _ensure_config()
        if os.environ.get("TERMPAWS_SKIP_PRESTART", "").lower() not in {"1", "true", "yes"}:
            _run_prestart()
        uvicorn.run(
            "app.main:app",
            host=os.environ.get("BACKEND_HOST", "0.0.0.0"),
            port=int(os.environ.get("BACKEND_PORT", "8000")),
            workers=int(os.environ.get("BACKEND_WORKERS", "1")),
        )
    elif command == "migrate":
        _run_prestart()
    else:
        print("usage: termpaws [run|serve|migrate]", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
