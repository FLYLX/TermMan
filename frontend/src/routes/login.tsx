import { zodResolver } from "@hookform/resolvers/zod"
import { useQuery } from "@tanstack/react-query"
import {
  createFileRoute,
  Link as RouterLink,
  redirect,
} from "@tanstack/react-router"
import { useState } from "react"
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
import useCustomToast from "@/hooks/useCustomToast"
import { apiRequest } from "@/lib/api-request"

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
        title: "Log In - TermPaws",
      },
    ],
  }),
})

function SetupForm({
  onDone,
}: {
  onDone: (email: string, password: string) => void
}) {
  const { locale } = useI18n()
  const { showErrorToast } = useCustomToast()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async () => {
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
      showErrorToast(
        locale === "zh" ? "请输入有效的邮箱地址" : "Enter a valid email",
      )
      return
    }
    if (password.length < 8) {
      showErrorToast(locale === "zh" ? "密码至少 8 位" : "At least 8 characters")
      return
    }
    if (password !== confirm) {
      showErrorToast(
        locale === "zh" ? "两次输入的密码不一致" : "Passwords do not match",
      )
      return
    }
    setSubmitting(true)
    try {
      await apiRequest("/api/v1/utils/setup", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      })
      onDone(email, password)
    } catch (error) {
      showErrorToast(
        error instanceof Error ? error.message : "Setup failed",
      )
      setSubmitting(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1 text-left">
        <h1 className="text-xl font-black tracking-tight">
          {locale === "zh" ? "初始化管理员" : "Admin setup"}
        </h1>
        <p className="text-xs text-[#565654]">
          {locale === "zh"
            ? "第一个访问者设置管理员账号和密码，设置完成即成为超管。"
            : "The first visitor sets the admin email and password."}
        </p>
      </div>
      <div className="grid gap-4">
        <div className="space-y-1.5">
          <span className="text-xs text-[#565654]">
            {locale === "zh" ? "管理员邮箱" : "Admin email"}
          </span>
          <Input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="admin@example.com"
            autoComplete="username"
            className="rounded-[10px] border-2 border-[#3a3a3a] bg-white"
          />
        </div>
        <div className="space-y-1.5">
          <span className="text-xs text-[#565654]">
            {locale === "zh" ? "新密码（至少 8 位）" : "New password (min 8)"}
          </span>
          <PasswordInput
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            className="rounded-[10px] border-2 border-[#3a3a3a] bg-white"
          />
        </div>
        <div className="space-y-1.5">
          <span className="text-xs text-[#565654]">
            {locale === "zh" ? "确认密码" : "Confirm password"}
          </span>
          <PasswordInput
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
            className="rounded-[10px] border-2 border-[#3a3a3a] bg-white"
          />
        </div>
        <LoadingButton
          type="button"
          className="w-full border-2 border-[#3a3a3a] bg-white font-bold text-[#1f1f1f] shadow-[3px_4px_0_rgba(0,0,0,0.10)] hover:bg-[#f4f4f3]"
          loading={submitting}
          disabled={!email || !password}
          onClick={() => void handleSubmit()}
        >
          {locale === "zh" ? "创建管理员并登录" : "Create admin & log in"}
        </LoadingButton>
      </div>
    </div>
  )
}

function Login() {
  const { loginMutation } = useAuth()
  const { locale, t } = useI18n()
  const { data: setupState } = useQuery({
    queryKey: ["setup-required"],
    queryFn: () =>
      apiRequest<{ required: boolean }>("/api/v1/utils/setup-required"),
    staleTime: 0,
  })
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

  if (setupState?.required) {
    return (
      <AuthLayout>
        <SetupForm
          onDone={(email, password) =>
            loginMutation.mutate({
              username: email,
              password,
            })
          }
        />
      </AuthLayout>
    )
  }

  return (
    <AuthLayout>
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          className="flex flex-col gap-6"
        >
          <div className="flex flex-col gap-1 text-left">
            <h1 className="text-xl font-black tracking-tight">
              {t("brand.loginTitle")}
            </h1>
            <p className="text-xs text-[#565654]">
              {t("brand.loginDescription")}
            </p>
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
                      autoComplete="username"
                      className="rounded-[10px] border-2 border-[#3a3a3a] bg-white"
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
                      autoComplete="current-password"
                      className="rounded-[10px] border-2 border-[#3a3a3a] bg-white"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage className="text-xs" />
                </FormItem>
              )}
            />

            <LoadingButton
              type="submit"
              className="w-full border-2 border-[#3a3a3a] bg-white font-bold text-[#1f1f1f] shadow-[3px_4px_0_rgba(0,0,0,0.10)] hover:bg-[#f4f4f3]"
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
