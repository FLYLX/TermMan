import { createFileRoute, Outlet } from "@tanstack/react-router"

export const Route = createFileRoute("/_layout/item-handlers")({
  component: ItemHandlersLayout,
})

function ItemHandlersLayout() {
  return <Outlet />
}
