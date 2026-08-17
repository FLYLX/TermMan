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
    <div className="relative flex min-h-svh items-center justify-center bg-white p-6 font-mono text-[#1f1f1f]">
      <div className="pointer-events-none absolute inset-0 opacity-50 [background-image:linear-gradient(to_right,rgba(15,23,42,0.05)_1px,transparent_1px),linear-gradient(to_bottom,rgba(15,23,42,0.05)_1px,transparent_1px)] [background-size:32px_32px]" />

      <div
        className="relative z-10 w-full max-w-sm border-2 border-[#3a3a3a] bg-white p-8 shadow-[4px_5px_0_rgba(0,0,0,0.14)]"
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
