import { createFileRoute } from "@tanstack/react-router"

import { KnowledgeFileManager } from "@/components/Knowledge/KnowledgeFileManager"

function KnowledgePage() {
  return <KnowledgeFileManager />
}

export const Route = createFileRoute("/_layout/knowledge")({
  component: KnowledgePage,
  head: () => ({
    meta: [
      {
        title: "Knowledge - TermPaws",
      },
    ],
  }),
})
