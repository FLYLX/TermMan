import { Link } from "@tanstack/react-router"

import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

function LogoMark({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "flex size-10 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 shadow-lg shadow-primary/10",
        className,
      )}
    >
      <span className="font-mono text-xs font-semibold uppercase tracking-[0.24em] text-primary">
        TM
      </span>
    </div>
  )
}

function LogoWordmark({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <LogoMark />
      <div className="flex min-w-0 flex-col leading-none">
        <span className="font-mono text-[10px] uppercase tracking-[0.34em] text-primary/75">
          Terminal Ops
        </span>
        <span className="text-lg font-semibold tracking-tight text-foreground">
          TermPaws
        </span>
      </div>
    </div>
  )
}

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const content =
    variant === "responsive" ? (
      <>
        <div className="group-data-[collapsible=icon]:hidden">
          <LogoWordmark className={className} />
        </div>
        <div className="hidden group-data-[collapsible=icon]:block">
          <LogoMark className={className} />
        </div>
      </>
    ) : variant === "full" ? (
      <LogoWordmark className={className} />
    ) : (
      <LogoMark className={className} />
    )

  if (!asLink) {
    return content
  }

  return (
    <Link to="/" className="inline-flex items-center">
      {content}
    </Link>
  )
}
