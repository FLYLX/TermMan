import { zodResolver } from "@hookform/resolvers/zod"
import {
  createFileRoute,
  Link as RouterLink,
  redirect,
} from "@tanstack/react-router"
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
        title: "Log In - TermPaws",
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
