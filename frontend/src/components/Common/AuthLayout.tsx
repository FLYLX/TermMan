import {
  ArrowRight,
  Bot,
  type LucideIcon,
  Server,
  Shield,
  Terminal,
} from "lucide-react"

import { Appearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import { useI18n } from "@/components/locale-provider"
import { Badge } from "@/components/ui/badge"

interface AuthLayoutProps {
  children: React.ReactNode
}

function ArchitectureStage({
  step,
  title,
  description,
  detail,
  icon: Icon,
  accentClassName,
}: {
  step: string
  title: string
  description: string
  detail: string
  icon: LucideIcon
  accentClassName: string
}) {
  return (
    <div className="rounded-[26px] border border-white/10 bg-white/[0.035] p-4 shadow-[0_18px_50px_-36px_rgba(0,0,0,0.9)]">
      <div className="flex items-start gap-4">
        <div
          className={`flex size-11 shrink-0 items-center justify-center rounded-2xl border ${accentClassName}`}
        >
          <Icon className="size-5" />
        </div>
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] uppercase tracking-[0.34em] text-slate-400">
              {step}
            </span>
            <div className="h-px flex-1 bg-white/10" />
          </div>
          <h3 className="text-base font-semibold tracking-tight text-white">
            {title}
          </h3>
          <p className="text-sm leading-6 text-slate-300">{description}</p>
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-slate-400">
            {detail}
          </p>
        </div>
      </div>
    </div>
  )
}

export function AuthLayout({ children }: AuthLayoutProps) {
  const { locale } = useI18n()

  const copy =
    locale === "zh"
      ? {
          authBadge: "Daemon 子终端接入原理",
          heroTitle: "Agent 接入 daemon 子终端，本质上是消费 daemon 广播的子进程流。",
          heroDescription:
            "链路是：daemon 持有 item 子进程，子进程 stdout/stderr 被广播；backend 先走 subscription_center.publish_stream，再交给 AgentInputBridge 做 handler 解析和输入过滤，最后由 stream_manager.process_stream 把终端反馈送进 agent/xagent 会话。",
          features: [
            "subprocess stdout/stderr",
            "subscription_center + bridge",
            "stream_manager + agent_session",
          ],
          architectureTitle: "实际接入链路",
          architectureStatus: "login 仅展示原理",
          stages: [
            {
              step: "01 / Daemon",
              title: "daemon 持有 item 的原生子终端进程",
              description:
                "每个 item 在 daemon 侧以子进程存在，stdout/stderr 是源头，agent 并不直接越过 daemon 去接管这个进程。",
              detail: "item subprocess -> stdout/stderr",
              icon: Terminal,
              accentClassName:
                "border-amber-400/30 bg-amber-400/10 text-amber-200",
            },
            {
              step: "02 / Publish",
              title: "backend 先接收并发布终端流",
              description:
                "daemon 广播出的输出先进入 backend 的 shared stream timeline。subscription_center.publish_stream 会先把流交给事件总线和普通订阅者。",
              detail: "publish_stream -> terminal_stream_pipeline",
              icon: Server,
              accentClassName:
                "border-cyan-400/30 bg-cyan-400/10 text-cyan-200",
            },
            {
              step: "03 / Bridge",
              title: "AgentInputBridge 解析 handler 并套输入过滤",
              description:
                "bridge 会拼接 raw_output，按 item 绑定关系找到 handler，必要时应用 input_filter，然后把 filtered_output 继续送给 agent 层。",
              detail: "handle_stream -> filter -> handler resolve",
              icon: Shield,
              accentClassName:
                "border-fuchsia-400/30 bg-fuchsia-400/10 text-fuchsia-200",
            },
            {
              step: "04 / Session",
              title: "stream_manager 把终端反馈送进 agent/xagent",
              description:
                "stream_manager.process_stream 会做批处理和等待窗口控制，再把终端输出推进 agent_session_manager，后续才进入 agent/xagent 的会话决策。",
              detail: "process_stream -> agent_session_manager",
              icon: Bot,
              accentClassName:
                "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
            },
          ],
          runtimeMapTitle: "关键代码路径",
          runtimeMap: [
            {
              label: "Item Subprocess",
              value: "daemon 子进程产出 stdout / stderr",
              icon: Terminal,
            },
            {
              label: "publish_stream",
              value: "subscription center 先发到共享流",
              icon: Server,
            },
            {
              label: "AgentInputBridge",
              value: "解析 handler 并应用 input filter",
              icon: Shield,
            },
            {
              label: "process_stream",
              value: "批量送入 agent / xagent session",
              icon: Bot,
            },
          ],
          guardrailsTitle: "关键边界",
          guardrails: [
            "Agent 不直接接管 daemon 子终端，而是消费 daemon 广播的输出流。",
            "输入过滤发生在 AgentInputBridge 阶段，先于 agent session 处理。",
            "登录页这里只展示原理，不会实际触发这条 daemon -> agent -> xagent 链路。",
          ],
          mobileBadge: "接入原理",
          mobileTitle: "这里展示 agent 接入 daemon 子终端的真实链路",
          mobileDescription:
            "daemon 持有子进程，backend 负责发布和桥接终端流，stream_manager 再把反馈送进 agent/xagent。登录页本身不启动这条链路。",
          footerCaption: "daemon -> stream -> bridge -> agent",
        }
      : {
          authBadge: "Daemon Subterminal Integration",
          heroTitle:
            "Agent reaches daemon subterminals by consuming daemon-broadcast subprocess streams.",
          heroDescription:
            "The actual chain is: daemon owns the item subprocess and broadcasts stdout/stderr; backend runs subscription_center.publish_stream, then AgentInputBridge resolves the handler and applies input filtering, and finally stream_manager.process_stream feeds terminal feedback into the agent/xagent session.",
          features: [
            "subprocess stdout/stderr",
            "subscription_center + bridge",
            "stream_manager + agent_session",
          ],
          architectureTitle: "Actual Integration Flow",
          architectureStatus: "login shows the flow only",
          stages: [
            {
              step: "01 / Daemon",
              title: "Daemon owns the native item subprocess",
              description:
                "Each item lives as a daemon-side subprocess. stdout/stderr is the source stream, and the agent does not bypass the daemon to take over that process directly.",
              detail: "item subprocess -> stdout/stderr",
              icon: Terminal,
              accentClassName:
                "border-amber-400/30 bg-amber-400/10 text-amber-200",
            },
            {
              step: "02 / Publish",
              title: "Backend receives and publishes terminal stream first",
              description:
                "Daemon output enters the shared backend stream timeline first. subscription_center.publish_stream sends it through the event bus and normal subscribers.",
              detail: "publish_stream -> terminal_stream_pipeline",
              icon: Server,
              accentClassName:
                "border-cyan-400/30 bg-cyan-400/10 text-cyan-200",
            },
            {
              step: "03 / Bridge",
              title: "AgentInputBridge resolves handler and applies input filter",
              description:
                "The bridge builds raw_output, resolves the bound handler for the item, applies input_filter when enabled, and forwards filtered_output into the agent layer.",
              detail: "handle_stream -> filter -> handler resolve",
              icon: Shield,
              accentClassName:
                "border-fuchsia-400/30 bg-fuchsia-400/10 text-fuchsia-200",
            },
            {
              step: "04 / Session",
              title: "stream_manager feeds terminal feedback into agent/xagent",
              description:
                "stream_manager.process_stream batches terminal feedback and manages wait windows before it reaches agent_session_manager and the later agent/xagent decision loop.",
              detail: "process_stream -> agent_session_manager",
              icon: Bot,
              accentClassName:
                "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
            },
          ],
          runtimeMapTitle: "Key Code Paths",
          runtimeMap: [
            {
              label: "Item Subprocess",
              value: "daemon child process emits stdout / stderr",
              icon: Terminal,
            },
            {
              label: "publish_stream",
              value: "subscription center sends it into shared stream flow",
              icon: Server,
            },
            {
              label: "AgentInputBridge",
              value: "resolves handler and applies input filter",
              icon: Shield,
            },
            {
              label: "process_stream",
              value: "batches and feeds agent / xagent session",
              icon: Bot,
            },
          ],
          guardrailsTitle: "Critical Boundaries",
          guardrails: [
            "The agent does not directly seize the daemon subterminal. It consumes daemon-broadcast output streams.",
            "Input filtering happens inside AgentInputBridge before agent session processing.",
            "This login page explains the flow only and does not trigger the daemon -> agent -> xagent path.",
          ],
          mobileBadge: "Flow Principle",
          mobileTitle: "This page shows the real daemon-to-agent integration flow",
          mobileDescription:
            "Daemon owns the subprocess, backend publishes and bridges the stream, and stream_manager feeds feedback into agent/xagent. The login page itself does not trigger this path.",
          footerCaption: "daemon -> stream -> bridge -> agent",
        }

  return (
    <div className="relative min-h-svh overflow-hidden bg-[#f4efe6] text-foreground dark:bg-[#091014]">
      <div className="pointer-events-none absolute inset-0 opacity-60 [background-image:linear-gradient(to_right,rgba(15,23,42,0.035)_1px,transparent_1px),linear-gradient(to_bottom,rgba(15,23,42,0.035)_1px,transparent_1px)] [background-size:36px_36px] dark:opacity-25 dark:[background-image:linear-gradient(to_right,rgba(255,255,255,0.045)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.045)_1px,transparent_1px)]" />
      <div className="pointer-events-none absolute -left-20 top-[-7rem] size-[26rem] rounded-full bg-[#d9b56a]/25 blur-3xl" />
      <div className="pointer-events-none absolute bottom-[-10rem] right-[-5rem] size-[32rem] rounded-full bg-emerald-500/18 blur-3xl" />

      <div className="grid min-h-svh lg:grid-cols-[1.14fr_0.86fr]">
        <div className="relative hidden overflow-hidden border-r border-white/10 lg:flex">
          <div className="absolute inset-0 bg-[linear-gradient(145deg,rgba(12,18,20,0.96),rgba(8,12,14,0.94))]" />
          <div className="relative z-10 flex flex-1 flex-col px-8 py-10 xl:px-12">
            <Logo variant="full" asLink={false} />

            <div className="mt-8 max-w-2xl space-y-5">
              <span className="inline-flex rounded-full border border-white/10 bg-white/[0.045] px-3 py-1 font-mono text-[10px] uppercase tracking-[0.34em] text-amber-200">
                {copy.authBadge}
              </span>

              <div className="space-y-3">
                <h1 className="max-w-xl text-4xl font-semibold tracking-tight text-white xl:text-[2.85rem] xl:leading-[1.05]">
                  {copy.heroTitle}
                </h1>
                <p className="max-w-2xl text-sm leading-7 text-slate-300 xl:text-[15px]">
                  {copy.heroDescription}
                </p>
              </div>

              <div className="grid gap-2 sm:grid-cols-3">
                {copy.features.map((label) => (
                  <div
                    key={label}
                    className="rounded-2xl border border-white/10 bg-white/[0.04] px-3 py-2 shadow-sm"
                  >
                    <p className="font-mono text-[10px] uppercase tracking-[0.3em] text-slate-300">
                      {label}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-8 grid gap-4">
              <div className="rounded-[30px] border border-white/10 bg-black/30 p-4 shadow-[0_28px_100px_-48px_rgba(0,0,0,0.95)] backdrop-blur-xl xl:p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="font-mono text-[10px] uppercase tracking-[0.34em] text-slate-400">
                      {copy.architectureTitle}
                    </p>
                    <h2 className="mt-2 text-lg font-semibold tracking-tight text-white">
                      {copy.heroTitle}
                    </h2>
                  </div>
                  <Badge className="border-emerald-400/30 bg-emerald-400/10 text-emerald-200">
                    {copy.architectureStatus}
                  </Badge>
                </div>

                <div className="mt-4 grid gap-3">
                  {copy.stages.map((stage) => (
                    <ArchitectureStage key={stage.step} {...stage} />
                  ))}
                </div>
              </div>

              <div className="grid gap-4 xl:grid-cols-[1.3fr_0.7fr]">
                <div className="rounded-[28px] border border-white/10 bg-white/[0.035] p-4 shadow-[0_18px_70px_-44px_rgba(0,0,0,0.9)]">
                  <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.32em] text-slate-400">
                    <Server className="size-3.5" />
                    <span>{copy.runtimeMapTitle}</span>
                  </div>
                  <div className="mt-4 grid gap-3 sm:grid-cols-3">
                    {copy.runtimeMap.map((node) => {
                      const Icon = node.icon

                      return (
                        <div
                          key={node.label}
                          className="rounded-2xl border border-white/10 bg-black/20 px-3 py-3"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex size-9 items-center justify-center rounded-xl border border-white/10 bg-white/[0.05] text-white">
                              <Icon className="size-4" />
                            </div>
                            <ArrowRight className="size-4 text-slate-500" />
                          </div>
                          <p className="mt-3 text-sm font-medium text-white">
                            {node.label}
                          </p>
                          <p className="mt-1 text-xs leading-5 text-slate-400">
                            {node.value}
                          </p>
                        </div>
                      )
                    })}
                  </div>
                </div>

                <div className="rounded-[28px] border border-white/10 bg-white/[0.035] p-4 shadow-[0_18px_70px_-44px_rgba(0,0,0,0.9)]">
                  <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.32em] text-slate-400">
                    <Shield className="size-3.5" />
                    <span>{copy.guardrailsTitle}</span>
                  </div>
                  <div className="mt-3 grid gap-2">
                    {copy.guardrails.map((rule) => (
                      <div
                        key={rule}
                        className="rounded-2xl border border-white/10 bg-black/20 px-3 py-2.5"
                      >
                        <div className="flex items-start gap-2">
                          <Shield className="mt-0.5 size-3.5 shrink-0 text-emerald-300" />
                          <p className="text-sm leading-6 text-slate-200">
                            {rule}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="relative flex items-center justify-center p-6 md:p-10">
          <div className="absolute right-6 top-6 z-10">
            <Appearance />
          </div>

          <div className="relative z-10 w-full max-w-md">
            <div className="rounded-[32px] border border-black/10 bg-white/[0.78] p-6 shadow-[0_32px_120px_-48px_rgba(37,31,20,0.42)] backdrop-blur-2xl dark:border-white/10 dark:bg-black/[0.38] dark:shadow-[0_32px_120px_-48px_rgba(0,0,0,0.95)] md:p-8">
              <div className="mb-6 flex items-center justify-between lg:hidden">
                <Logo variant="full" asLink={false} />
                <span className="rounded-full border border-primary/20 bg-primary/10 px-3 py-1 font-mono text-[10px] uppercase tracking-[0.34em] text-primary">
                  {copy.mobileBadge}
                </span>
              </div>

              <div className="mb-6 rounded-[24px] border border-border/60 bg-muted/25 p-4 lg:hidden">
                <p className="font-mono text-[10px] uppercase tracking-[0.34em] text-primary/75">
                  {copy.mobileTitle}
                </p>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  {copy.mobileDescription}
                </p>
              </div>

              {children}

              <div className="mt-8 border-t border-black/10 pt-5 text-center font-mono text-[10px] uppercase tracking-[0.34em] text-muted-foreground dark:border-white/10">
                {copy.footerCaption}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
