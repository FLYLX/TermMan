import { Code2, Copy, Check, Terminal, MessageSquare, Server, Zap } from "lucide-react"
import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { useI18n } from "@/components/locale-provider"
import { createFileRoute } from "@tanstack/react-router"

export const Route = createFileRoute("/_layout/plugin-dev")({
  component: PluginDevGuide,
})

function CodeBlock({ code, lang = "python" }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="relative">
      <button
        onClick={() => { navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 2000) }}
        className="absolute right-2 top-2 z-10 rounded-md bg-zinc-800 p-1.5 text-zinc-400 hover:text-zinc-100"
      >
        {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
      </button>
      <pre className="overflow-x-auto rounded-lg border border-zinc-800 bg-zinc-950 p-4 text-xs leading-relaxed text-zinc-300">
        <code>{code}</code>
      </pre>
    </div>
  )
}

function PluginDevGuide() {
  const { t } = useI18n()
  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-bold text-zinc-100">第三方插件开发指南</h1>
        <p className="text-sm text-zinc-400">
          TermMan 插件接口是标准化的。实现以下接口，即可接入任意聊天平台（Discord / Telegram / Kook 等）。
        </p>
      </div>

      <Card className="border-zinc-800 bg-zinc-900/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-zinc-100">
            <Server className="size-5 text-cyan-400" />
            1. 插件注册
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-zinc-400">在 <code className="rounded bg-zinc-800 px-1 text-cyan-300">app/plugins/your_platform/plugin.py</code> 创建插件入口：</p>
          <CodeBlock code={`from app.services.plugins.contracts import BackendPlugin, PluginEntrypoints

def get_backend_plugin() -> BackendPlugin:
    return BackendPlugin(
        plugin_id="termman.discord",
        name="Discord",
        version="1.0.0",
        description="Discord bot integration for TermMan",
        builtin=False,
        category="messaging",
        enabled=lambda: settings.DISCORD_PLUGIN_ENABLED,
        entrypoints=PluginEntrypoints(
            register_agent_integration=register_integration,
            include_router=include_router,
            startup=startup,
            shutdown=shutdown,
        ),
    )`} />
        </CardContent>
      </Card>

      <Card className="border-zinc-800 bg-zinc-900/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-zinc-100">
            <Zap className="size-5 text-amber-400" />
            2. Agent Integration（核心接口）
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-zinc-400">所有方法都是<strong>可选</strong>的，不实现的方法使用 NoopAgentIntegration 默认值。</p>
          <CodeBlock code={`class DiscordIntegration:
    name = "discord"

    # ── Prompt 层（卸载时自动消失）──
    def build_source_route(self, agent, *, source) -> str:
        \"\"\"返回当前来源的路由提示文本（如 'Discord channel #xxx'）\"\"\"
        if not self._is_discord_context(agent):
            return ""
        channel = self._get_channel_name(agent)
        return (
            "Current source route:\\n"
            f"- current source: Discord ({channel})\\n"
            "- reply contract: output reply text directly; "
            "the system auto-delivers to this Discord channel.\\n"
        )

    def build_ticket_prompt(self, ticket) -> str:
        \"\"\"返回 ticket 的 routing 指令文本\"\"\"
        if ticket.source_type != "discord":
            return ""
        return (
            "Authoritative reply ticket:\\n"
            f"- ticket_id: {ticket.ticket_id}\\n"
            "- source: Discord\\n"
            "- REPLY ROUTING: output reply text directly; "
            "system auto-delivers to this Discord channel.\\n"
        )

    def filter_skills(self, skills, agent) -> list:
        \"\"\"过滤重复的 skill（integration 已自带 messaging 规则时）\"\"\"
        if not self._is_discord_context(agent):
            return skills
        return [s for s in skills if s.skill_id not in DISCORD_COMPAT_SKILL_IDS]

    # ── Delivery 层（卸载时 fallback web）──
    def deliver_ticket(self, ticket, text) -> bool:
        \"\"\"把回复发送到 Discord（成功返回 True）\"\"\"
        if ticket.source_type != "discord":
            return False
        channel_id = ticket.reply_target.get("channel_id")
        await discord_bot.send_message(channel_id, text)
        return True

    def conversation_memory_append(self, ticket, text) -> None:
        \"\"\"记录会话记忆（可选）\"\"\"
        pass

    # ── Context 层 ──
    def setup_chat_context(self, agent, context) -> bool:
        \"\"\"注册 Discord context 到 agent（robot_id 等等价物）\"\"\"
        agent_context = agent._context
        agent_context.discord_guild_id = context["guild_id"]
        agent_context.discord_channel_id = context["channel_id"]
        return True

    def clear_chat_context(self, agent, context) -> None:
        \"\"\"清理 Discord context\"\"\"
        agent_context = agent._context
        agent_context.discord_guild_id = ""
        agent_context.discord_channel_id = ""

    def inject_tool_args(self, agent, *, server_name, tool_name, args) -> None:
        \"\"\"注入 context token 到工具参数（如 _discord_context_token）\"\"\"
        if tool_name in ("send_message", "sleep_conversation"):
            ctx = agent._context
            args["_discord_context_token"] = ctx.discord_context_token

    # ── Memory 层 ──
    def memory_scope_rank(self, agent, memory) -> int:
        \"\"\"Discord 记忆 scope 排序（同 channel 优先）\"\"\"
        metadata = memory.get("metadata", {})
        ctx = agent._context
        if not getattr(ctx, "discord_channel_id", ""):
            return 0
        mem_channel = metadata.get("discord_channel_id", "")
        if not mem_channel:
            return 0
        return 4 if mem_channel == ctx.discord_channel_id else -1

    # ── Item 事件层（监控终端输出等）──
    def on_terminal_output(self, item_id, content, *, source) -> None:
        \"\"\"终端有输出时触发（可转发到 Discord）\"\"\"
        if source == "filtered":
            return
        channel_id = self._get_notification_channel(item_id)
        if channel_id:
            asyncio.create_task(
                discord_bot.send_message(channel_id, f"[Terminal] {content[:200]}")
            )

    def on_item_event(self, item_id, event, payload) -> None:
        \"\"\"Item 生命周期事件（start/stop/error）\"\"\"
        if event == "item_started":
            pass  # 通知 Discord: 服务器启动了
        elif event == "item_stopped":
            pass  # 通知 Discord: 服务器停了

    # ── Tool/Skill 层 ──
    def builtin_skill_definitions(self) -> list:
        \"\"\"提供 Discord 专属 skill\"\"\"
        return [discord_messaging_skill]

    def builtin_mcp_server_factories(self) -> dict:
        \"\"\"提供 Discord MCP server（send_message/sleep 等工具）\"\"\"
        return {"discord": lambda: DiscordMCPServer()}`} />
        </CardContent>
      </Card>

      <Card className="border-zinc-800 bg-zinc-900/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-zinc-100">
            <Terminal className="size-5 text-emerald-400" />
            3. 接收消息（Item 输入）
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-zinc-400">
            通过 <code className="rounded bg-zinc-800 px-1 text-cyan-300">collect_chat_response</code> 把消息送入 agent：
          </p>
          <CodeBlock code={`from app.services.agent.chat_runtime import collect_chat_response

async def handle_discord_message(message: str, channel_id: str, user_id: str):
    result = await collect_chat_response(
        session=db_session,
        item_id=item_id,
        current_user=owner,
        message=message,
        robot_id=str(bot_id),           # 你的 bot ID
        robot_sender_key=f"discord:{channel_id}:{user_id}",
        robot_reply_target=DiscordReplyTarget(
            target_type="group",
            target_id=channel_id,
            metadata={"sender_name": username, "sender_id": user_id},
        ),
        robot_conversation_key=f"group:{channel_id}",
        reply_ticket_id="",
        return_result=True,
    )
    # result.content = agent 的回复文本`} />
        </CardContent>
      </Card>

      <Card className="border-zinc-800 bg-zinc-900/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-zinc-100">
            <MessageSquare className="size-5 text-violet-400" />
            4. 监控 Item 输出
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-zinc-400">
            实现 <code className="rounded bg-zinc-800 px-1 text-cyan-300">on_terminal_output</code> 和 <code className="rounded bg-zinc-800 px-1 text-cyan-300">on_item_event</code> 即可拿到 item 的终端输出和生命周期事件：
          </p>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
              <p className="text-xs font-medium text-zinc-300">on_terminal_output</p>
              <p className="mt-1 text-xs text-zinc-500">每条终端输出都触发（filtered/raw source）</p>
            </div>
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
              <p className="text-xs font-medium text-zinc-300">on_item_event</p>
              <p className="mt-1 text-xs text-zinc-500">item_started / item_stopped / item_error</p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="border-zinc-800 bg-zinc-900/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-zinc-100">
            <Code2 className="size-5 text-cyan-400" />
            5. 完整目录结构
          </CardTitle>
        </CardHeader>
        <CardContent>
          <CodeBlock code={`app/plugins/discord/
├── __init__.py
├── plugin.py              # get_backend_plugin()
├── config.py              # Settings
├── bot.py                 # Discord bot client
├── agent/
│   ├── __init__.py
│   └── integration.py     # DiscordIntegration(AgentIntegration)
├── mcp/
│   ├── __init__.py
│   └── server.py          # DiscordMCPServer (send/sleep 工具)
├── contracts.py           # DiscordReplyTarget
├── prompts.py             # Discord 专属 prompt 文本
└── api.py                 # Discord 管理 API"} />
        </CardContent>
      </Card>

      <div className="rounded-lg border border-cyan-900/50 bg-cyan-950/20 p-4">
        <p className="text-sm text-cyan-300">
          <strong>卸载效果</strong>：插件禁用后，所有 prompt 自动消失（source_route/ticket_prompt 返回空），
          delivery 自动 fallback 到 web（deliver_ticket 返回 False），
          context 清理（clear_chat_context），
          core 完全无感知。
        </p>
      </div>
    </div>
  )
}
