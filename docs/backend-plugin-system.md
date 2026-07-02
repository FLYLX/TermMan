# Backend Plugin System

记录日期：2026-06-12

## 定位

现在已经有第一版“内置插件市场”：

- WebUI 侧边栏有 `Plugins` 页面。
- backend 提供 `/api/v1/plugins` catalog。
- 用户可以在 WebUI 里查看内置插件、启用/停用插件、reload 插件。
- 启用状态持久化到 `.runtime/plugin_marketplace.json`。
- 环境变量仍作为默认值，例如 `ROBOT_PLUGIN_ENABLED` 是 robot 第一次进入市场时的默认启用状态。

这还不是第三方插件市场：当前不下载任意代码包，不安装 zip，不做签名校验，也不运行第三方沙箱进程。当前市场管理的是内置插件。

## 当前内置插件

- `termman.robot`
  - 类型：`messaging`
  - 目录：`backend/app/plugins/robot/`
  - 能力：API、agent integration、startup/shutdown
  - 作用：QQ robot server、OneBot V11 QQ 接入、robot MCP、robot conversation memory。

- `termman.terminal_ws`
  - 类型：`terminal`
  - 目录：`backend/app/plugins/terminal_ws/`
  - 能力：API、shutdown
  - 作用：用户在 WebUI 的某个终端页里创建专属 WebSocket Server。

## API

```text
GET   /api/v1/plugins/
GET   /api/v1/plugins/{plugin_id}
PATCH /api/v1/plugins/{plugin_id}
POST  /api/v1/plugins/reload
```

更新插件启用状态：

```json
{
  "enabled": false
}
```

返回字段：

```json
{
  "plugin_id": "termman.robot",
  "name": "Robot",
  "version": "builtin",
  "description": "Optional QQ robot server integration through OneBot V11 connectors and MCP.",
  "builtin": true,
  "category": "messaging",
  "enabled": true,
  "default_enabled": true,
  "configurable": true,
  "capabilities": ["agent", "api", "startup", "shutdown"]
}
```

普通登录用户可以查看插件列表；启用、停用、reload 只允许 superuser。

## 启停语义

插件启用状态影响：

- `PluginManager.enabled_plugins()`
- agent integration 注册
- startup/shutdown 生命周期
- 插件自己的运行时 guard

FastAPI router 已经 include 后不能安全卸载，所以插件 router 会常驻注册；具体插件 API 需要在插件内部通过 guard 判断当前启用状态。比如 robot 禁用后，`/api/v1/robots/...` 会返回 `404 Robot plugin is disabled`。

terminal_ws 禁用后，终端页的 WebSocket Server API 会返回 `404 Terminal WebSocket plugin is disabled`。

## 目录约定

```text
backend/app/services/plugins/
  __init__.py
  contracts.py       # BackendPlugin / PluginEntrypoints
  manager.py         # catalog、状态持久化、启停、reload、生命周期

backend/app/api/routes/plugins.py
  # 内置插件市场 API

frontend/src/routes/_layout/plugins.tsx
  # WebUI 插件市场页面

backend/app/plugins/
  robot/
  terminal_ws/
```

新增内置插件时应提供：

```py
def get_backend_plugin() -> BackendPlugin:
    return BackendPlugin(
        plugin_id="termman.example",
        name="Example",
        version="builtin",
        category="example",
        description="...",
        enabled=lambda: True,
        entrypoints=PluginEntrypoints(...),
    )
```

然后把模块加入：

```py
PluginManager._builtin_plugin_modules()
```

## Agent 边界

核心 agent 不 import 具体插件实现，只通过：

```text
backend/app/services/agent/integrations/
  contracts.py
  registry.py
  hooks.py
```

调用聚合 hook：

- prompt
- skill
- MCP server factory
- history scope
- context injection
- delivery retry/fallback

robot 插件启用时才注册 `RobotAgentIntegration`；禁用后 agent hook 返回空，不影响普通 terminal agent。

## Reload 边界

`plugin_manager.reload()` 会：

- `importlib.invalidate_caches()`
- 重新加载内置插件 descriptor
- 重新加载 agent integration registry

它不会：

- 卸载已经 include 到 FastAPI 的 router
- 热替换所有已经 import 的 Python 模块源码
- 安装或卸载第三方插件包
- 自动重启所有长期运行的外部进程

因此当前支持的是“内置插件市场 + 内置插件启停/reload”，不是完整第三方插件市场。

## 后续插件市场方案

要扩展成真正插件市场，还需要：

- 插件 manifest，例如 `.termman-plugin/plugin.json`
- 插件包下载、安装、卸载、更新
- sha256 与签名校验
- 权限声明与授权 UI
- 插件进程/容器沙箱
- 插件 API/MCP/skill 的动态路由隔离
- 插件版本兼容性检查

当前实现先把架构入口、WebUI 管理入口、启停持久化和核心隔离做好。
