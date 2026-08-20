import { X } from "lucide-react"
import type { ReactNode } from "react"

interface SketchDialogProps {
  open: boolean
  onClose: () => void
  title: ReactNode
  description?: string
  children: ReactNode
}

export function SketchDialog({
  open,
  onClose,
  title,
  description,
  children,
}: SketchDialogProps) {
  if (!open) {
    return null
  }
  return (
    <div
      className="pe-auto"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 90,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "2rem",
        background: "rgba(255,255,255,.78)",
      }}
    >
      <div
        className="sketch-box sketch-a"
        style={{
          width: "min(680px, 94vw)",
          maxHeight: "84vh",
          overflow: "auto",
          padding: 20,
          background: "#fff",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 12,
            marginBottom: 12,
          }}
        >
          <div>
            <div style={{ fontWeight: 800, fontSize: 15 }}>{title}</div>
            {description ? (
              <p style={{ fontSize: 12, color: "#565654", marginTop: 4 }}>
                {description}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            style={{ flexShrink: 0 }}
          >
            <X className="size-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
