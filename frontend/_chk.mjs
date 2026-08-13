import { chromium } from "playwright";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
const t = await page.request.post("http://localhost:28888/api/v1/login/access-token", { form: { username: "admin@example.com", password: "changethis" } });
const { access_token } = await t.json();
await page.goto("http://localhost:27777/login", { waitUntil: "load" });
await page.evaluate((tok) => localStorage.setItem("access_token", tok), access_token);
await page.goto("http://localhost:27777/item-handlers/288d27b5-82cf-41f2-90dd-f56a5300521e", { waitUntil: "networkidle" });
await page.waitForTimeout(2500);
const info = await page.evaluate(() => {
  const wires = [...document.querySelectorAll(".board-wires path")].map(p => p.getAttribute("d").slice(0,40));
  // which terminals are bound: look for sketch-active / bound text
  const terms = [...document.querySelectorAll("section")].map(s=>s.innerText.slice(0,60));
  return { wireCount: wires.length, wires };
});
console.log(JSON.stringify(info, null, 1));
await browser.close();
