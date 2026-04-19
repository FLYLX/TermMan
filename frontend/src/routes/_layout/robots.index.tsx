import { createFileRoute } from "@tanstack/react-router"

import { RobotManager } from "@/components/Robots/RobotManager"

function RobotsPage() {
  return <RobotManager />
}

export const Route = createFileRoute("/_layout/robots/")({
  component: RobotsPage,
  head: () => ({
    meta: [
      {
        title: "Robots - TermMan",
      },
    ],
  }),
})
