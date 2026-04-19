import { createContext, useContext, useEffect, useMemo, useState } from "react"
import {
  getLocaleTag,
  type Locale,
  type MessageValues,
  type TranslationKey,
  translate,
} from "@/lib/i18n"

type LocaleProviderProps = {
  children: React.ReactNode
  defaultLocale?: Locale
  storageKey?: string
}

type LocaleProviderState = {
  locale: Locale
  localeTag: string
  setLocale: (locale: Locale) => void
  t: (key: TranslationKey, values?: MessageValues) => string
}

const initialState: LocaleProviderState = {
  locale: "en",
  localeTag: "en-US",
  setLocale: () => null,
  t: (key) => key,
}

const LocaleProviderContext = createContext<LocaleProviderState>(initialState)

function resolveInitialLocale(
  storageKey: string,
  defaultLocale: Locale,
): Locale {
  const stored = localStorage.getItem(storageKey)
  if (stored === "zh" || stored === "en") {
    return stored
  }

  const browserLanguage = navigator.language.toLowerCase()
  if (browserLanguage.startsWith("zh")) {
    return "zh"
  }

  return defaultLocale
}

export function LocaleProvider({
  children,
  defaultLocale = "en",
  storageKey = "termman-locale",
}: LocaleProviderProps) {
  const [locale, setLocaleState] = useState<Locale>(() =>
    resolveInitialLocale(storageKey, defaultLocale),
  )

  useEffect(() => {
    localStorage.setItem(storageKey, locale)
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en"
  }, [locale, storageKey])

  const value = useMemo<LocaleProviderState>(
    () => ({
      locale,
      localeTag: getLocaleTag(locale),
      setLocale: (nextLocale: Locale) => {
        setLocaleState(nextLocale)
      },
      t: (key, values) => translate(locale, key, values),
    }),
    [locale],
  )

  return (
    <LocaleProviderContext.Provider value={value}>
      {children}
    </LocaleProviderContext.Provider>
  )
}

export const useI18n = () => {
  const context = useContext(LocaleProviderContext)

  if (context === undefined) {
    throw new Error("useI18n must be used within a LocaleProvider")
  }

  return context
}
