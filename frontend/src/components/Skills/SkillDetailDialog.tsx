import { useQuery, useQueryClient } from "@tanstack/react-query"
import { FileCode, FilePlus, RefreshCw, Trash2 } from "lucide-react"
import { useState } from "react"
import { type SkillListItem, SkillsService } from "@/client"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"

interface SkillFile {
  path: string
  name: string
  size: number
  is_binary: boolean
}

interface SkillDetailDialogProps {
  skill: SkillListItem
  children: React.ReactNode
}

export function SkillDetailDialog({ skill, children }: SkillDetailDialogProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [fileContent, setFileContent] = useState<string>("")
  const [isSaving, setIsSaving] = useState(false)
  const [newFileDialog, setNewFileDialog] = useState(false)
  const [newFilePath, setNewFilePath] = useState("")
  const [deleteFileDialog, setDeleteFileDialog] = useState<string | null>(null)
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()

  const { data: detail, isLoading } = useQuery({
    queryKey: ["skill", skill.skill_id],
    queryFn: () => SkillsService.getSkill({ skillId: skill.skill_id }),
    enabled: isOpen,
  })

  const { data: filesData, refetch: refetchFiles } = useQuery({
    queryKey: ["skill-files", skill.skill_id],
    queryFn: async () => {
      const result = await SkillsService.listSkillFiles({
        skillId: skill.skill_id,
      })
      return result as { files: SkillFile[] }
    },
    enabled: isOpen,
  })

  const files = filesData?.files || []

  const handleFileClick = async (filePath: string) => {
    try {
      const result = await SkillsService.getSkillFile({
        skillId: skill.skill_id,
        filePath: filePath,
      })
      if (
        typeof result === "object" &&
        result !== null &&
        "content" in result
      ) {
        setFileContent(result.content as string)
        setSelectedFile(filePath)
      }
    } catch (error) {
      console.error("Failed to load file:", error)
      showErrorToast("Failed to load file")
    }
  }

  const handleSaveFile = async () => {
    if (!selectedFile) return
    setIsSaving(true)
    try {
      await SkillsService.updateSkillFile({
        skillId: skill.skill_id,
        filePath: selectedFile,
        requestBody: { content: fileContent },
      })
      showSuccessToast("File saved successfully")
      queryClient.invalidateQueries({ queryKey: ["skill", skill.skill_id] })
    } catch (error) {
      console.error("Failed to save file:", error)
      showErrorToast("Failed to save file")
    } finally {
      setIsSaving(false)
    }
  }

  const handleCreateFile = async () => {
    if (!newFilePath.trim()) {
      showErrorToast("File path is required")
      return
    }

    try {
      await SkillsService.createSkillFile({
        skillId: skill.skill_id,
        filePath: newFilePath,
        requestBody: { content: "" },
      })
      showSuccessToast("File created successfully")
      setNewFileDialog(false)
      setNewFilePath("")
      refetchFiles()
      setSelectedFile(newFilePath)
      setFileContent("")
    } catch (error) {
      console.error("Failed to create file:", error)
      showErrorToast("Failed to create file")
    }
  }

  const handleDeleteFile = async () => {
    if (!deleteFileDialog) return

    try {
      await SkillsService.deleteSkillFile({
        skillId: skill.skill_id,
        filePath: deleteFileDialog,
      })
      showSuccessToast("File deleted successfully")
      setDeleteFileDialog(null)
      if (selectedFile === deleteFileDialog) {
        setSelectedFile(null)
        setFileContent("")
      }
      refetchFiles()
    } catch (error) {
      console.error("Failed to delete file:", error)
      showErrorToast("Failed to delete file")
    }
  }

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const getFileIcon = (file: SkillFile) => {
    if (file.is_binary) {
      return <FileCode className="h-4 w-4 text-orange-500" />
    }
    if (file.name.endsWith(".md")) {
      return <FileCode className="h-4 w-4 text-blue-500" />
    }
    if (file.name.endsWith(".py") || file.name.endsWith(".sh")) {
      return <FileCode className="h-4 w-4 text-green-500" />
    }
    if (file.name.endsWith(".json")) {
      return <FileCode className="h-4 w-4 text-yellow-500" />
    }
    return <FileCode className="h-4 w-4" />
  }

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="max-w-4xl max-h-[80vh]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {skill.name}
            <Badge variant="secondary">{skill.category}</Badge>
          </DialogTitle>
        </DialogHeader>
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <RefreshCw className="h-6 w-6 animate-spin" />
          </div>
        ) : detail ? (
          <Tabs defaultValue="files" className="w-full">
            <TabsList>
              <TabsTrigger value="info">Info</TabsTrigger>
              <TabsTrigger value="content">SKILL.md</TabsTrigger>
              <TabsTrigger value="files">Files ({files.length})</TabsTrigger>
            </TabsList>
            <TabsContent value="info" className="space-y-4">
              <div>
                <h4 className="font-semibold mb-2">Description</h4>
                <p className="text-muted-foreground">
                  {detail.description || "No description"}
                </p>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <h4 className="font-semibold mb-2">Trigger</h4>
                  <pre className="text-xs bg-muted p-2 rounded overflow-auto max-h-40">
                    {JSON.stringify(detail.trigger, null, 2)}
                  </pre>
                </div>
                <div>
                  <h4 className="font-semibold mb-2">Action</h4>
                  <pre className="text-xs bg-muted p-2 rounded overflow-auto max-h-40">
                    {JSON.stringify(detail.action, null, 2)}
                  </pre>
                </div>
              </div>
              <div>
                <h4 className="font-semibold mb-2">Safety</h4>
                <pre className="text-xs bg-muted p-2 rounded overflow-auto max-h-40">
                  {JSON.stringify(detail.safety, null, 2)}
                </pre>
              </div>
              <div className="flex gap-4">
                <div>
                  <h4 className="font-semibold mb-1">Scripts</h4>
                  <div className="flex gap-1 flex-wrap">
                    {detail.scripts.length > 0 ? (
                      detail.scripts.map((s) => (
                        <Badge key={s} variant="outline">
                          {s}
                        </Badge>
                      ))
                    ) : (
                      <span className="text-sm text-muted-foreground">
                        None
                      </span>
                    )}
                  </div>
                </div>
                <div>
                  <h4 className="font-semibold mb-1">Templates</h4>
                  <div className="flex gap-1 flex-wrap">
                    {detail.templates.length > 0 ? (
                      detail.templates.map((t) => (
                        <Badge key={t} variant="outline">
                          {t}
                        </Badge>
                      ))
                    ) : (
                      <span className="text-sm text-muted-foreground">
                        None
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </TabsContent>
            <TabsContent value="content">
              <ScrollArea className="h-[400px]">
                <pre className="text-xs bg-muted p-4 rounded whitespace-pre-wrap">
                  {detail.content}
                </pre>
              </ScrollArea>
            </TabsContent>
            <TabsContent value="files">
              <div className="flex gap-4">
                <div className="w-1/3 border rounded p-2">
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="font-semibold text-sm">Files</h4>
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setNewFileDialog(true)}
                        title="Create new file"
                      >
                        <FilePlus className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => refetchFiles()}
                        title="Refresh"
                      >
                        <RefreshCw className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                  <ScrollArea className="h-[350px]">
                    {files.length === 0 ? (
                      <div className="text-sm text-muted-foreground text-center py-4">
                        No files found
                      </div>
                    ) : (
                      files.map((file) => (
                        <div
                          key={file.path}
                          className={`flex items-center justify-between p-2 rounded cursor-pointer hover:bg-muted ${
                            selectedFile === file.path ? "bg-muted" : ""
                          }`}
                        >
                          <div
                            className="flex items-center gap-2 flex-1 min-w-0"
                            onClick={() =>
                              !file.is_binary && handleFileClick(file.path)
                            }
                          >
                            {getFileIcon(file)}
                            <div className="flex flex-col min-w-0">
                              <span className="text-sm truncate">
                                {file.path}
                              </span>
                              <span className="text-xs text-muted-foreground">
                                {formatFileSize(file.size)}
                                {file.is_binary && " (binary)"}
                              </span>
                            </div>
                          </div>
                          {!file.is_binary && file.path !== "SKILL.md" && (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-6 w-6"
                              onClick={(e) => {
                                e.stopPropagation()
                                setDeleteFileDialog(file.path)
                              }}
                            >
                              <Trash2 className="h-3 w-3 text-destructive" />
                            </Button>
                          )}
                        </div>
                      ))
                    )}
                  </ScrollArea>
                </div>
                <div className="flex-1 border rounded p-2">
                  {selectedFile ? (
                    <div className="h-full flex flex-col">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm font-medium">
                          {selectedFile}
                        </span>
                        <Button
                          size="sm"
                          onClick={handleSaveFile}
                          disabled={isSaving}
                        >
                          {isSaving ? "Saving..." : "Save"}
                        </Button>
                      </div>
                      <Textarea
                        className="flex-1 font-mono text-xs min-h-[300px]"
                        value={fileContent}
                        onChange={(e) => setFileContent(e.target.value)}
                      />
                    </div>
                  ) : (
                    <div className="h-full flex items-center justify-center text-muted-foreground">
                      Select a file to edit
                    </div>
                  )}
                </div>
              </div>
            </TabsContent>
          </Tabs>
        ) : null}
      </DialogContent>

      <Dialog open={newFileDialog} onOpenChange={setNewFileDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create New File</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium">File Path</label>
              <p className="text-xs text-muted-foreground mb-2">
                e.g., scripts/my_script.sh, templates/output.txt
              </p>
              <Input
                value={newFilePath}
                onChange={(e) => setNewFilePath(e.target.value)}
                placeholder="scripts/new_script.sh"
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setNewFileDialog(false)}>
                Cancel
              </Button>
              <Button onClick={handleCreateFile}>Create</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={!!deleteFileDialog}
        onOpenChange={() => setDeleteFileDialog(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete File</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete "{deleteFileDialog}"? This action
              cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteFile}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Dialog>
  )
}

export default SkillDetailDialog
