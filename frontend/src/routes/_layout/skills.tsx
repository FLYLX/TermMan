import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { RefreshCw, Search } from "lucide-react"
import { Suspense } from "react"

import { SkillsService } from "@/client"
import { DataTable } from "@/components/Common/DataTable"
import PendingItems from "@/components/Pending/PendingItems"
import AddSkill from "@/components/Skills/AddSkill"
import { columns } from "@/components/Skills/columns"
import UploadSkillZip from "@/components/Skills/UploadSkillZip"
import { Button } from "@/components/ui/button"
import useAuth from "@/hooks/useAuth"

function getSkillsQueryOptions() {
  return {
    queryFn: () => SkillsService.listSkills({}),
    queryKey: ["skills"],
  }
}

export const Route = createFileRoute("/_layout/skills")({
  component: Skills,
  head: () => ({
    meta: [
      {
        title: "Skills - TermMan",
      },
    ],
  }),
})

function SkillsTable() {
  const { data: skills } = useSuspenseQuery(getSkillsQueryOptions())
  const { user: currentUser } = useAuth()

  const handleReload = async () => {
    if (currentUser?.is_superuser) {
      await SkillsService.reloadSkills()
    }
  }

  if (skills.data.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center text-center py-12">
        <div className="rounded-full bg-muted p-4 mb-4">
          <Search className="h-8 w-8 text-muted-foreground" />
        </div>
        <h3 className="text-lg font-semibold">No skills found</h3>
        <p className="text-muted-foreground">
          Create or upload a skill to get started
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        {currentUser?.is_superuser && (
          <Button variant="outline" size="sm" onClick={handleReload}>
            <RefreshCw className="h-4 w-4 mr-2" />
            Reload
          </Button>
        )}
      </div>
      <DataTable columns={columns} data={skills.data} />
    </div>
  )
}

function Skills() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Skills</h1>
          <p className="text-muted-foreground">Manage your skill library</p>
        </div>
        <div className="flex gap-2">
          <UploadSkillZip />
          <AddSkill />
        </div>
      </div>
      <Suspense fallback={<PendingItems />}>
        <SkillsTable />
      </Suspense>
    </div>
  )
}
