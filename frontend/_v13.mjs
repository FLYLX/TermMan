import { chromium } from "playwright";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
const t = await page.request.post("http://localhost:28888/api/v1/login/access-token", { form: { username: "admin@example.com", password: "changethis" } });
const { access_token } = await t.json();
await page.goto("http://localhost:27777/login", { waitUntil: "load" });
await page.evaluate((tok) => localStorage.setItem("access_token", tok), access_token);
await page.goto("http://localhost:27777/item-handlers/288d27b5-82cf-41f2-90dd-f56a5300521e", { waitUntil: "networkidle" });
await page.waitForTimeout(2500);
const m = await page.evaluate(() => {
  const q = (s) => { const el = document.querySelector(s); if (!el) return null; const r = el.getBoundingClientRect(); return { x: Math.round(r.x), right: Math.round(r.right), bottom: Math.round(r.bottom), w: Math.round(r.width) }; };
  const sections = [...document.querySelectorAll("section")];
  const right = sections[sections.length - 1];
  const termBox = right ? right.querySelector(".sketch-box, .sketch-tray") : null;
  return {
    winW: window.innerWidth, winH: window.innerHeight,
    rightSection: q("section:last-of-type") ? { right: Math.round(right.getBoundingClientRect().right) } : null,
    termBoxRight: termBox ? Math.round(termBox.getBoundingClientRect().right) : null,
    footer: q("footer"),
  };
});
console.log(JSON.stringify(m, null, 1));
await browser.close();
