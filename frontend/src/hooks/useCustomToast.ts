import { toast } from "sonner"
import { useI18n } from "@/components/locale-provider"

const useCustomToast = () => {
  const { t } = useI18n()

  const showSuccessToast = (description: string) => {
    toast.success(t("toast.success"), {
      description,
    })
  }

  const showErrorToast = (description: string) => {
    toast.error(t("toast.error"), {
      description,
    })
  }

  return { showSuccessToast, showErrorToast }
}

export default useCustomToast
