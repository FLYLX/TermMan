import { Logo } from "@/components/Common/Logo"
import { useI18n } from "@/components/locale-provider"

interface AuthLayoutProps {
  children: React.ReactNode
}

export function AuthLayout({ children }: AuthLayoutProps) {
  const { locale } = useI18n()

  const tagline =
    locale === "zh" ? "终端智能体编排平台" : "Terminal Agent Orchestration"

  return (
    <div className="relative flex min-h-svh items-center justify-center p-6 font-mono text-[#1f1f1f] [background:linear-gradient(135deg,#f5f1e8_0%,#f2f4ef_55%,#e9efec_100%)]">
      <div className="pointer-events-none absolute inset-0 opacity-70 [background-image:linear-gradient(to_right,rgba(58,58,58,0.06)_1px,transparent_1px),linear-gradient(to_bottom,rgba(58,58,58,0.06)_1px,transparent_1px)] [background-size:28px_28px]" />
      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
        <div className="absolute -left-24 top-[-6rem] size-96 rounded-full bg-[#d9b56a]/30 blur-3xl [animation:blob-float_14s_ease-in-out_infinite]" />
        <div className="absolute bottom-[-8rem] right-[-4rem] size-[28rem] rounded-full bg-emerald-500/20 blur-3xl [animation:blob-float_18s_ease-in-out_infinite_reverse]" />
        <div className="absolute left-[38%] top-[30%] size-72 rounded-full bg-sky-400/10 blur-3xl [animation:blob-float_22s_ease-in-out_infinite]" />
      </div>

      <div
        className="relative z-10 w-full max-w-sm border-2 border-[#3a3a3a] bg-white/75 p-8 shadow-[4px_5px_0_rgba(0,0,0,0.14)] backdrop-blur-xl [animation:card-in_.35s_ease-out]"
        style={{
          borderRadius: "16px 205px 16px 205px / 205px 16px 205px 16px",
        }}
      >
        <div className="mb-8 flex flex-col items-center gap-2">
          <Logo variant="full" asLink={false} />
          <span className="text-[10px] uppercase tracking-[0.34em] text-[#565654]">
            {tagline}
          </span>
        </div>

        {children}
      </div>
    </div>
  )
}
