// Render a local HTML file to PNG: node scripts/render-html.mjs <in.html> <out.png> [width] [height]
import { chromium } from "@playwright/test";
import path from "node:path";
import { pathToFileURL } from "node:url";

const [input, output, width = "1600", height = "1200"] = process.argv.slice(2);
const browser = await chromium.launch({ channel: "chrome" });
const page = await browser.newPage({
  viewport: { width: Number(width), height: Number(height) },
  deviceScaleFactor: 1,
});
await page.goto(pathToFileURL(path.resolve(input)).href);
await page.waitForLoadState("networkidle");
await page.screenshot({ path: output });
await browser.close();
console.log("rendered", output);
