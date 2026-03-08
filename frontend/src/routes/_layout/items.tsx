import { createFileRoute, Outlet } from "@tanstack/react-router"

export const Route = createFileRoute("/_layout/items")({
  component: ItemsLayout,
})

function ItemsLayout() {
  return <Outlet />
}
