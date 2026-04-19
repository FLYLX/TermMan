import { createFileRoute } from "@tanstack/react-router"

import { Appearance } from "@/components/Common/Appearance"
import { LanguageSwitcher } from "@/components/Common/LanguageSwitcher"
import { useI18n } from "@/components/locale-provider"
import ChangePassword from "@/components/UserSettings/ChangePassword"
import DeleteAccount from "@/components/UserSettings/DeleteAccount"
import UserInformation from "@/components/UserSettings/UserInformation"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useAuth from "@/hooks/useAuth"

function PreferencesPanel() {
  const { t } = useI18n()

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="rounded-xl border bg-card p-4">
        <h3 className="font-semibold">{t("common.appearance")}</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("settings.preferencesDescription")}
        </p>
        <div className="mt-4 flex">
          <Appearance />
        </div>
      </div>
      <div className="rounded-xl border bg-card p-4">
        <h3 className="font-semibold">{t("common.language")}</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("settings.preferencesDescription")}
        </p>
        <div className="mt-4 flex">
          <LanguageSwitcher />
        </div>
      </div>
    </div>
  )
}

export const Route = createFileRoute("/_layout/settings")({
  component: UserSettings,
  head: () => ({
    meta: [
      {
        title: "Settings - TermMan",
      },
    ],
  }),
})

function UserSettings() {
  const { t } = useI18n()
  const { user: currentUser } = useAuth()
  const tabsConfig = [
    {
      value: "preferences",
      title: t("settings.preferences"),
      component: PreferencesPanel,
    },
    {
      value: "my-profile",
      title: t("settings.profile"),
      component: UserInformation,
    },
    {
      value: "password",
      title: t("settings.password"),
      component: ChangePassword,
    },
    {
      value: "danger-zone",
      title: t("settings.dangerZone"),
      component: DeleteAccount,
    },
  ]
  const finalTabs = currentUser?.is_superuser ? tabsConfig : tabsConfig

  if (!currentUser) {
    return null
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          {t("settings.title")}
        </h1>
        <p className="text-muted-foreground">{t("settings.description")}</p>
      </div>

      <Tabs defaultValue="my-profile">
        <TabsList>
          {finalTabs.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value}>
              {tab.title}
            </TabsTrigger>
          ))}
        </TabsList>
        {finalTabs.map((tab) => (
          <TabsContent key={tab.value} value={tab.value}>
            <tab.component />
          </TabsContent>
        ))}
      </Tabs>
    </div>
  )
}
