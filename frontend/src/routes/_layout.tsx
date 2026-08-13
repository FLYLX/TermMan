import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"
import { useLocation } from "@tanstack/react-router"

import { HangTagNav } from "@/components/Layout/HangTagNav"
import { isLoggedIn } from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({
        to: "/login",
      })
    }
  },
})

const HANG_LAYOUT_CSS = `
.hang-layout { min-height: 100svh; background: #f4f4f3; color: #1f1f1f; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.tag-rail { position: relative; display: flex; align-items: flex-start; justify-content: center; gap: 14px; padding: 14px 96px 8px; background: linear-gradient(180deg, #f7f7f6 0%, #f1f1f0 55%, rgba(244,244,243,0) 100%); }
.tag-rail-line { position: absolute; top: 8px; left: 0; right: 0; height: 2px; background: #555; }
.tag-user-anchor { position: absolute; right: 20px; top: 36px; }
.hang-tag { position: relative; margin-top: 0; transform-origin: top center; transform: translateY(calc(-100% + 12px)); border: 2px solid #3a3a3a; border-top: none; background: #fff; color: #242424; padding: 18px 14px 9px; font-weight: 700; font-size: 12px; line-height: 1.2; display: flex; flex-direction: column; align-items: center; gap: 4px; box-shadow: 3px 4px 0 rgba(0,0,0,.10); border-radius: 0 0 18px 18px; cursor: pointer; transition: transform .3s cubic-bezier(.2,.8,.3,1), box-shadow .18s ease, background .18s ease; }
.hang-tag::before { content: ""; position: absolute; bottom: 100%; left: 50%; width: 2px; height: 60px; background: #555; }
.tag-hole { position: absolute; top: 5px; left: 50%; margin-left: -5px; width: 10px; height: 10px; border: 2px solid #3a3a3a; border-radius: 9999px; background: #f4f4f3; }
.hang-tag:hover { transform: translateY(calc(-50% + 6px)) rotate(0deg); background: #fbfbfa; box-shadow: 4px 6px 0 rgba(0,0,0,.14); }
.hang-tag-active, .hang-tag-active:hover { transform: translateY(0) rotate(0deg); background: #e9e9e6; box-shadow: 4px 7px 0 rgba(0,0,0,.18); }
.tag-user-menu { position: absolute; right: 0; top: calc(100% + 10px); z-index: 60; width: 220px; background: #fff; border: 2px solid #3a3a3a; border-radius: 12px; box-shadow: 4px 5px 0 rgba(0,0,0,.12); padding: 10px; animation: tag-pop .16s ease-out; }
@keyframes tag-pop { from { transform: translateY(-6px) scale(.96); opacity: 0; } to { transform: none; opacity: 1; } }
.sketch-mini-box { border: 2px solid #3a3a3a; border-radius: 10px; background: #fff; font-weight: 700; font-size: 12px; }
.hang-page { padding: 6px 18px 14px; animation: page-drop .3s cubic-bezier(.2,.8,.3,1); }
@keyframes page-drop { from { transform: translateY(-22px); opacity: 0; } to { transform: none; opacity: 1; } }
.hang-page .rounded-lg, .hang-page .rounded-xl, .hang-page .rounded-md { border-radius: 16px 205px 16px 205px / 205px 16px 205px 16px; }
.hang-page .rounded-full { border-radius: 9999px; }
.hang-page .border { border-color: #3d3d3d; }
.hang-page .border-t, .hang-page .border-b, .hang-page .border-l, .hang-page .border-r { border-color: #3d3d3d; }
.hang-page .shadow-sm { box-shadow: 2px 3px 0 rgba(0,0,0,.08); }
.hang-page .shadow, .hang-page .shadow-md { box-shadow: 3px 4px 0 rgba(0,0,0,.12); }
.hang-page .bg-card, .hang-page .bg-background, .hang-page .bg-accent\\/30 { background-color: #fff; }
.hang-page .bg-muted { background-color: #ececea; }
.hang-page .text-muted-foreground { color: #565654; }
.hang-page .text-foreground { color: #1f1f1f; }
.hang-page button, .hang-page [role="button"] { font-weight: 600; }
.hang-page input:not(.code-editor), .hang-page select { color: #1f1f1f; }
.hang-page textarea:not(.code-editor) { color: #1f1f1f; }
`

function Layout() {
  const location = useLocation()

  return (
    <div className="hang-layout">
      <style>{HANG_LAYOUT_CSS}</style>
      <HangTagNav />
      <main key={location.pathname} className="hang-page">
        <Outlet />
      </main>
    </div>
  )
}

export default Layout
