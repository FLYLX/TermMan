import { createFileRoute } from "@tanstack/react-router"

import { RobotDetail } from "@/components/Robots/RobotDetail"

function RobotDetailPage() {
  const { robotId } = Route.useParams()

  return <RobotDetail robotId={robotId} />
}

export const Route = createFileRoute("/_layout/robots/$robotId")({
  component: RobotDetailPage,
  head: () => ({
    meta: [
      {
        title: "Robot Detail - TermMan",
      },
    ],
  }),
})
