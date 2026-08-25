from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

import uvicorn

BACKEND_DIR = Path(__file__).resolve().parent.parent

def _default_config(db_path: str) -> dict:
    return {
        "PROJECT_NAME": "TermPaws",
        "SECRET_KEY": secrets.token_urlsafe(32),
        "FIRST_SUPERUSER": "admin@example.com",
        "SQLITE_DATABASE_URL": f"sqlite:///{db_path}",
        "HF_ENDPOINT": "https://hf-mirror.com",
        "HF_HUB_DISABLE_XET": "1",
    }


def _inject_config(values: dict) -> None:
    for key, value in values.items():
        if value is None or key.startswith("_"):
            continue
        os.environ.setdefault(str(key), str(value))


def _ensure_config() -> Path:
    home = Path(os.environ.get("TERMPAWS_HOME", Path.home() / ".termpaws"))
    json_file = home / "termpaws.json"
    os.environ["TERMPAWS_HOME"] = str(home)

    if json_file.exists():
        import json

        _inject_config(json.loads(json_file.read_text(encoding="utf-8")))
    else:
        home.mkdir(parents=True, exist_ok=True)
        (home / "data").mkdir(exist_ok=True)
        db_path = (home / "data" / "sql_app.db").as_posix()
        config = _default_config(db_path)
        import json

        json_file.write_text(
            json.dumps(config, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        _inject_config(config)
        print(f"[TermPaws] First run: created config at {json_file}", flush=True)
        print("[TermPaws] 未初始化管理员——打开网页后按提示设置管理员账号和密码", flush=True)

    home.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("CHROMA_PERSIST_DIR", str(home / "chroma_data"))
    os.environ.setdefault(
        "AGENT_STATE_STORE_PATH", str(home / "data" / "agent_state.db")
    )
    os.environ.setdefault(
        "ROBOT_CONVERSATION_MEMORY_DIR", str(home / "robot_conversation_memory")
    )
    _seed_knowledge(home)
    _seed_runtime_assets(home)
    return home


def _seed_runtime_assets(home: Path) -> None:
    import shutil

    bundled_skills = BACKEND_DIR / "app" / "skills"
    target_skills = home / "skills"
    if bundled_skills.exists() and not target_skills.exists():
        shutil.copytree(bundled_skills, target_skills)
        print(f"[TermPaws] Seeded skills at {target_skills}", flush=True)

    bundled_mcp = BACKEND_DIR / "app" / "mcp_servers.json"
    target_mcp = home / "mcp_servers.json"
    if bundled_mcp.exists() and not target_mcp.exists():
        shutil.copy2(bundled_mcp, target_mcp)
        print(f"[TermPaws] Seeded mcp_servers.json at {target_mcp}", flush=True)


def _seed_knowledge(home: Path) -> None:
    import shutil

    target = home / "knowledge"
    bundled = BACKEND_DIR / "app" / "knowledge"
    os.environ.setdefault("KNOWLEDGE_BASE_DIR", str(target))
    if target.exists() or not bundled.exists():
        return
    shutil.copytree(bundled, target, ignore=shutil.ignore_patterns(".gitkeep"))
    print(f"[TermPaws] Seeded knowledge base at {target}", flush=True)


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


SYSTEMD_UNIT = """\
[Unit]
Description=TermPaws
After=network.target

[Service]
Type=simple
ExecStart={exe} run
Restart=always
RestartSec=5
Environment=TERMPAWS_HOME={home}
Environment=PYTHONUNBUFFERED=1
Environment=MALLOC_ARENA_MAX=2

[Install]
WantedBy=multi-user.target
"""


def _service(args: list[str]) -> None:
    exe = Path(sys.executable).parent / "termpaws"
    home = os.environ.get("TERMPAWS_HOME", str(Path.home() / ".termpaws"))
    unit = SYSTEMD_UNIT.format(exe=exe, home=home)

    if args[:1] == ["install"]:
        if sys.platform != "linux":
            sys.exit("service install is only supported on Linux (systemd)")
        unit_path = Path("/etc/systemd/system/termpaws.service")
        try:
            unit_path.write_text(unit, encoding="utf-8")
        except PermissionError:
            sys.exit(f"Permission denied, re-run with sudo or write {unit_path} manually")
        import subprocess

        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", "--now", "termpaws"], check=True)
        print("[TermPaws] Service installed and started: systemctl status termpaws", flush=True)
    else:
        print(unit)


def _seed_embedding_cache() -> None:
    """wheel 内置的模型缓存播种到 fastembed 缓存目录（离线可用）。"""
    import shutil
    import tempfile

    bundled = BACKEND_DIR / "app" / "bundled_fastembed_cache"
    if not bundled.exists():
        return
    target_root = Path(
        os.environ.get(
            "FASTEMBED_CACHE_PATH",
            str(Path(tempfile.gettempdir()) / "fastembed_cache"),
        )
    )
    for src in bundled.iterdir():
        dst = target_root / src.name
        if not dst.exists():
            shutil.copytree(src, dst)
            print(f"[TermPaws] Seeded embedding model cache: {dst}", flush=True)


def _warm_embedding_model() -> None:
    """启动时经国内镜像下载/加载 embedding 模型；运行时严格本地。"""
    try:
        from fastembed import TextEmbedding

        from app.core.config import settings

        print("[TermPaws] Preparing local embedding model...", flush=True)
        _seed_embedding_cache()
        TextEmbedding(model_name=settings.EMBEDDING_MODEL_NAME)
        print("[TermPaws] Embedding model ready (local)", flush=True)
    except Exception as exc:
        print(f"[TermPaws] Embedding model prepare failed: {exc}", flush=True)


def _serve() -> None:
    host = os.environ.get("BACKEND_HOST", "0.0.0.0")
    port = int(os.environ.get("BACKEND_PORT", "28888"))
    import threading

    threading.Thread(target=_warm_embedding_model, daemon=True).start()
    # Single process, single port: page + API + robot bridge (embedded) are all
    # served on the same app. NapCat connects to ws://host:28888/robot-bridge/onebot/v11/ws
    uvicorn.run("app.main:app", host=host, port=port)


HELP = """TermPaws — AI terminal management platform

usage: termpaws <command>

commands:
  run, serve       Start the server (default when no command given).
                   First run creates ~/.termpaws/termpaws.json; the first
                   visitor sets the admin account in the web UI.
  migrate          Run database migrations only, then exit.
  service          Print the systemd unit template to stdout.
  service install  Register and start the systemd service (Linux, root required).
  help, --help     Show this help.

config:   ~/.termpaws/termpaws.json   (env vars take precedence)
data:     ~/.termpaws/                (sqlite, vector store, knowledge)
listen:   0.0.0.0:28888               (page + API + robot bridge, same port)
"""


def main() -> None:
    args = sys.argv[1:]
    command = args[0] if args else "serve"

    if command in {"serve", "run"}:
        _ensure_config()
        # settings 在 prestart 阶段就会实例化，端口必须在此之前就位
        os.environ.setdefault("BACKEND_PORT", "28888")
        if os.environ.get("TERMPAWS_SKIP_PRESTART", "").lower() not in {"1", "true", "yes"}:
            _run_prestart()
        _serve()
    elif command == "migrate":
        _run_prestart()
    elif command == "service":
        _service(args[1:])
    elif command in {"help", "--help", "-h"}:
        print(HELP)
    else:
        print(HELP, file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
