import { chromium } from "playwright";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

const tokenResp = await page.request.post(
  "http://localhost:28888/api/v1/login/access-token",
  { form: { username: "admin@example.com", password: "changethis" } },
);
const { access_token } = await tokenResp.json();
await page.goto("http://localhost:27777/login", { waitUntil: "load" });
await page.evaluate((tok) => localStorage.setItem("access_token", tok), access_token);

await page.goto("http://localhost:27777/item-handlers/288d27b5-82cf-41f2-90dd-f56a5300521e", { waitUntil: "networkidle" });
await page.waitForTimeout(2500);
console.log("errorComponent:", await page.evaluate(() => Boolean(document.querySelector('[data-testid="error-component"]'))));

const texts = await page.evaluate(() => (document.body.innerText || "").slice(0, 400));
console.log("textStart:", JSON.stringify(texts));

// open bound terminal (测试项目 4) fullscreen
await page.getByText("测试项目 4").first().click().catch(() => {});
await page.waitForTimeout(1200);
console.log("fullscreen:", await page.evaluate(() => Boolean(document.querySelector(".terminal-fullscreen"))));

// click WS feature -> zoom above fullscreen
await page.getByText("WebSocket Server").last().click().catch(() => {});
await page.waitForTimeout(1200);
const zoomVisible = await page.evaluate(() => {
  const el = document.querySelector(".zoom-card");
  if (!el) return { found: false };
  const r = el.getBoundingClientRect();
  const style = getComputedStyle(el);
  return { found: true, visible: r.width > 0 && style.display !== "none", zIndex: style.zIndex };
});
console.log("ws zoom:", JSON.stringify(zoomVisible));

await page.screenshot({ path: "board2.png", fullPage: false });
console.log("PAGEERRORS:", errors.join(" | ") || "(none)");
await browser.close();
