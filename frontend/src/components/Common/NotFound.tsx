import { Link } from "@tanstack/react-router"

import { Logo } from "@/components/Common/Logo"
import { useI18n } from "@/components/locale-provider"
import { Button } from "@/components/ui/button"

const NotFound = () => {
  const { t } = useI18n()

  return (
    <div
      className="relative flex min-h-screen items-center justify-center overflow-hidden p-6"
      data-testid="not-found"
    >
      <div className="pointer-events-none absolute -left-24 top-0 size-72 rounded-full bg-primary/18 blur-3xl" />
      <div className="pointer-events-none absolute bottom-0 right-0 size-80 rounded-full bg-blue-500/10 blur-3xl" />
      <div className="relative z-10 w-full max-w-2xl rounded-[32px] border border-white/10 bg-black/35 p-8 shadow-[0_32px_120px_-48px_rgba(0,0,0,0.95)] backdrop-blur-2xl md:p-12">
        <Logo variant="full" asLink={false} />
        <div className="mt-8">
          <span className="inline-flex rounded-full border border-primary/20 bg-primary/10 px-3 py-1 font-mono text-[10px] uppercase tracking-[0.34em] text-primary">
            Term.PathNotFound
          </span>
          <div className="mt-6 font-mono text-6xl font-semibold tracking-tight text-primary md:text-8xl">
            404
          </div>
          <h1 className="mt-4 text-3xl font-semibold tracking-tight md:text-4xl">
            {t("brand.notFoundTitle")}
          </h1>
          <p className="mt-4 max-w-xl text-base leading-7 text-muted-foreground">
            {t("brand.notFoundDescription")}
          </p>
          <Link to="/">
            <Button className="mt-8 rounded-full px-6">
              {t("brand.notFoundAction")}
            </Button>
          </Link>
        </div>
      </div>
    </div>
  )
}

export default NotFound
