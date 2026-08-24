# TermPaws

AI 驱动的多终端管理平台：一个 Web 界面统一管理所有主机终端，内置 Agent 帮你执行任务，QQ/Telegram 等机器人入口开箱即用。

![终端列表](docs/images/shot_list.png)
![任务调度](docs/images/shot_dispatcher.png)
![抽屉终端](docs/images/shot_drawer.png)

## 快速开始（Docker，推荐）

### 一体机（backend + frontend，单容器单端口）

```bash
git clone https://github.com/FLYLX/TermMan.git && cd TermMan
docker build -f dockerfiles/aio.Dockerfile -t termpaws:aio dockerfiles
docker run -d --name termpaws \
  -p 28888:28888 -p 32000-32111:32000-32111 \
  -v termpaws-data:/root/.termpaws \
  termpaws:aio
```

打开 http://localhost:28888 ，按页面提示创建管理员账号。配置/数据库/向量库/知识库全部持久化在 `termpaws-data` 卷里（`/root/.termpaws/termpaws.json` 是配置文件）。

### daemon（装到每一台受控主机）

```bash
docker build -f dockerfiles/daemon.Dockerfile -t termpaws:daemon dockerfiles
docker run -d --name termpaws-daemon \
  -p 39999:39999 \
  -v termpaws-daemon-data:/opt/termpaws-daemon \
  termpaws:daemon
```

日志里找 `API Key: tpd_...`，在 Web 界面添加终端时填入：`http://<daemon主机IP>:39999` + 该 key。

### NapCat（QQ 机器人，可选）

```bash
docker build -f dockerfiles/napcat.Dockerfile -t termpaws:napcat dockerfiles
docker run -d --name napcat -p 6099:6099 termpaws:napcat
```

打开日志里带 token 的 WebUI 地址（`http://localhost:6099/webui?token=...`），登录 QQ 后配置 OneBot V11 反向 WS：`ws://<termpaws地址>:28888/robot-bridge/onebot/v11/ws`。

### 其他镜像

`dockerfiles/` 下还有 `backend.Dockerfile`（纯 API）和 `frontend.Dockerfile`（纯静态前端，需自行反代 `/api`）。全部支持 `--build-arg TERMPAWS_VERSION=x.y.z` 钉版本。

## pip 安装（备选）

```bash
pip install termpaws        # backend + frontend
termpaws run                # 首跑生成 ~/.termpaws/termpaws.json，网页创建管理员

pip install termpaws-daemon # 受控主机
termpaws-daemon
```

Linux 生产可一键注册 systemd：`sudo termpaws service install` / `sudo termpaws-daemon service install`。

## 亮点

- **AI Agent 操作终端**：自然语言下任务，Agent 自动建 plan、执行、汇报进度，支持随时取消
- **多入口统一会话**：Web 聊天、QQ 机器人、终端输出、定时任务汇入同一个会话，消息智能合并，回复各回各家
- **机器人桥内嵌**：QQ/Telegram/Discord 等平台适配器直接跑在 backend 里（基于 NoneBot2），插件热启停
- **语义记忆**：内置 bge 向量模型（离线打包进 wheel），长期记忆/知识库开箱即用
- **一键部署**：单容器单端口，配置自动生成

## 架构

```
QQ/机器人 ──→ robot-bridge（内嵌于 backend）──┐
Web UI ────────────────────────────────────→ backend（FastAPI，Agent 核心）
                                               │  HTTP / Socket.IO / HMAC 鉴权
                                               ▼
                                        daemon（PTY 终端 / 任务执行沙箱，可多台）
```

| 组件 | PyPI 包 | 职责 |
|---|---|---|
| backend | `termpaws-backend` | REST API、Agent 运行时、MCP host、插件 host |
| frontend | `termpaws-frontend` | Web UI 静态资源，由 backend 同源托管 |
| daemon | `termpaws-daemon` | 终端进程管理、job 执行，装在受控主机上 |
| meta | `termpaws` | 一键全装 |

## 数据与配置

| 位置 | 内容 |
|---|---|
| `~/.termpaws/termpaws.json` | backend 配置（密钥、数据库路径、镜像源等） |
| `~/.termpaws/data/` | SQLite 数据库、向量库、知识库、记忆 |
| `daemon.json` | daemon 配置（API_KEY，首跑自动生成） |

## 架构创新点

1. **统一合并队列**：所有来源的消息进入 per-item 单消费者队列，合并成批次轮次——连发 10 条消息只开 2 轮 LLM 调用
2. **Reply Ticket 路由**：每条输入入队时绑定回复路由，投递层按 ticket 扇出，代码零猜测；SQLite 持久化，重启恢复
3. **意图判定全归 LLM**：代码里没有任何正则/关键词猜测用户意图
4. **来源可插拔**：接入新平台 = 实现一个 `AgentIntegration` 接口，核心零改动
5. **plan 生命周期由系统保证**：任务取消时系统直接终止 plan，不依赖 LLM 自觉

详细设计见 [AGENT_ARCHITECTURE.md](AGENT_ARCHITECTURE.md)。

## License

MIT
