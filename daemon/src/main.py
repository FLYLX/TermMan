import os
import socketio
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sys

# 添加当前目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core import config
from utils import logger
from api import router, sio
from service import terminal_manager

# 创建FastAPI应用
fastapi_app = FastAPI(
    title="TermPaws Daemon",
    description="Terminal Management Daemon API",
    version="0.1.0"
)

# 配置CORS
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@fastapi_app.get("/")
def root():
    """
    Daemon健康检查接口
    """
    return {
        "message": "TermPaws Daemon is running",
        "version": "0.1.0"
    }

# 注册HTTP路由
fastapi_app.include_router(router, prefix="/api")

# 创建WSGI应用，将Socket.IO和FastAPI结合
app = socketio.ASGIApp(sio, fastapi_app)


def _ensure_api_key() -> str:
    key = config.get("API_KEY")
    if key:
        return key
    import json
    import secrets

    key = f"tpd_{secrets.token_urlsafe(24)}"
    json_path = os.path.join(os.getcwd(), "daemon.json")
    data = {}
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    data["API_KEY"] = key
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    config.config_data["API_KEY"] = key
    print(f"[TermPaws Daemon] First run: generated API_KEY={key}", flush=True)
    print(f"[TermPaws Daemon] Saved to {json_path} — add this key in the backend UI", flush=True)
    return key


SYSTEMD_UNIT = """\
[Unit]
Description=TermPaws Daemon
After=network.target

[Service]
Type=simple
WorkingDirectory={workdir}
ExecStart={exe}
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""

HELP = """TermPaws Daemon — terminal agent node

usage: termpaws-daemon [command]

commands:
  run, serve       Start the daemon (default when no command given).
                   First run creates ./daemon.json with a generated API_KEY
                   and prints it — add this key in the backend web UI.
  service          Print the systemd unit template to stdout.
  service install  Register and start the systemd service (Linux, root required).
                   WorkingDirectory is fixed to the current directory.
  help, --help     Show this help.

config:   ./daemon.json   (env vars take precedence)
listen:   0.0.0.0:39999
"""


def _service(args: list) -> None:
    import sys

    exe = os.path.join(os.path.dirname(sys.executable), "termpaws-daemon")
    workdir = os.getcwd()
    unit = SYSTEMD_UNIT.format(exe=exe, workdir=workdir)

    if args[:1] == ["install"]:
        if sys.platform != "linux":
            sys.exit("service install is only supported on Linux (systemd)")
        unit_path = "/etc/systemd/system/termpaws-daemon.service"
        try:
            with open(unit_path, "w", encoding="utf-8") as f:
                f.write(unit)
        except PermissionError:
            sys.exit(f"Permission denied, re-run with sudo or write {unit_path} manually")
        import subprocess

        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", "--now", "termpaws-daemon"], check=True)
        print("[TermPaws Daemon] Service installed and started: systemctl status termpaws-daemon", flush=True)
    else:
        print(unit)


def main() -> None:
    import sys

    args = sys.argv[1:]
    command = args[0] if args else "serve"

    if command == "service":
        _service(args[1:])
        return
    if command in {"help", "--help", "-h"}:
        print(HELP)
        return
    if command not in {"serve", "run"}:
        print(HELP, file=sys.stderr)
        raise SystemExit(2)

    # 获取配置
    host = config.get("HOST")
    port = config.get("PORT")
    api_key = _ensure_api_key()

    logger.info(f"Starting TermPaws Daemon on {host}:{port}")
    logger.info(f"API Key: {api_key}")

    # 启动服务器
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )


if __name__ == "__main__":
    main()
