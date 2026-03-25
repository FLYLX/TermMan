import { useQueryClient } from "@tanstack/react-query"
import { Upload } from "lucide-react"
import { useRef, useState } from "react"
import { SkillsService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import useCustomToast from "@/hooks/useCustomToast"

export function UploadSkillZip() {
  const [isOpen, setIsOpen] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault()
    const file = fileInputRef.current?.files?.[0]
    if (!file) return

    setIsUploading(true)
    try {
      const fileContent = await file.arrayBuffer()
      const base64 = btoa(
        new Uint8Array(fileContent).reduce(
          (data, byte) => data + String.fromCharCode(byte),
          "",
        ),
      )

      await SkillsService.uploadSkillZip({
        requestBody: {
          file: `data:application/zip;base64,${base64}`,
        },
      })
      showSuccessToast("Skill uploaded successfully")
      queryClient.invalidateQueries({ queryKey: ["skills"] })
      setIsOpen(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ""
      }
    } catch (_error) {
      showErrorToast("Failed to upload skill")
    } finally {
      setIsUploading(false)
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon" title="Upload Zip">
          <Upload className="h-4 w-4" />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Upload Skill Zip</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleUpload} className="space-y-4">
          <div className="border-2 border-dashed rounded-lg p-8 text-center">
            <input
              ref={fileInputRef}
              type="file"
              accept=".zip"
              className="hidden"
              id="skill-zip"
              onChange={() => {}}
            />
            <label
              htmlFor="skill-zip"
              className="cursor-pointer flex flex-col items-center gap-2"
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload className="h-8 w-8 text-muted-foreground" />
              <span className="text-sm text-muted-foreground">
                Click to select a .zip file
              </span>
              <span className="text-xs text-muted-foreground">
                The zip should contain a skill folder with SKILL.md
              </span>
            </label>
          </div>
          {fileInputRef.current?.files?.[0] && (
            <p className="text-sm text-center">
              Selected: {fileInputRef.current.files[0].name}
            </p>
          )}
          <Button
            type="submit"
            className="w-full"
            disabled={!fileInputRef.current?.files?.[0] || isUploading}
          >
            {isUploading ? "Uploading..." : "Upload"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export default UploadSkillZip
