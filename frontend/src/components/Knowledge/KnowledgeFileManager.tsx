import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Download,
  FileText,
  Loader2,
  Search,
  Trash2,
  Upload,
} from "lucide-react"
import {
  type ChangeEvent,
  type DragEvent,
  useMemo,
  useRef,
  useState,
} from "react"

import { useI18n } from "@/components/locale-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import useCustomToast from "@/hooks/useCustomToast"

import {
  deleteKnowledgeLibraryFile,
  downloadKnowledgeLibraryFile,
  formatBytes,
  getKnowledgeLibraryQueryKey,
  type KnowledgeFileItem,
  listKnowledgeLibraryFiles,
  uploadKnowledgeLibraryFiles,
} from "./api"

export function KnowledgeFileManager() {
  const { t, localeTag } = useI18n()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const [searchQuery, setSearchQuery] = useState("")
  const [isUploading, setIsUploading] = useState(false)
  const [deletingPath, setDeletingPath] = useState<string | null>(null)
  const [isDragActive, setIsDragActive] = useState(false)

  const { data: knowledgeFilesData } = useQuery({
    queryKey: getKnowledgeLibraryQueryKey(),
    queryFn: () => listKnowledgeLibraryFiles(),
  })

  const knowledgeFiles = knowledgeFilesData?.data ?? []

  const filteredFiles = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase()
    if (!normalizedQuery) {
      return knowledgeFiles
    }

    return knowledgeFiles.filter(
      (file) =>
        file.name.toLowerCase().includes(normalizedQuery) ||
        file.path.toLowerCase().includes(normalizedQuery),
    )
  }, [knowledgeFiles, searchQuery])

  const refreshData = async () => {
    await queryClient.invalidateQueries({
      queryKey: getKnowledgeLibraryQueryKey(),
    })
    await queryClient.invalidateQueries({
      queryKey: ["itemHandler-knowledge"],
    })
    await queryClient.invalidateQueries({
      queryKey: ["itemHandlers"],
    })
  }

  const handleUpload = async (files: File[]) => {
    if (files.length === 0) {
      return
    }

    setIsUploading(true)
    try {
      await uploadKnowledgeLibraryFiles(files)
      await refreshData()
      showSuccessToast(
        t("itemHandlers.detail.knowledgeUploaded", { count: files.length }),
      )
    } catch (error) {
      showErrorToast(
        error instanceof Error
          ? error.message
          : t("itemHandlers.detail.knowledgeUploadFailed"),
      )
    } finally {
      setIsUploading(false)
    }
  }

  const handleFileInputChange = async (
    event: ChangeEvent<HTMLInputElement>,
  ) => {
    const files = Array.from(event.target.files ?? [])
    event.target.value = ""
    await handleUpload(files)
  }

  const handleDelete = async (filePath: string) => {
    setDeletingPath(filePath)
    try {
      await deleteKnowledgeLibraryFile(filePath)
      showSuccessToast(t("itemHandlers.detail.knowledgeDeleted"))
      await refreshData()
    } catch (error) {
      showErrorToast(
        error instanceof Error
          ? error.message
          : t("itemHandlers.detail.knowledgeDeleteFailed"),
      )
    } finally {
      setDeletingPath(null)
    }
  }

  const handleDownload = async (file: KnowledgeFileItem) => {
    if (file.missing) {
      return
    }

    try {
      await downloadKnowledgeLibraryFile(file)
    } catch (error) {
      showErrorToast(
        error instanceof Error ? error.message : t("files.downloadFailed"),
      )
    }
  }

  const handleDropUpload = async (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setIsDragActive(false)
    await handleUpload(Array.from(event.dataTransfer.files ?? []))
  }

  const formatModifiedAt = (timestamp: number | null) => {
    if (!timestamp) {
      return "-"
    }
    return new Date(timestamp * 1000).toLocaleString(localeTag, {
      dateStyle: "short",
      timeStyle: "short",
    })
  }

  return (
    <div
      className={`space-y-3 rounded-[20px] border bg-card p-3 shadow-sm transition-all md:p-4 ${
        isDragActive ? "border-primary/40 bg-primary/5" : ""
      }`}
      onDragOver={(event) => {
        event.preventDefault()
        setIsDragActive(true)
      }}
      onDragLeave={() => setIsDragActive(false)}
      onDrop={(event) => void handleDropUpload(event)}
    >
      <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div className="relative max-w-lg flex-1">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder={t("knowledge.searchFiles")}
            className="h-9 rounded-xl bg-background pl-10"
          />
        </div>
        <div className="flex items-center gap-2">
          <div className="hidden rounded-full border bg-muted/30 px-2.5 py-1 text-[11px] text-muted-foreground sm:inline-flex">
            {knowledgeFiles.length} {t("knowledge.filesTitle")}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".md,.markdown,.txt"
            className="hidden"
            onChange={(event) => void handleFileInputChange(event)}
          />
          <Button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading}
            className="h-9 rounded-xl px-3.5"
          >
            {isUploading ? (
              <Loader2 className="mr-2 size-4 animate-spin" />
            ) : (
              <Upload className="mr-2 size-4" />
            )}
            {t("itemHandlers.detail.uploadKnowledge")}
          </Button>
        </div>
      </div>

      {filteredFiles.length === 0 ? (
        <div className="rounded-[18px] border bg-muted/10 py-8">
          <div className="flex flex-col items-center justify-center gap-2 px-4 text-center">
            <FileText className="size-12 text-muted-foreground/40" />
            <div className="space-y-1">
              <div className="text-sm font-medium">
                {knowledgeFiles.length === 0
                  ? t("itemHandlers.detail.noKnowledgeFiles")
                  : t("knowledge.noMatchingFiles")}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2 2xl:grid-cols-3">
          {filteredFiles.map((file) => (
            <div
              key={file.path}
              className="flex h-full flex-col rounded-[18px] border bg-card transition-transform hover:-translate-y-0.5 hover:border-primary/30"
            >
              <div className="flex flex-1 flex-col p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex min-w-0 items-start gap-2.5">
                    <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
                      <FileText className="size-3.5" />
                    </div>
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">
                        {file.name}
                      </div>
                      <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
                        {file.path}
                      </div>
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
                    {file.indexed && (
                      <Badge
                        variant="outline"
                        className="h-5 border-primary/20 bg-primary/10 px-1.5 text-[10px] text-primary"
                      >
                        {t("itemHandlers.detail.knowledgeIndexed")}
                      </Badge>
                    )}
                    {file.missing && (
                      <Badge
                        variant="destructive"
                        className="h-5 px-1.5 text-[10px]"
                      >
                        {t("itemHandlers.detail.knowledgeMissing")}
                      </Badge>
                    )}
                    {!file.indexed && !file.missing && (
                      <Badge
                        variant="secondary"
                        className="h-5 px-1.5 text-[10px]"
                      >
                        {t("knowledge.readyStatus")}
                      </Badge>
                    )}
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                  <div className="whitespace-nowrap">
                    {t("knowledge.fileSize")} {formatBytes(file.size)}
                  </div>
                  <div className="whitespace-nowrap">
                    {t("knowledge.chunkCount")} {file.chunk_count}
                  </div>
                  <div className="truncate">
                    {t("knowledge.lastModified")}{" "}
                    {formatModifiedAt(file.modified_at)}
                  </div>
                </div>

                <div className="mt-3 flex items-center gap-2 border-t pt-3">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 rounded-lg px-3"
                    onClick={() => void handleDownload(file)}
                    disabled={file.missing}
                  >
                    <Download className="mr-1.5 size-3.5" />
                    {t("files.download")}
                  </Button>
                  <Button
                    type="button"
                    variant="destructive"
                    size="sm"
                    className="h-8 rounded-lg px-3"
                    onClick={() => void handleDelete(file.path)}
                    disabled={deletingPath === file.path}
                  >
                    {deletingPath === file.path ? (
                      <Loader2 className="mr-1.5 size-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="mr-1.5 size-3.5" />
                    )}
                    {t("common.delete")}
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
