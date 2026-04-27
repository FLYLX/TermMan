import { Appearance } from "@/components/Common/Appearance"
import { ArchitectureDiagram } from "@/components/Common/ArchitectureDiagram"
import { Logo } from "@/components/Common/Logo"
import { useI18n } from "@/components/locale-provider"

interface AuthLayoutProps {
  children: React.ReactNode
}

export function AuthLayout({ children }: AuthLayoutProps) {
  const { locale } = useI18n()

  const copy =
    locale === "zh"
      ? {
          tagline: "终端智能体编排平台",
          description: "TermMan 是一个终端智能体编排平台，通过 Daemon 托管子进程，Agent 消费终端流，实现智能化的终端交互与决策闭环。",
          features: ["实时终端流监控与过滤", "LLM 驱动的智能决策", "QQ 机器人消息路由", "向量记忆与知识检索"],
          footer: "daemon → stream → bridge → agent",
        }
      : {
          tagline: "Terminal Agent Orchestration",
          description: "TermMan is a terminal agent orchestration platform. Daemon hosts subprocesses, Agent consumes terminal streams, enabling intelligent terminal interaction and decision loops.",
          features: ["Real-time stream monitoring & filtering", "LLM-powered intelligent decisions", "QQ bot message routing", "Vector memory & knowledge retrieval"],
          footer: "daemon → stream → bridge → agent",
        }

  return (
    <div className="relative min-h-svh overflow-hidden bg-[#f4efe6] text-foreground dark:bg-[#091014]">
      <div className="pointer-events-none absolute inset-0 opacity-60 [background-image:linear-gradient(to_right,rgba(15,23,42,0.035)_1px,transparent_1px),linear-gradient(to_bottom,rgba(15,23,42,0.035)_1px,transparent_1px)] [background-size:36px_36px] dark:opacity-25 dark:[background-image:linear-gradient(to_right,rgba(255,255,255,0.045)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.045)_1px,transparent_1px)]" />
      <div className="pointer-events-none absolute -left-20 top-[-7rem] size-[26rem] rounded-full bg-[#d9b56a]/25 blur-3xl" />
      <div className="pointer-events-none absolute bottom-[-10rem] right-[-5rem] size-[32rem] rounded-full bg-emerald-500/18 blur-3xl" />

      <div className="grid min-h-svh lg:grid-cols-[1.15fr_0.85fr]">
        <div className="relative hidden overflow-hidden border-r border-white/10 lg:flex">
          <div className="absolute inset-0 bg-[linear-gradient(145deg,rgba(12,18,20,0.96),rgba(8,12,14,0.94))]" />

          <div className="relative z-10 flex flex-1 flex-col p-6 xl:p-8">
            <div className="flex items-center justify-between">
              <Logo variant="full" asLink={false} />
              <span className="rounded-full border border-white/10 bg-white/[0.045] px-3 py-1 font-mono text-[10px] uppercase tracking-[0.34em] text-amber-200">
                {copy.tagline}
              </span>
            </div>

            <div className="mt-4 flex-1 overflow-hidden">
              <ArchitectureDiagram />
            </div>

            <div className="mt-4 flex flex-col gap-3">
              <p className="max-w-md text-sm leading-relaxed text-slate-400">
                {copy.description}
              </p>
              <div className="flex flex-wrap gap-2">
                {copy.features.map((feature, i) => (
                  <span
                    key={i}
                    className="rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 font-mono text-[10px] text-slate-500"
                  >
                    {feature}
                  </span>
                ))}
              </div>
              <span className="mt-1 font-mono text-[10px] uppercase tracking-[0.34em] text-slate-600">
                {copy.footer}
              </span>
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
              </div>

              {children}

              <div className="mt-8 border-t border-black/10 pt-5 text-center font-mono text-[10px] uppercase tracking-[0.34em] text-muted-foreground dark:border-white/10">
                {copy.tagline}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
