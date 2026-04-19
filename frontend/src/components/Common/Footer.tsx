import { useI18n } from "@/components/locale-provider"

export function Footer() {
  const currentYear = new Date().getFullYear()
  const { t } = useI18n()

  return (
    <footer className="px-4 pb-6 md:px-6">
      <div className="rounded-[20px] border bg-card px-4 py-3 shadow-sm">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex flex-wrap items-center gap-3">
            <span className="inline-flex rounded-full border border-primary/20 bg-primary/10 px-3 py-1 font-mono text-[10px] uppercase tracking-[0.34em] text-primary">
              TermMan
            </span>
            <p className="text-sm text-muted-foreground">
              {t("brand.footerDescription")}
            </p>
          </div>
          <p className="font-mono text-[10px] uppercase tracking-[0.34em] text-muted-foreground">
            {t("brand.footerCaption", { year: currentYear })}
          </p>
        </div>
      </div>
    </footer>
  )
}
