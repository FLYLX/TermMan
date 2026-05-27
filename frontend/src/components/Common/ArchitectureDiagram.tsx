import { useEffect, useState } from "react"
import { useI18n } from "@/components/locale-provider"

export function ArchitectureDiagram() {
  const { locale } = useI18n()
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  const isZh = locale === "zh"

  if (!mounted) {
    return <div className="h-full" />
  }

  const labels = isZh
    ? {
        stream: "stdout/stderr",
        subscribe: "订阅分发",
        filter: "输入过滤",
        bridge: "标准化输入",
        agent: "消息处理",
        decision: "决策反馈",
        memory: "记忆存取",
        robot: "QQ消息",
        mcp: "工具调用",
        knowledge: "知识检索",
        llm: "LLM调用",
      }
    : {
        stream: "stdout/stderr",
        subscribe: "fan-out",
        filter: "filtered",
        bridge: "normalized",
        agent: "process",
        decision: "feedback",
        memory: "R/W",
        robot: "QQ msg",
        mcp: "tools",
        knowledge: "retrieve",
        llm: "LLM call",
      }

  return (
    <div className="relative h-full w-full">
      <svg
        className="h-full w-full"
        viewBox="0 0 700 400"
        preserveAspectRatio="xMidYMid meet"
      >
        <defs>
          <marker
            id="arrow"
            markerWidth="6"
            markerHeight="6"
            refX="5"
            refY="3"
            orient="auto"
          >
            <polygon points="0 0, 6 3, 0 6" fill="#64748b" />
          </marker>
          <marker
            id="arrowBlue"
            markerWidth="6"
            markerHeight="6"
            refX="5"
            refY="3"
            orient="auto"
          >
            <polygon points="0 0, 6 3, 0 6" fill="#3b82f6" />
          </marker>
          <marker
            id="arrowGreen"
            markerWidth="6"
            markerHeight="6"
            refX="5"
            refY="3"
            orient="auto"
          >
            <polygon points="0 0, 6 3, 0 6" fill="#10b981" />
          </marker>
          <marker
            id="arrowOrange"
            markerWidth="6"
            markerHeight="6"
            refX="5"
            refY="3"
            orient="auto"
          >
            <polygon points="0 0, 6 3, 0 6" fill="#f97316" />
          </marker>
          <marker
            id="arrowViolet"
            markerWidth="6"
            markerHeight="6"
            refX="5"
            refY="3"
            orient="auto"
          >
            <polygon points="0 0, 6 3, 0 6" fill="#8b5cf6" />
          </marker>
          <marker
            id="arrowPink"
            markerWidth="6"
            markerHeight="6"
            refX="5"
            refY="3"
            orient="auto"
          >
            <polygon points="0 0, 6 3, 0 6" fill="#ec4899" />
          </marker>
        </defs>

        <line
          x1="100"
          y1="55"
          x2="100"
          y2="85"
          stroke="#475569"
          strokeWidth="2"
          markerEnd="url(#arrow)"
        />
        <text
          x="115"
          y="75"
          className="fill-slate-500"
          style={{ fontSize: "10px" }}
        >
          {labels.stream}
        </text>

        <line
          x1="100"
          y1="135"
          x2="100"
          y2="165"
          stroke="#475569"
          strokeWidth="2"
          markerEnd="url(#arrow)"
        />
        <text
          x="115"
          y="155"
          className="fill-slate-500"
          style={{ fontSize: "10px" }}
        >
          {labels.subscribe}
        </text>

        <line
          x1="100"
          y1="215"
          x2="100"
          y2="245"
          stroke="#475569"
          strokeWidth="2"
          markerEnd="url(#arrow)"
        />
        <text
          x="115"
          y="235"
          className="fill-slate-500"
          style={{ fontSize: "10px" }}
        >
          {labels.bridge}
        </text>

        <line
          x1="180"
          y1="275"
          x2="280"
          y2="275"
          stroke="#475569"
          strokeWidth="2"
          markerEnd="url(#arrow)"
        />
        <text
          x="205"
          y="268"
          className="fill-slate-500"
          style={{ fontSize: "10px" }}
        >
          {labels.filter}
        </text>

        <line
          x1="420"
          y1="275"
          x2="520"
          y2="275"
          stroke="#475569"
          strokeWidth="2"
          markerEnd="url(#arrow)"
        />
        <text
          x="445"
          y="268"
          className="fill-slate-500"
          style={{ fontSize: "10px" }}
        >
          {labels.agent}
        </text>

        <path
          d="M 600 245 Q 600 180 350 180 Q 100 180 100 165"
          stroke="#3b82f6"
          strokeWidth="2"
          fill="none"
          strokeDasharray="5 3"
          markerEnd="url(#arrowBlue)"
          opacity="0.7"
        />
        <text
          x="320"
          y="175"
          className="fill-blue-400"
          style={{ fontSize: "10px" }}
        >
          {labels.decision}
        </text>

        <line
          x1="350"
          y1="305"
          x2="350"
          y2="335"
          stroke="#10b981"
          strokeWidth="2"
          markerEnd="url(#arrowGreen)"
          opacity="0.8"
        />
        <text
          x="365"
          y="325"
          className="fill-emerald-400"
          style={{ fontSize: "10px" }}
        >
          {labels.memory}
        </text>

        <line
          x1="280"
          y1="365"
          x2="180"
          y2="365"
          stroke="#f97316"
          strokeWidth="2"
          markerEnd="url(#arrowOrange)"
          opacity="0.7"
        />
        <text
          x="195"
          y="358"
          className="fill-orange-400"
          style={{ fontSize: "10px" }}
        >
          {labels.robot}
        </text>

        <line
          x1="520"
          y1="305"
          x2="520"
          y2="335"
          stroke="#8b5cf6"
          strokeWidth="2"
          markerEnd="url(#arrowViolet)"
          opacity="0.7"
        />
        <text
          x="535"
          y="325"
          className="fill-violet-400"
          style={{ fontSize: "10px" }}
        >
          {labels.mcp}
        </text>

        <line
          x1="600"
          y1="305"
          x2="600"
          y2="335"
          stroke="#ec4899"
          strokeWidth="2"
          markerEnd="url(#arrowPink)"
          opacity="0.7"
        />
        <text
          x="615"
          y="325"
          className="fill-pink-400"
          style={{ fontSize: "10px" }}
        >
          {labels.knowledge}
        </text>

        <g transform="translate(40, 20)">
          <rect
            x="0"
            y="0"
            width="120"
            height="35"
            rx="8"
            className="fill-amber-950/30 stroke-amber-400/40"
            strokeWidth="1"
          />
          <text
            x="30"
            y="15"
            className="fill-amber-400 font-semibold"
            style={{ fontSize: "12px" }}
          >
            Daemon
          </text>
          <text
            x="30"
            y="28"
            className="fill-amber-400/70"
            style={{ fontSize: "9px" }}
          >
            {isZh ? "终端进程" : "Process"}
          </text>
          <circle cx="15" cy="17" r="8" className="fill-amber-400/20" />
          <text
            x="15"
            y="21"
            className="fill-amber-400"
            style={{ fontSize: "10px" }}
            textAnchor="middle"
          >
            ▶
          </text>
        </g>

        <g transform="translate(40, 85)">
          <rect
            x="0"
            y="0"
            width="120"
            height="50"
            rx="8"
            className="fill-slate-800/50 stroke-slate-400/40"
            strokeWidth="1"
          />
          <text
            x="30"
            y="20"
            className="fill-slate-300 font-semibold"
            style={{ fontSize: "12px" }}
          >
            Socket
          </text>
          <text
            x="30"
            y="35"
            className="fill-slate-400/70"
            style={{ fontSize: "9px" }}
          >
            {isZh ? "连接池" : "Conn Pool"}
          </text>
          <circle cx="15" cy="25" r="8" className="fill-slate-400/20" />
          <text
            x="15"
            y="29"
            className="fill-slate-300"
            style={{ fontSize: "10px" }}
            textAnchor="middle"
          >
            ◉
          </text>
        </g>

        <g transform="translate(40, 165)">
          <rect
            x="0"
            y="0"
            width="120"
            height="50"
            rx="8"
            className="fill-cyan-950/30 stroke-cyan-400/40"
            strokeWidth="1"
          />
          <text
            x="30"
            y="20"
            className="fill-cyan-400 font-semibold"
            style={{ fontSize: "12px" }}
          >
            Stream
          </text>
          <text
            x="30"
            y="35"
            className="fill-cyan-400/70"
            style={{ fontSize: "9px" }}
          >
            {isZh ? "订阅中心" : "Pub/Sub"}
          </text>
          <circle cx="15" cy="25" r="8" className="fill-cyan-400/20" />
          <text
            x="15"
            y="29"
            className="fill-cyan-400"
            style={{ fontSize: "10px" }}
            textAnchor="middle"
          >
            ◎
          </text>
        </g>

        <g transform="translate(40, 245)">
          <rect
            x="0"
            y="0"
            width="140"
            height="50"
            rx="8"
            className="fill-fuchsia-950/30 stroke-fuchsia-400/40"
            strokeWidth="1"
          />
          <text
            x="30"
            y="20"
            className="fill-fuchsia-400 font-semibold"
            style={{ fontSize: "12px" }}
          >
            Bridge
          </text>
          <text
            x="30"
            y="35"
            className="fill-fuchsia-400/70"
            style={{ fontSize: "9px" }}
          >
            {isZh ? "数据桥接" : "Data Bridge"}
          </text>
          <circle cx="15" cy="25" r="8" className="fill-fuchsia-400/20" />
          <text
            x="15"
            y="29"
            className="fill-fuchsia-400"
            style={{ fontSize: "10px" }}
            textAnchor="middle"
          >
            ⇄
          </text>
        </g>

        <g transform="translate(280, 245)">
          <rect
            x="0"
            y="0"
            width="140"
            height="50"
            rx="8"
            className="fill-rose-950/30 stroke-rose-400/40"
            strokeWidth="1"
          />
          <text
            x="30"
            y="20"
            className="fill-rose-400 font-semibold"
            style={{ fontSize: "12px" }}
          >
            Filter
          </text>
          <text
            x="30"
            y="35"
            className="fill-rose-400/70"
            style={{ fontSize: "9px" }}
          >
            {isZh ? "输入过滤层" : "Input Filter"}
          </text>
          <circle cx="15" cy="25" r="8" className="fill-rose-400/20" />
          <text
            x="15"
            y="29"
            className="fill-rose-400"
            style={{ fontSize: "10px" }}
            textAnchor="middle"
          >
            ▽
          </text>
        </g>

        <g transform="translate(520, 245)">
          <rect
            x="0"
            y="0"
            width="160"
            height="50"
            rx="8"
            className="fill-emerald-950/30 stroke-emerald-400/40"
            strokeWidth="1"
          />
          <text
            x="30"
            y="20"
            className="fill-emerald-400 font-semibold"
            style={{ fontSize: "12px" }}
          >
            Agent
          </text>
          <text
            x="30"
            y="35"
            className="fill-emerald-400/70"
            style={{ fontSize: "9px" }}
          >
            {isZh ? "智能体核心" : "Agent Core"}
          </text>
          <circle cx="15" cy="25" r="8" className="fill-emerald-400/20" />
          <text
            x="15"
            y="29"
            className="fill-emerald-400"
            style={{ fontSize: "10px" }}
            textAnchor="middle"
          >
            ◆
          </text>
        </g>

        <g transform="translate(280, 335)">
          <rect
            x="0"
            y="0"
            width="140"
            height="30"
            rx="6"
            className="fill-teal-950/30 stroke-teal-400/40"
            strokeWidth="1"
          />
          <text
            x="25"
            y="13"
            className="fill-teal-400 font-medium"
            style={{ fontSize: "10px" }}
          >
            Memory
          </text>
          <text
            x="25"
            y="24"
            className="fill-teal-400/70"
            style={{ fontSize: "8px" }}
          >
            {isZh ? "记忆系统" : "Memory"}
          </text>
          <circle cx="12" cy="15" r="6" className="fill-teal-400/20" />
          <text
            x="12"
            y="18"
            className="fill-teal-400"
            style={{ fontSize: "8px" }}
            textAnchor="middle"
          >
            ▣
          </text>
        </g>

        <g transform="translate(40, 335)">
          <rect
            x="0"
            y="0"
            width="140"
            height="30"
            rx="6"
            className="fill-orange-950/30 stroke-orange-400/40"
            strokeWidth="1"
          />
          <text
            x="25"
            y="13"
            className="fill-orange-400 font-medium"
            style={{ fontSize: "10px" }}
          >
            Robot
          </text>
          <text
            x="25"
            y="24"
            className="fill-orange-400/70"
            style={{ fontSize: "8px" }}
          >
            QQ {isZh ? "机器人" : "Bot"}
          </text>
          <circle cx="12" cy="15" r="6" className="fill-orange-400/20" />
          <text
            x="12"
            y="18"
            className="fill-orange-400"
            style={{ fontSize: "8px" }}
            textAnchor="middle"
          >
            Q
          </text>
        </g>

        <g transform="translate(520, 335)">
          <rect
            x="0"
            y="0"
            width="80"
            height="30"
            rx="6"
            className="fill-violet-950/30 stroke-violet-400/40"
            strokeWidth="1"
          />
          <text
            x="25"
            y="13"
            className="fill-violet-400 font-medium"
            style={{ fontSize: "10px" }}
          >
            MCP
          </text>
          <text
            x="25"
            y="24"
            className="fill-violet-400/70"
            style={{ fontSize: "8px" }}
          >
            {isZh ? "工具" : "Tools"}
          </text>
          <circle cx="12" cy="15" r="6" className="fill-violet-400/20" />
          <text
            x="12"
            y="18"
            className="fill-violet-400"
            style={{ fontSize: "8px" }}
            textAnchor="middle"
          >
            ⚙
          </text>
        </g>

        <g transform="translate(600, 335)">
          <rect
            x="0"
            y="0"
            width="80"
            height="30"
            rx="6"
            className="fill-pink-950/30 stroke-pink-400/40"
            strokeWidth="1"
          />
          <text
            x="25"
            y="13"
            className="fill-pink-400 font-medium"
            style={{ fontSize: "10px" }}
          >
            RAG
          </text>
          <text
            x="25"
            y="24"
            className="fill-pink-400/70"
            style={{ fontSize: "8px" }}
          >
            {isZh ? "知识库" : "Knowledge"}
          </text>
          <circle cx="12" cy="15" r="6" className="fill-pink-400/20" />
          <text
            x="12"
            y="18"
            className="fill-pink-400"
            style={{ fontSize: "8px" }}
            textAnchor="middle"
          >
            ◈
          </text>
        </g>

        <g transform="translate(520, 165)">
          <rect
            x="0"
            y="0"
            width="160"
            height="35"
            rx="6"
            className="fill-blue-950/30 stroke-blue-400/40"
            strokeWidth="1"
          />
          <text
            x="30"
            y="15"
            className="fill-blue-400 font-medium"
            style={{ fontSize: "11px" }}
          >
            StreamMgr
          </text>
          <text
            x="30"
            y="28"
            className="fill-blue-400/70"
            style={{ fontSize: "8px" }}
          >
            {isZh ? "流式输出" : "Stream Output"}
          </text>
          <circle cx="15" cy="17" r="7" className="fill-blue-400/20" />
          <text
            x="15"
            y="21"
            className="fill-blue-400"
            style={{ fontSize: "9px" }}
            textAnchor="middle"
          >
            ⚡
          </text>
        </g>

        <line
          x1="600"
          y1="200"
          x2="600"
          y2="245"
          stroke="#3b82f6"
          strokeWidth="2"
          markerEnd="url(#arrowBlue)"
          opacity="0.6"
        />
        <text
          x="615"
          y="225"
          className="fill-blue-400"
          style={{ fontSize: "9px" }}
        >
          {labels.llm}
        </text>
      </svg>
    </div>
  )
}
