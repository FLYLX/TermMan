import { createFileRoute, Outlet } from "@tanstack/react-router"

export const Route = createFileRoute("/_layout/robots")({
  component: RobotsLayout,
})

function RobotsLayout() {
  return <Outlet />
}
