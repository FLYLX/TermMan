import { toast } from "sonner"
import { useCallback } from "react"
import { useI18n } from "@/components/locale-provider"

const useCustomToast = () => {
  const { t } = useI18n()

  const showSuccessToast = useCallback((description: string) => {
    toast.success(t("toast.success"), {
      description,
    })
  }, [t])

  const showErrorToast = useCallback((description: string) => {
    toast.error(t("toast.error"), {
      description,
    })
  }, [t])

  return { showSuccessToast, showErrorToast }
}

export default useCustomToast
