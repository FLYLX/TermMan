import {
  AlertCircle,
  ArrowUp,
  ChevronRight,
  Download,
  FileText,
  Folder,
  FolderPlus,
  Loader2,
  Pencil,
  RefreshCw,
  Save,
  Trash2,
  Upload,
} from "lucide-react"
import {
  type ChangeEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"
import { OpenAPI } from "@/client"
import { useI18n } from "@/components/locale-provider"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import { cn } from "@/lib/utils"

type FileEntry = {
  name: string
  path: string
  type: "directory" | "file"
  size: number | null
  modified_at: number
  has_children: boolean
  is_symlink: boolean
}

type FileTreeResponse = {
  success: boolean
  current_path: string
  entries: FileEntry[]
}

type FileContentResponse = {
  success: boolean
  item_uuid: string
  path: string
  size: number
  encoding: string
  truncated: boolean
  content: string
}

type FileDefaultPathResponse = {
  success: boolean
  item_uuid: string
  path: string
}

type FileTicketResponse = {
  success: boolean
  ticket: string
  daemon_url: string
  url: string
  path: string
}

type FileActionResponse = {
  success: boolean
  path: string
  target_path?: string
  type?: "directory" | "file"
}

type FileWriteResponse = {
  success: boolean
  path: string
  size: number
  encoding: string
}

type DirectoryState = {
  entries: FileEntry[]
  isLoading: boolean
  error: string | null
  loaded: boolean
}

type UploadProgressState = {
  fileName: string
  fileIndex: number
  fileCount: number
  loadedBytes: number
  totalBytes: number
  speedBytesPerSecond: number
}

const ROOT_PATH = "/"
const EDITOR_PREVIEW_BYTES = 1024 * 1024

function normalizePath(path?: string | null) {
  const normalized = (path || "").replace(/\\/g, "/").trim()
  if (!normalized || normalized === "." || normalized === ROOT_PATH) {
    return ROOT_PATH
  }
  return normalized.replace(/^\/+/, "").replace(/\/+$/, "") || ROOT_PATH
}

function getPathSegments(path: string) {
  return normalizePath(path).split("/").filter(Boolean)
}

function getParentPath(path: string) {
  const segments = getPathSegments(path)
  if (segments.length <= 1) {
    return ROOT_PATH
  }
  return segments.slice(0, -1).join("/")
}

function joinPath(basePath: string, name: string) {
  const normalizedBase = normalizePath(basePath)
  const normalizedName = name.trim().replace(/\\/g, "/").replace(/^\/+/, "")
  if (!normalizedName) {
    return ""
  }
  return normalizedBase === ROOT_PATH
    ? normalizedName
    : `${normalizedBase}/${normalizedName}`
}

function isPathWithin(path: string, ancestorPath: string) {
  const normalizedPath = normalizePath(path)
  const normalizedAncestor = normalizePath(ancestorPath)
  if (normalizedAncestor === ROOT_PATH) {
    return true
  }
  return (
    normalizedPath === normalizedAncestor ||
    normalizedPath.startsWith(`${normalizedAncestor}/`)
  )
}

function replacePathPrefix(
  path: string,
  sourcePath: string,
  targetPath: string,
) {
  const normalizedPath = normalizePath(path)
  const normalizedSource = normalizePath(sourcePath)
  const normalizedTarget = normalizePath(targetPath)
  if (normalizedPath === normalizedSource) {
    return normalizedTarget
  }
  if (
    normalizedSource !== ROOT_PATH &&
    normalizedPath.startsWith(`${normalizedSource}/`)
  ) {
    return `${normalizedTarget}${normalizedPath.slice(normalizedSource.length)}`
  }
  return normalizedPath
}

function formatBytes(value: number | null) {
  if (value === null) {
    return "-"
  }

  if (value < 1024) {
    return `${value} B`
  }

  const units = ["KB", "MB", "GB", "TB"]
  let size = value
  let unitIndex = -1

  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex += 1
  }

  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unitIndex]}`
}

function formatTimestamp(value: number | undefined, localeTag: string) {
  if (!value) {
    return ""
  }

  return new Intl.DateTimeFormat(localeTag, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value * 1000))
}

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem("access_token") || ""
  const headers = new Headers(init?.headers || {})
  headers.set("Authorization", `Bearer ${token}`)

  if (
    init?.body &&
    !(init.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json")
  }

  const response = await fetch(`${OpenAPI.BASE}${path}`, {
    ...init,
    headers,
  })

  if (!response.ok) {
    let detail = "Request failed"
    try {
      const payload = await response.json()
      detail = payload.detail || detail
    } catch {
      detail = response.statusText || detail
    }
    throw new Error(detail)
  }

  return response.json() as Promise<T>
}

async function daemonRequest(url: string, ticket: string, init?: RequestInit) {
  const headers = new Headers(init?.headers || {})
  headers.set("Authorization", `Bearer ${ticket}`)

  const response = await fetch(url, {
    ...init,
    headers,
  })

  if (!response.ok) {
    let detail = "Daemon request failed"
    try {
      const payload = await response.json()
      detail = payload.detail || detail
    } catch {
      detail = response.statusText || detail
    }
    throw new Error(detail)
  }

  return response
}

function daemonUploadWithProgress(
  url: string,
  ticket: string,
  formData: FormData,
  onProgress: (loadedBytes: number) => void,
) {
  return new Promise<void>((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open("POST", url)
    request.setRequestHeader("Authorization", `Bearer ${ticket}`)

    request.upload.onprogress = (event) => {
      onProgress(event.loaded)
    }

    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        resolve()
        return
      }

      let detail = request.statusText || "Daemon request failed"
      try {
        const payload = JSON.parse(request.responseText)
        detail = payload.detail || detail
      } catch {
        // Keep the status text fallback.
      }
      reject(new Error(detail))
    }

    request.onerror = () => reject(new Error("Daemon request failed"))
    request.onabort = () => reject(new Error("Upload aborted"))
    request.send(formData)
  })
}

export function ItemFilesPanel({ itemId }: { itemId: string }) {
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const directoriesRef = useRef<Record<string, DirectoryState>>({})
  const { t, localeTag } = useI18n()
  const { showErrorToast, showSuccessToast } = useCustomToast()

  const [directories, setDirectories] = useState<
    Record<string, DirectoryState>
  >({
    [ROOT_PATH]: {
      entries: [],
      isLoading: false,
      error: null,
      loaded: false,
    },
  })
  const [selectedPath, setSelectedPath] = useState(ROOT_PATH)
  const [selectedType, setSelectedType] = useState<"directory" | "file">(
    "directory",
  )
  const [pathInput, setPathInput] = useState(ROOT_PATH)
  const [isJumpingPath, setIsJumpingPath] = useState(false)

  const [selectedContent, setSelectedContent] =
    useState<FileContentResponse | null>(null)
  const [editorContent, setEditorContent] = useState("")
  const [originalContent, setOriginalContent] = useState("")
  const [isLoadingContent, setIsLoadingContent] = useState(false)
  const [isSavingContent, setIsSavingContent] = useState(false)
  const [contentError, setContentError] = useState<string | null>(null)

  const [isUploading, setIsUploading] = useState(false)
  const [uploadProgress, setUploadProgress] =
    useState<UploadProgressState | null>(null)
  const [isCreatingFolder, setIsCreatingFolder] = useState(false)
  const [actionPath, setActionPath] = useState<string | null>(null)
  const [downloadingPath, setDownloadingPath] = useState<string | null>(null)

  useEffect(() => {
    directoriesRef.current = directories
  }, [directories])

  const selectedDirectoryPath = useMemo(() => {
    return selectedType === "directory"
      ? normalizePath(selectedPath)
      : getParentPath(selectedPath)
  }, [selectedPath, selectedType])
  const currentPath = useMemo(() => normalizePath(selectedPath), [selectedPath])
  const currentPathSegments = useMemo(
    () => getPathSegments(currentPath),
    [currentPath],
  )

  const selectedDirectory = directories[selectedDirectoryPath]
  const hasUnsavedChanges =
    Boolean(selectedContent) && editorContent !== originalContent

  useEffect(() => {
    setPathInput(currentPath)
  }, [currentPath])

  const confirmDiscardUnsavedChanges = useCallback(() => {
    if (!hasUnsavedChanges) {
      return true
    }
    return window.confirm(t("files.discardChanges"))
  }, [hasUnsavedChanges, t])

  const loadDirectory = useCallback(
    async (path: string, options?: { force?: boolean }) => {
      const directoryPath = normalizePath(path)
      const cached = directoriesRef.current[directoryPath]
      if (!options?.force && cached?.loaded && !cached.error) {
        return cached.entries
      }

      setDirectories((previous) => ({
        ...previous,
        [directoryPath]: {
          entries: previous[directoryPath]?.entries || [],
          isLoading: true,
          error: null,
          loaded: previous[directoryPath]?.loaded || false,
        },
      }))

      try {
        const search = new URLSearchParams({ path: directoryPath })
        const result = await apiRequest<FileTreeResponse>(
          `/api/v1/items/${itemId}/files/tree?${search.toString()}`,
        )
        const currentPath = normalizePath(result.current_path)
        setDirectories((previous) => ({
          ...previous,
          [currentPath]: {
            entries: result.entries,
            isLoading: false,
            error: null,
            loaded: true,
          },
        }))
        return result.entries
      } catch (error) {
        const message =
          error instanceof Error ? error.message : t("files.loadFailed")
        setDirectories((previous) => ({
          ...previous,
          [directoryPath]: {
            entries: previous[directoryPath]?.entries || [],
            isLoading: false,
            error: message,
            loaded: true,
          },
        }))
        throw error
      }
    },
    [itemId, t],
  )

  const refreshExplorer = useCallback(async () => {
    const directoriesToRefresh = Array.from(
      new Set([ROOT_PATH, selectedDirectoryPath]),
    )
    await Promise.all(
      directoriesToRefresh.map((directoryPath) =>
        loadDirectory(directoryPath, { force: true }),
      ),
    )
  }, [loadDirectory, selectedDirectoryPath])

  const resetEditor = useCallback(() => {
    setSelectedContent(null)
    setEditorContent("")
    setOriginalContent("")
    setContentError(null)
  }, [])

  const fetchFileContent = useCallback(
    async (path: string) => {
      const filePath = normalizePath(path)
      await loadDirectory(getParentPath(filePath))
      const search = new URLSearchParams({
        path: filePath,
        preview_bytes: String(EDITOR_PREVIEW_BYTES),
      })
      return apiRequest<FileContentResponse>(
        `/api/v1/items/${itemId}/files/content?${search.toString()}`,
      )
    },
    [itemId, loadDirectory],
  )

  const applyFileContent = useCallback((result: FileContentResponse) => {
    const filePath = normalizePath(result.path)
    setSelectedPath(filePath)
    setSelectedType("file")
    setSelectedContent(result)
    setEditorContent(result.content)
    setOriginalContent(result.content)
  }, [])

  const loadFileContent = useCallback(
    async (path: string) => {
      const filePath = normalizePath(path)
      setSelectedPath(filePath)
      setSelectedType("file")
      setIsLoadingContent(true)
      setContentError(null)

      try {
        const result = await fetchFileContent(filePath)
        applyFileContent(result)
      } catch (error) {
        const message =
          error instanceof Error ? error.message : t("files.loadFailed")
        resetEditor()
        setContentError(message)
      } finally {
        setIsLoadingContent(false)
      }
    },
    [applyFileContent, fetchFileContent, resetEditor, t],
  )

  useEffect(() => {
    let cancelled = false

    const initializeExplorer = async () => {
      setDirectories({
        [ROOT_PATH]: {
          entries: [],
          isLoading: false,
          error: null,
          loaded: false,
        },
      })
      setSelectedPath(ROOT_PATH)
      setSelectedType("directory")
      resetEditor()

      let defaultPath = ROOT_PATH
      try {
        const result = await apiRequest<FileDefaultPathResponse>(
          `/api/v1/items/${itemId}/files/default-path`,
        )
        defaultPath = normalizePath(result.path)
      } catch {
        defaultPath = ROOT_PATH
      }

      await loadDirectory(ROOT_PATH, { force: true })
      if (cancelled) {
        return
      }

      setSelectedPath(defaultPath)
      setSelectedType("directory")
      await loadDirectory(defaultPath, { force: true })
    }

    void initializeExplorer()

    return () => {
      cancelled = true
    }
  }, [itemId, loadDirectory, resetEditor])

  useEffect(() => {
    const handleSaveShortcut = (event: KeyboardEvent) => {
      if (
        !(event.ctrlKey || event.metaKey) ||
        event.key.toLowerCase() !== "s"
      ) {
        return
      }
      if (selectedType !== "file" || !selectedContent || !hasUnsavedChanges) {
        return
      }
      event.preventDefault()
      void (async () => {
        if (selectedContent.truncated) {
          showErrorToast(t("files.partialEditDisabled"))
          return
        }
        if (isSavingContent) {
          return
        }
        setIsSavingContent(true)
        try {
          const result = await apiRequest<FileWriteResponse>(
            `/api/v1/items/${itemId}/files/write`,
            {
              method: "POST",
              body: JSON.stringify({
                path: selectedContent.path,
                content: editorContent,
                encoding: selectedContent.encoding || "utf-8",
              }),
            },
          )
          setOriginalContent(editorContent)
          setSelectedContent((previous) =>
            previous
              ? {
                  ...previous,
                  path: result.path,
                  size: result.size,
                  encoding: result.encoding,
                  content: editorContent,
                  truncated: false,
                }
              : previous,
          )
          showSuccessToast(t("files.saved"))
          await refreshExplorer()
        } catch (error) {
          const message =
            error instanceof Error ? error.message : t("files.saveFailed")
          showErrorToast(message)
        } finally {
          setIsSavingContent(false)
        }
      })()
    }

    window.addEventListener("keydown", handleSaveShortcut)
    return () => window.removeEventListener("keydown", handleSaveShortcut)
  }, [
    editorContent,
    hasUnsavedChanges,
    isSavingContent,
    itemId,
    refreshExplorer,
    selectedContent,
    selectedType,
    showErrorToast,
    showSuccessToast,
    t,
  ])

  const handleRefresh = useCallback(async () => {
    if (
      selectedType === "file" &&
      hasUnsavedChanges &&
      !confirmDiscardUnsavedChanges()
    ) {
      return
    }

    await refreshExplorer()
    if (selectedType === "file" && selectedPath !== ROOT_PATH) {
      await loadFileContent(selectedPath)
    }
  }, [
    confirmDiscardUnsavedChanges,
    hasUnsavedChanges,
    loadFileContent,
    refreshExplorer,
    selectedPath,
    selectedType,
  ])

  const handleSelectDirectory = useCallback(
    async (path: string) => {
      if (!confirmDiscardUnsavedChanges()) {
        return
      }

      const directoryPath = normalizePath(path)
      setSelectedPath(directoryPath)
      setSelectedType("directory")
      resetEditor()
      try {
        await loadDirectory(directoryPath)
      } catch {
        return
      }
    },
    [confirmDiscardUnsavedChanges, loadDirectory, resetEditor],
  )

  const handleSelectFile = useCallback(
    async (path: string) => {
      if (!confirmDiscardUnsavedChanges()) {
        return
      }
      await loadFileContent(path)
    },
    [confirmDiscardUnsavedChanges, loadFileContent],
  )

  const handleGoToParent = useCallback(async () => {
    if (selectedDirectoryPath === ROOT_PATH) {
      return
    }

    await handleSelectDirectory(getParentPath(selectedDirectoryPath))
  }, [handleSelectDirectory, selectedDirectoryPath])

  const handleJumpToPath = useCallback(async () => {
    const targetPath = normalizePath(pathInput)

    if (targetPath === currentPath) {
      setPathInput(targetPath)
      return
    }

    if (!confirmDiscardUnsavedChanges()) {
      setPathInput(currentPath)
      return
    }

    setIsJumpingPath(true)
    setContentError(null)
    try {
      try {
        await loadDirectory(targetPath, { force: true })
        setSelectedPath(targetPath)
        setSelectedType("directory")
        resetEditor()
      } catch {
        const result = await fetchFileContent(targetPath)
        applyFileContent(result)
      }
    } catch (error) {
      const message =
        error instanceof Error ? error.message : t("files.pathJumpFailed")
      setPathInput(currentPath)
      showErrorToast(message)
    } finally {
      setIsJumpingPath(false)
    }
  }, [
    applyFileContent,
    confirmDiscardUnsavedChanges,
    currentPath,
    fetchFileContent,
    loadDirectory,
    pathInput,
    resetEditor,
    showErrorToast,
    t,
  ])

  const handleSaveContent = useCallback(async () => {
    if (!selectedContent) {
      return
    }
    if (selectedContent.truncated) {
      showErrorToast(t("files.partialEditDisabled"))
      return
    }

    setIsSavingContent(true)
    try {
      const result = await apiRequest<FileWriteResponse>(
        `/api/v1/items/${itemId}/files/write`,
        {
          method: "POST",
          body: JSON.stringify({
            path: selectedContent.path,
            content: editorContent,
            encoding: selectedContent.encoding || "utf-8",
          }),
        },
      )
      setOriginalContent(editorContent)
      setSelectedContent((previous) =>
        previous
          ? {
              ...previous,
              path: result.path,
              size: result.size,
              encoding: result.encoding,
              content: editorContent,
              truncated: false,
            }
          : previous,
      )
      showSuccessToast(t("files.saved"))
      await refreshExplorer()
    } catch (error) {
      const message =
        error instanceof Error ? error.message : t("files.saveFailed")
      showErrorToast(message)
    } finally {
      setIsSavingContent(false)
    }
  }, [
    editorContent,
    itemId,
    refreshExplorer,
    selectedContent,
    showErrorToast,
    showSuccessToast,
    t,
  ])

  const handleDownload = useCallback(
    async (path: string) => {
      const filePath = normalizePath(path)
      setDownloadingPath(filePath)
      try {
        const ticket = await apiRequest<FileTicketResponse>(
          `/api/v1/items/${itemId}/files/download-ticket`,
          {
            method: "POST",
            body: JSON.stringify({ path: filePath }),
          },
        )

        const response = await daemonRequest(ticket.url, ticket.ticket)
        const blob = await response.blob()
        const downloadUrl = URL.createObjectURL(blob)
        const anchor = document.createElement("a")
        anchor.href = downloadUrl
        anchor.download = filePath.split("/").pop() || "download"
        document.body.appendChild(anchor)
        anchor.click()
        anchor.remove()
        URL.revokeObjectURL(downloadUrl)
      } catch (error) {
        const message =
          error instanceof Error ? error.message : t("files.downloadFailed")
        showErrorToast(message)
      } finally {
        setDownloadingPath(null)
      }
    },
    [itemId, showErrorToast, t],
  )

  const handleCreateDirectory = useCallback(async () => {
    const name = window.prompt(t("files.newFolderName"))
    if (!name) {
      return
    }

    const path = joinPath(selectedDirectoryPath, name)
    if (!path) {
      showErrorToast(t("files.folderNameRequired"))
      return
    }

    setIsCreatingFolder(true)
    try {
      await apiRequest<FileActionResponse>(
        `/api/v1/items/${itemId}/files/mkdir`,
        {
          method: "POST",
          body: JSON.stringify({ path }),
        },
      )
      setSelectedPath(path)
      setSelectedType("directory")
      resetEditor()
      await loadDirectory(path, { force: true })
      await refreshExplorer()
      showSuccessToast(t("files.folderCreated"))
    } catch (error) {
      const message =
        error instanceof Error ? error.message : t("files.folderCreateFailed")
      showErrorToast(message)
    } finally {
      setIsCreatingFolder(false)
    }
  }, [
    itemId,
    loadDirectory,
    resetEditor,
    refreshExplorer,
    selectedDirectoryPath,
    showErrorToast,
    showSuccessToast,
    t,
  ])

  const handleRenameEntry = useCallback(
    async (entry: FileEntry) => {
      const nextName = window.prompt(t("files.renamePrompt"), entry.name)
      if (!nextName || nextName === entry.name) {
        return
      }

      const targetPath = joinPath(getParentPath(entry.path), nextName)
      if (!targetPath) {
        showErrorToast(t("files.renameFailed"))
        return
      }

      setActionPath(entry.path)
      try {
        const result = await apiRequest<FileActionResponse>(
          `/api/v1/items/${itemId}/files/rename`,
          {
            method: "POST",
            body: JSON.stringify({
              path: entry.path,
              target_path: targetPath,
            }),
          },
        )

        const nextPath = result.target_path || targetPath
        if (isPathWithin(selectedPath, entry.path)) {
          const remappedPath = replacePathPrefix(
            selectedPath,
            entry.path,
            nextPath,
          )
          setSelectedPath(remappedPath)

          if (selectedType === "file") {
            setSelectedContent((previous) =>
              previous
                ? {
                    ...previous,
                    path: replacePathPrefix(
                      previous.path,
                      entry.path,
                      nextPath,
                    ),
                  }
                : previous,
            )
          }
        }

        await refreshExplorer()
        showSuccessToast(t("files.itemRenamed"))
      } catch (error) {
        const message =
          error instanceof Error ? error.message : t("files.renameFailed")
        showErrorToast(message)
      } finally {
        setActionPath(null)
      }
    },
    [
      itemId,
      refreshExplorer,
      selectedPath,
      selectedType,
      showErrorToast,
      showSuccessToast,
      t,
    ],
  )

  const handleDeleteEntry = useCallback(
    async (entry: FileEntry) => {
      const entryType =
        entry.type === "directory" ? t("files.directory") : t("files.title")
      const confirmed = window.confirm(
        t("files.deleteConfirm", {
          type: entryType,
          name: entry.name,
        }),
      )
      if (!confirmed) {
        return
      }

      setActionPath(entry.path)
      try {
        await apiRequest<FileActionResponse>(
          `/api/v1/items/${itemId}/files/delete`,
          {
            method: "POST",
            body: JSON.stringify({ path: entry.path }),
          },
        )

        if (isPathWithin(selectedPath, entry.path)) {
          setSelectedPath(getParentPath(entry.path))
          setSelectedType("directory")
          resetEditor()
        }

        await refreshExplorer()
        showSuccessToast(
          entry.type === "directory"
            ? t("files.folderDeleted")
            : t("files.fileDeleted"),
        )
      } catch (error) {
        const message =
          error instanceof Error ? error.message : t("files.deleteFailed")
        showErrorToast(message)
      } finally {
        setActionPath(null)
      }
    },
    [
      itemId,
      refreshExplorer,
      resetEditor,
      selectedPath,
      showErrorToast,
      showSuccessToast,
      t,
    ],
  )

  const handleSelectUpload = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  const handleUploadFiles = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(event.target.files || [])
      if (!files.length) {
        return
      }

      setIsUploading(true)
      const totalBytes = files.reduce((sum, file) => sum + file.size, 0)
      const startedAt = performance.now()
      let completedBytes = 0
      try {
        for (const [index, file] of files.entries()) {
          const updateProgress = (currentFileLoadedBytes: number) => {
            const loadedBytes = Math.min(
              totalBytes,
              completedBytes + Math.min(currentFileLoadedBytes, file.size),
            )
            const elapsedSeconds = Math.max(
              0.001,
              (performance.now() - startedAt) / 1000,
            )
            setUploadProgress({
              fileName: file.name,
              fileIndex: index + 1,
              fileCount: files.length,
              loadedBytes,
              totalBytes,
              speedBytesPerSecond: loadedBytes / elapsedSeconds,
            })
          }

          updateProgress(0)
          const targetPath = joinPath(selectedDirectoryPath, file.name)
          const ticket = await apiRequest<FileTicketResponse>(
            `/api/v1/items/${itemId}/files/upload-ticket`,
            {
              method: "POST",
              body: JSON.stringify({
                path: targetPath,
                allow_overwrite: false,
              }),
            },
          )

          const formData = new FormData()
          formData.append("file", file)

          await daemonUploadWithProgress(
            ticket.url,
            ticket.ticket,
            formData,
            updateProgress,
          )
          completedBytes += file.size
          updateProgress(file.size)
        }

        await refreshExplorer()
        if (files.length === 1) {
          await loadFileContent(joinPath(selectedDirectoryPath, files[0].name))
        }
        showSuccessToast(t("files.uploadedCount", { count: files.length }))
      } catch (error) {
        const message =
          error instanceof Error ? error.message : t("files.uploadFailed")
        showErrorToast(message)
      } finally {
        event.target.value = ""
        setIsUploading(false)
        setUploadProgress(null)
      }
    },
    [
      itemId,
      loadFileContent,
      refreshExplorer,
      selectedDirectoryPath,
      showErrorToast,
      showSuccessToast,
      t,
    ],
  )

  const renderDirectoryEntries = useCallback(
    (directoryPath: string) => {
      const directory = directories[directoryPath]
      if (!directory) {
        return null
      }

      if (directory.error) {
        return (
          <div className="flex items-start gap-3 rounded-xl border border-red-500/20 bg-red-500/5 px-4 py-4 text-sm text-red-500">
            <AlertCircle className="mt-0.5 size-4 shrink-0" />
            <span>{directory.error}</span>
          </div>
        )
      }

      if (
        !directory.isLoading &&
        directory.loaded &&
        directory.entries.length === 0
      ) {
        return (
          <div className="px-4 py-6 text-sm text-muted-foreground">
            {t("files.folderEmpty")}
          </div>
        )
      }

      return directory.entries.map((entry) => {
        const isDirectory = entry.type === "directory"
        const isSelected =
          selectedPath === entry.path && selectedType === entry.type

        return (
          <div key={entry.path}>
            <div
              className={cn(
                "group flex items-center gap-2 rounded-lg px-2 py-1 text-sm transition-colors",
                isSelected
                  ? "bg-accent text-accent-foreground"
                  : "hover:bg-muted/50",
              )}
            >
              <button
                type="button"
                className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-1 py-1 text-left"
                onClick={() =>
                  void (isDirectory
                    ? handleSelectDirectory(entry.path)
                    : handleSelectFile(entry.path))
                }
              >
                {isDirectory ? (
                  <Folder className="size-4 shrink-0 text-yellow-500" />
                ) : (
                  <FileText className="size-4 shrink-0 text-sky-500" />
                )}
                <div className="min-w-0">
                  <div className="truncate font-medium">{entry.name}</div>
                  <div className="truncate text-xs text-muted-foreground">
                    {isDirectory
                      ? entry.has_children
                        ? t("files.directory")
                        : t("files.emptyDirectory")
                      : `${formatBytes(entry.size)} · ${formatTimestamp(entry.modified_at, localeTag)}`}
                  </div>
                </div>
              </button>

              <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                {!isDirectory && (
                  <Button
                    size="icon"
                    variant="ghost"
                    className="size-7 shrink-0"
                    disabled={downloadingPath === entry.path}
                    onClick={() => void handleDownload(entry.path)}
                  >
                    <Download className="size-4" />
                    <span className="sr-only">
                      {t("files.downloadLabel", { name: entry.name })}
                    </span>
                  </Button>
                )}
                <Button
                  size="icon"
                  variant="ghost"
                  className="size-7 shrink-0"
                  disabled={actionPath === entry.path}
                  onClick={() => void handleRenameEntry(entry)}
                >
                  <Pencil className="size-4" />
                  <span className="sr-only">
                    {t("files.renameLabel", { name: entry.name })}
                  </span>
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="size-7 shrink-0 text-red-500 hover:text-red-500"
                  disabled={actionPath === entry.path}
                  onClick={() => void handleDeleteEntry(entry)}
                >
                  <Trash2 className="size-4" />
                  <span className="sr-only">
                    {t("files.deleteLabel", { name: entry.name })}
                  </span>
                </Button>
              </div>
            </div>
          </div>
        )
      })
    },
    [
      actionPath,
      directories,
      downloadingPath,
      handleDeleteEntry,
      handleDownload,
      handleRenameEntry,
      handleSelectDirectory,
      handleSelectFile,
      localeTag,
      selectedPath,
      selectedType,
      t,
    ],
  )

  const selectedFileName =
    selectedContent?.path.split("/").pop() || t("files.noFileSelected")
  const explorerDirectory = directories[selectedDirectoryPath]
  const uploadPercent = uploadProgress?.totalBytes
    ? Math.min(
        100,
        Math.max(
          0,
          (uploadProgress.loadedBytes / uploadProgress.totalBytes) * 100,
        ),
      )
    : 0
  const uploadPercentLabel = `${uploadPercent.toFixed(uploadPercent >= 10 ? 0 : 1)}%`

  return (
    <section className="rounded-2xl border bg-card/85 p-4 shadow-sm">
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-xl font-semibold">{t("files.title")}</h2>
          <p className="text-sm text-muted-foreground">
            {t("files.description")}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => void handleRefresh()}
          >
            <RefreshCw
              className={cn(
                "size-4",
                explorerDirectory?.isLoading && "animate-spin",
              )}
            />
            {t("files.refresh")}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => void handleCreateDirectory()}
            disabled={isCreatingFolder}
          >
            <FolderPlus className="size-4" />
            {isCreatingFolder
              ? t("files.creatingFolder")
              : t("files.newFolder")}
          </Button>
          <Button size="sm" onClick={handleSelectUpload} disabled={isUploading}>
            <Upload className="size-4" />
            {isUploading ? t("files.uploading") : t("files.upload")}
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            multiple
            onChange={(event) => void handleUploadFiles(event)}
          />
        </div>
      </div>

      {isUploading && uploadProgress && (
        <div className="mb-4 rounded-xl border bg-muted/10 px-3 py-3">
          <div className="mb-2 flex min-w-0 items-center justify-between gap-3 text-xs">
            <div className="min-w-0">
              <div className="truncate font-medium text-foreground">
                {t("files.uploadProgressLabel", {
                  current: uploadProgress.fileIndex,
                  total: uploadProgress.fileCount,
                  name: uploadProgress.fileName,
                })}
              </div>
              <div className="truncate text-muted-foreground">
                {t("files.uploadProgressStats", {
                  loaded: formatBytes(uploadProgress.loadedBytes),
                  total: formatBytes(uploadProgress.totalBytes),
                  speed: `${formatBytes(uploadProgress.speedBytesPerSecond)}/s`,
                })}
              </div>
            </div>
            <span className="shrink-0 font-mono text-muted-foreground">
              {uploadPercentLabel}
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-[width] duration-150"
              style={{ width: uploadPercentLabel }}
            />
          </div>
        </div>
      )}

      <form
        className="mb-4 rounded-xl border bg-muted/10 px-3 py-3"
        onSubmit={(event) => {
          event.preventDefault()
          void handleJumpToPath()
        }}
      >
        <div className="flex flex-col gap-3 xl:flex-row xl:items-end">
          <div className="min-w-0 flex-1">
            <div className="mb-2 flex min-w-0 flex-wrap items-center gap-1 text-xs text-muted-foreground">
              <span className="mr-1 font-medium text-foreground">
                {t("files.currentPath")}
              </span>
              <button
                type="button"
                className="rounded px-1 py-0.5 font-mono hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:text-foreground"
                onClick={() => void handleSelectDirectory(ROOT_PATH)}
                disabled={currentPath === ROOT_PATH}
                title={ROOT_PATH}
              >
                {t("files.daemonRoot")}
              </button>
              {currentPathSegments.map((segment, index) => {
                const segmentPath = currentPathSegments
                  .slice(0, index + 1)
                  .join("/")
                const isLast = index === currentPathSegments.length - 1
                return (
                  <span
                    key={segmentPath}
                    className="flex min-w-0 items-center gap-1"
                  >
                    <ChevronRight className="size-3 shrink-0" />
                    <button
                      type="button"
                      className="max-w-[12rem] truncate rounded px-1 py-0.5 font-mono hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:text-foreground"
                      onClick={() => void handleSelectDirectory(segmentPath)}
                      disabled={isLast}
                      title={segmentPath}
                    >
                      {segment}
                    </button>
                  </span>
                )
              })}
            </div>
            <Input
              value={pathInput}
              onChange={(event) => setPathInput(event.target.value)}
              placeholder={t("files.pathPlaceholder")}
              className="font-mono"
              spellCheck={false}
              aria-label={t("files.pathInputLabel")}
            />
          </div>
          <Button
            type="submit"
            size="sm"
            className="shrink-0"
            disabled={isJumpingPath}
          >
            {isJumpingPath ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <ChevronRight className="size-4" />
            )}
            {t("files.jump")}
          </Button>
        </div>
      </form>

      <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
        <div className="rounded-2xl border bg-muted/10">
          <div className="border-b px-4 py-3">
            <div className="text-xs font-medium uppercase tracking-[0.2em] text-muted-foreground">
              {t("files.explorer")}
            </div>
            <div className="mt-2 truncate font-mono text-sm text-foreground">
              {selectedDirectoryPath === ROOT_PATH
                ? t("files.daemonRoot")
                : selectedDirectoryPath}
            </div>
          </div>

          <ScrollArea className="h-[40rem] px-2 py-3">
            {explorerDirectory?.isLoading && !explorerDirectory.loaded ? (
              <div className="flex items-center gap-2 px-3 py-4 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                {t("files.loading")}
              </div>
            ) : (
              <div className="space-y-1">
                <button
                  type="button"
                  className={cn(
                    "sticky top-0 z-10 flex w-full items-center gap-2 rounded-lg border bg-background/95 px-3 py-2 text-left text-sm font-medium backdrop-blur transition-colors",
                    selectedDirectoryPath === ROOT_PATH
                      ? "cursor-not-allowed border-dashed text-muted-foreground"
                      : "hover:bg-muted/50",
                  )}
                  onClick={() => void handleGoToParent()}
                  disabled={selectedDirectoryPath === ROOT_PATH}
                >
                  <ArrowUp className="size-4" />
                  <span>{t("files.parentDirectory")}</span>
                </button>
                {renderDirectoryEntries(selectedDirectoryPath)}
              </div>
            )}
          </ScrollArea>
        </div>

        <div className="rounded-2xl border bg-muted/10">
          <div className="border-b px-4 py-3">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold">
                  {selectedFileName}
                </div>
                <div className="truncate text-xs text-muted-foreground">
                  {selectedContent
                    ? selectedContent.path
                    : selectedDirectoryPath === ROOT_PATH
                      ? t("files.selectFromExplorer")
                      : selectedDirectoryPath}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {selectedContent
                    ? `${formatBytes(selectedContent.size)} · ${selectedContent.encoding}${
                        selectedContent.truncated ? " · preview truncated" : ""
                      }`
                    : selectedDirectory?.loaded
                      ? t("files.itemsInFolder", {
                          count: selectedDirectory.entries.length,
                        })
                      : t("files.pickFileToEdit")}
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                {selectedContent && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => void handleDownload(selectedContent.path)}
                    disabled={downloadingPath === selectedContent.path}
                  >
                    <Download className="size-4" />
                    {t("files.download")}
                  </Button>
                )}
                <Button
                  size="sm"
                  onClick={() => void handleSaveContent()}
                  disabled={
                    !selectedContent ||
                    !hasUnsavedChanges ||
                    isSavingContent ||
                    selectedContent.truncated
                  }
                >
                  {isSavingContent ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <Save className="size-4" />
                  )}
                  {t("files.save")}
                </Button>
              </div>
            </div>
          </div>

          <div className="h-[40rem]">
            {isLoadingContent ? (
              <div className="flex h-full items-center justify-center gap-3 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                {t("files.loading")}
              </div>
            ) : contentError ? (
              <div className="flex h-full items-start gap-3 px-4 py-4 text-sm text-amber-500">
                <AlertCircle className="mt-0.5 size-4 shrink-0" />
                <span>{contentError}</span>
              </div>
            ) : selectedContent ? (
              <div className="flex h-full flex-col">
                {selectedContent.truncated && (
                  <div className="border-b border-amber-500/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-600 dark:text-amber-400">
                    {t("files.previewTruncatedMessage")}
                  </div>
                )}
                <Textarea
                  value={editorContent}
                  onChange={(event) => setEditorContent(event.target.value)}
                  spellCheck={false}
                  wrap="off"
                  disabled={selectedContent.truncated}
                  className="h-full min-h-0 resize-none rounded-none border-0 bg-[#111111] px-4 py-4 font-mono text-[13px] leading-6 text-slate-100 focus-visible:ring-0 focus-visible:ring-offset-0 disabled:cursor-not-allowed disabled:opacity-80"
                />
              </div>
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
                <Folder className="size-8 text-muted-foreground" />
                <div>
                  <div className="text-sm font-medium text-foreground">
                    {selectedDirectoryPath === ROOT_PATH
                      ? t("files.daemonRoot")
                      : selectedDirectoryPath}
                  </div>
                  <div className="mt-1 text-sm text-muted-foreground">
                    {t("files.editPrompt")}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
