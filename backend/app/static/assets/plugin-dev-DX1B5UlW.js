import{j as e,ar as x,au as m,aq as p,av as u,ac as g,t as a,aw as h,ax as f,ay as y,az as b,aA as j,aB as k,aC as v,aD as N}from"./index-CKQAumsJ.js";function r({code:s}){const[i,n]=a.useState(!1);return e.jsxs("div",{className:"relative",children:[e.jsx("button",{onClick:()=>{navigator.clipboard.writeText(s),n(!0),setTimeout(()=>n(!1),2e3)},className:"absolute right-2 top-2 z-10 rounded-md bg-stone-200 p-1.5 text-stone-500 hover:text-stone-800",children:i?e.jsx(v,{className:"size-4"}):e.jsx(N,{className:"size-4"})}),e.jsx("pre",{className:"overflow-x-auto rounded-lg border border-stone-300 bg-[#fafaf8] p-4 text-xs leading-relaxed text-stone-700",children:e.jsx("code",{children:s})})]})}function t({icon:s,iconClass:i,title:n,defaultOpen:c=!1,children:d}){const[o,l]=a.useState(c);return e.jsxs(h,{className:"gap-0 border-stone-300 bg-white py-3",children:[e.jsx(f,{className:"cursor-pointer select-none px-4",onClick:()=>l(_=>!_),children:e.jsxs(y,{className:"flex items-center gap-2 text-sm text-stone-800",children:[e.jsx(s,{className:`size-4 ${i}`}),n,o?e.jsx(b,{className:"ml-auto size-4 text-stone-400"}):e.jsx(j,{className:"ml-auto size-4 text-stone-400"})]})}),o?e.jsx(k,{className:"space-y-3 px-4 pt-3",children:d}):null]})}function C(){return e.jsxs("div",{className:"mx-auto max-w-4xl space-y-3 p-4",children:[e.jsxs("div",{className:"space-y-1",children:[e.jsx("h1",{className:"text-xl font-bold text-stone-800",children:"第三方插件开发指南"}),e.jsx("p",{className:"text-xs text-stone-500",children:"TermPaws 插件接口是标准化的。实现以下接口，即可接入任意聊天平台（Discord / Telegram / Kook 等）。点击章节展开详情。"})]}),e.jsxs(t,{icon:x,iconClass:"text-cyan-600",title:"1. 插件注册",children:[e.jsxs("p",{className:"text-sm text-stone-500",children:["在 ",e.jsx("code",{className:"rounded bg-stone-200 px-1 text-cyan-700",children:"app/plugins/your_platform/plugin.py"})," 创建插件入口："]}),e.jsx(r,{code:`from app.services.plugins.contracts import BackendPlugin, PluginEntrypoints

def get_backend_plugin() -> BackendPlugin:
    return BackendPlugin(
        plugin_id="TermPaws.discord",
        name="Discord",
        version="1.0.0",
        description="Discord bot integration for TermPaws",
        builtin=False,
        category="messaging",
        enabled=lambda: settings.DISCORD_PLUGIN_ENABLED,
        entrypoints=PluginEntrypoints(
            register_agent_integration=register_integration,
            include_router=include_router,
            startup=startup,
            shutdown=shutdown,
        ),
    )`})]}),e.jsxs(t,{icon:m,iconClass:"text-amber-600",title:"2. Agent Integration（核心接口）",children:[e.jsxs("p",{className:"text-sm text-stone-500",children:["所有方法都是",e.jsx("strong",{children:"可选"}),"的，不实现的方法使用 NoopAgentIntegration 默认值。"]}),e.jsx(r,{code:`class DiscordIntegration:
    name = "discord"

    # ── Prompt 层（卸载时自动消失）──
    def build_source_route(self, agent, *, source) -> str:
        """返回当前来源的路由提示文本（如 'Discord channel #xxx'）"""
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
        """返回 ticket 的 routing 指令文本"""
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
        """过滤重复的 skill（integration 已自带 messaging 规则时）"""
        if not self._is_discord_context(agent):
            return skills
        return [s for s in skills if s.skill_id not in DISCORD_COMPAT_SKILL_IDS]

    # ── Delivery 层（卸载时 fallback web）──
    def deliver_ticket(self, ticket, text) -> bool:
        """把回复发送到 Discord（成功返回 True）"""
        if ticket.source_type != "discord":
            return False
        channel_id = ticket.reply_target.get("channel_id")
        await discord_bot.send_message(channel_id, text)
        return True

    def conversation_memory_append(self, ticket, text) -> None:
        """记录会话记忆（可选）"""
        pass

    # ── Context 层 ──
    def setup_chat_context(self, agent, context) -> bool:
        """注册 Discord context 到 agent（robot_id 等等价物）"""
        agent_context = agent._context
        agent_context.discord_guild_id = context["guild_id"]
        agent_context.discord_channel_id = context["channel_id"]
        return True

    def clear_chat_context(self, agent, context) -> None:
        """清理 Discord context"""
        agent_context = agent._context
        agent_context.discord_guild_id = ""
        agent_context.discord_channel_id = ""

    def inject_tool_args(self, agent, *, server_name, tool_name, args) -> None:
        """注入 context token 到工具参数（如 _discord_context_token）"""
        if tool_name in ("send_message", "sleep_conversation"):
            ctx = agent._context
            args["_discord_context_token"] = ctx.discord_context_token

    # ── Memory 层 ──
    def memory_scope_rank(self, agent, memory) -> int:
        """Discord 记忆 scope 排序（同 channel 优先）"""
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
        """终端有输出时触发（可转发到 Discord）"""
        if source == "filtered":
            return
        channel_id = self._get_notification_channel(item_id)
        if channel_id:
            asyncio.create_task(
                discord_bot.send_message(channel_id, f"[Terminal] {content[:200]}")
            )

    def on_item_event(self, item_id, event, payload) -> None:
        """Item 生命周期事件（start/stop/error）"""
        if event == "item_started":
            pass  # 通知 Discord: 服务器启动了
        elif event == "item_stopped":
            pass  # 通知 Discord: 服务器停了

    # ── Tool/Skill 层 ──
    def builtin_skill_definitions(self) -> list:
        """提供 Discord 专属 skill"""
        return [discord_messaging_skill]

    def builtin_mcp_server_factories(self) -> dict:
        """提供 Discord MCP server（send_message/sleep 等工具）"""
        return {"discord": lambda: DiscordMCPServer()}`})]}),e.jsxs(t,{icon:p,iconClass:"text-emerald-600",title:"3. 接收消息（Item 输入）",children:[e.jsxs("p",{className:"text-sm text-stone-500",children:["通过 ",e.jsx("code",{className:"rounded bg-stone-200 px-1 text-cyan-700",children:"collect_chat_response"})," 把消息送入 agent："]}),e.jsx(r,{code:`from app.services.agent.chat_runtime import collect_chat_response

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
    # result.content = agent 的回复文本`})]}),e.jsxs(t,{icon:u,iconClass:"text-violet-600",title:"4. 监控 Item 输出",children:[e.jsxs("p",{className:"text-sm text-stone-500",children:["实现 ",e.jsx("code",{className:"rounded bg-stone-200 px-1 text-cyan-700",children:"on_terminal_output"})," 和 ",e.jsx("code",{className:"rounded bg-stone-200 px-1 text-cyan-700",children:"on_item_event"})," 即可拿到 item 的终端输出和生命周期事件："]}),e.jsxs("div",{className:"grid grid-cols-2 gap-3",children:[e.jsxs("div",{className:"rounded-lg border border-stone-300 bg-stone-50 p-3",children:[e.jsx("p",{className:"text-xs font-medium text-stone-700",children:"on_terminal_output"}),e.jsx("p",{className:"mt-1 text-xs text-stone-500",children:"每条终端输出都触发（filtered/raw source）"})]}),e.jsxs("div",{className:"rounded-lg border border-stone-300 bg-stone-50 p-3",children:[e.jsx("p",{className:"text-xs font-medium text-stone-700",children:"on_item_event"}),e.jsx("p",{className:"mt-1 text-xs text-stone-500",children:"item_started / item_stopped / item_error"})]})]})]}),e.jsx(t,{icon:g,iconClass:"text-cyan-600",title:"5. 完整目录结构",children:e.jsx(r,{code:`app/plugins/discord/
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
└── api.py                 # Discord 管理 API`})}),e.jsx("div",{className:"rounded-lg border border-cyan-200 bg-cyan-50 p-4",children:e.jsxs("p",{className:"text-sm text-cyan-800",children:[e.jsx("strong",{children:"卸载效果"}),"：插件禁用后，所有 prompt 自动消失（source_route/ticket_prompt 返回空）， delivery 自动 fallback 到 web（deliver_ticket 返回 False）， context 清理（clear_chat_context）， core 完全无感知。"]})})]})}export{C as component};
