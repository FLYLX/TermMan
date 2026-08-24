# TermPaws Dockerfiles

One Dockerfile per deployment shape. All build straight from PyPI, no source checkout needed.

| File | What you get | Ports |
|---|---|---|
| `all-in-one.Dockerfile` | backend + frontend（同源单端口）+ daemon | 28888, 39999, 32000-32111 |
| `backend.Dockerfile` | backend only（API + 内嵌 robot bridge，无页面） | 28888 |
| `frontend.Dockerfile` | frontend only（静态 UI，需要指向一个 backend） | 27777 |
| `daemon.Dockerfile` | daemon only（终端节点） | 39999 |
| `napcat.Dockerfile` | NapCatQQ（QQ 协议连接器） | 6099 |

## Build & run

```bash
# all-in-one（最常用）
docker build -f dockerfiles/all-in-one.Dockerfile -t termpaws .
docker run -d -p 28888:28888 -p 39999:39999 termpaws

# 只跑 daemon（远程主机上）
docker build -f dockerfiles/daemon.Dockerfile -t termpaws-daemon .
docker run -d -p 39999:39999 termpaws-daemon

# NapCat
docker build -f dockerfiles/napcat.Dockerfile -t napcat .
docker run -d -p 6099:6099 napcat
```

All images accept `--build-arg TERMPAWS_VERSION=x.y.z`（napcat 用 `--build-arg NAPCAT_VERSION=x.y.z`）to pin a specific release.

## Wiring them together

- **backend 添加 daemon**：Web UI → 终端 → daemon 地址 `http://<daemon-host>:39999`，api_key 看 daemon 容器日志（首跑打印 `API Key: tpd_...`）
- **frontend-only 容器**：需要反代 `/api` 和 `/robot-bridge` 到 backend 地址
- **NapCat**：打开 `http://localhost:6099` 配置 OneBot V11 反向 WS：`ws://<termpaws-host>:28888/robot-bridge/onebot/v11/ws`
