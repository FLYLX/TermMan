// source: https://usehooks-ts.com/react-hook/use-copy-to-clipboard
import { useCallback, useState } from "react"

type CopiedValue = string | null

type CopyFn = (text: string) => Promise<boolean>

function fallbackCopyText(text: string) {
  if (typeof document === "undefined") {
    return false
  }
  const textarea = document.createElement("textarea")
  textarea.value = text
  textarea.setAttribute("readonly", "")
  textarea.style.position = "fixed"
  textarea.style.left = "-9999px"
  textarea.style.opacity = "0"
  document.body.appendChild(textarea)
  textarea.focus()
  textarea.select()
  try {
    return document.execCommand("copy")
  } finally {
    document.body.removeChild(textarea)
  }
}

export function useCopyToClipboard(): [CopiedValue, CopyFn] {
  const [copiedText, setCopiedText] = useState<CopiedValue>(null)

  const copy: CopyFn = useCallback(async (text) => {
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(text)
      } else if (!fallbackCopyText(text)) {
        throw new Error("Clipboard not supported")
      }
      setCopiedText(text)

      setTimeout(() => setCopiedText(null), 2000)

      return true
    } catch (error) {
      try {
        if (!fallbackCopyText(text)) {
          throw error
        }
        setCopiedText(text)
        setTimeout(() => setCopiedText(null), 2000)
        return true
      } catch (fallbackError) {
        console.warn("Copy failed", fallbackError)
        setCopiedText(null)
        return false
      }
    }
  }, [])

  return [copiedText, copy]
}
