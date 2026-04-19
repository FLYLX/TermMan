import { zodResolver } from "@hookform/resolvers/zod"
import {
  createFileRoute,
  Link as RouterLink,
  redirect,
} from "@tanstack/react-router"
import { Shield } from "lucide-react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import type { Body_login_login_access_token as AccessToken } from "@/client"
import { AuthLayout } from "@/components/Common/AuthLayout"
import { useI18n } from "@/components/locale-provider"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import { PasswordInput } from "@/components/ui/password-input"
import useAuth, { isLoggedIn } from "@/hooks/useAuth"

const formSchema = z.object({
  username: z.email(),
  password: z
    .string()
    .min(1, { message: "Password is required" })
    .min(8, { message: "Password must be at least 8 characters" }),
}) satisfies z.ZodType<AccessToken>

type FormData = z.infer<typeof formSchema>

export const Route = createFileRoute("/login")({
  component: Login,
  beforeLoad: async () => {
    if (isLoggedIn()) {
      throw redirect({
        to: "/",
      })
    }
  },
  head: () => ({
    meta: [
      {
        title: "Log In - TermMan",
      },
    ],
  }),
})

function Login() {
  const { loginMutation } = useAuth()
  const { locale, t } = useI18n()
  const copy =
    locale === "zh"
      ? {
          email: "邮箱",
          emailPlaceholder: "operator@example.com",
          password: "密码",
          passwordPlaceholder: "输入登录密码",
          forgotPassword: "忘记密码？",
          submit: "登录",
          noAccount: "还没有账户？",
          signUp: "注册",
          boundaryTitle: "这里展示的是 daemon -> agent 接入原理",
          boundaryDescription:
            "实际链路是 daemon 子进程输出先被 publish_stream 广播，再由 AgentInputBridge 和 stream_manager 送进 agent/xagent。登录页本身不会触发这条链路。",
        }
      : {
          email: "Email",
          emailPlaceholder: "operator@example.com",
          password: "Password",
          passwordPlaceholder: "Enter your password",
          forgotPassword: "Forgot your password?",
          submit: "Log In",
          noAccount: "Don't have an account yet?",
          signUp: "Sign up",
          boundaryTitle: "This page explains the daemon -> agent integration path",
          boundaryDescription:
            "The real path is daemon subprocess output -> publish_stream -> AgentInputBridge -> stream_manager -> agent/xagent. The login page itself does not trigger that runtime flow.",
        }
  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      username: "",
      password: "",
    },
  })

  const onSubmit = (data: FormData) => {
    if (loginMutation.isPending) return
    loginMutation.mutate(data)
  }

  return (
    <AuthLayout>
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          className="flex flex-col gap-6"
        >
          <div className="flex flex-col gap-2 text-left">
            <span className="rounded-full border border-primary/20 bg-primary/10 px-3 py-1 font-mono text-[10px] uppercase tracking-[0.34em] text-primary">
              {t("brand.loginBadge")}
            </span>
            <h1 className="text-2xl font-bold tracking-tight">
              {t("brand.loginTitle")}
            </h1>
            <p className="text-sm text-muted-foreground">
              {t("brand.loginDescription")}
            </p>
          </div>

          <div className="rounded-[24px] border border-emerald-500/20 bg-emerald-500/5 p-4">
            <div className="flex items-start gap-3">
              <div className="flex size-9 shrink-0 items-center justify-center rounded-2xl border border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">
                <Shield className="size-4" />
              </div>
              <div className="space-y-1">
                <p className="text-sm font-medium">{copy.boundaryTitle}</p>
                <p className="text-xs leading-5 text-muted-foreground">
                  {copy.boundaryDescription}
                </p>
              </div>
            </div>
          </div>

          <div className="grid gap-4">
            <FormField
              control={form.control}
              name="username"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{copy.email}</FormLabel>
                  <FormControl>
                    <Input
                      data-testid="email-input"
                      placeholder={copy.emailPlaceholder}
                      type="email"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage className="text-xs" />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="password"
              render={({ field }) => (
                <FormItem>
                  <div className="flex items-center">
                    <FormLabel>{copy.password}</FormLabel>
                    <RouterLink
                      to="/recover-password"
                      className="ml-auto text-sm underline-offset-4 hover:underline"
                    >
                      {copy.forgotPassword}
                    </RouterLink>
                  </div>
                  <FormControl>
                    <PasswordInput
                      data-testid="password-input"
                      placeholder={copy.passwordPlaceholder}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage className="text-xs" />
                </FormItem>
              )}
            />

            <LoadingButton
              type="submit"
              className="w-full"
              loading={loginMutation.isPending}
            >
              {copy.submit}
            </LoadingButton>
          </div>

          <div className="text-center text-sm">
            {copy.noAccount}{" "}
            <RouterLink to="/signup" className="underline underline-offset-4">
              {copy.signUp}
            </RouterLink>
          </div>
        </form>
      </Form>
    </AuthLayout>
  )
}
