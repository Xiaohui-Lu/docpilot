// Capture portfolio screenshots of a running, freshly seeded DocPilot instance.
// Usage: node scripts/screenshots.mjs [baseUrl] [outDir]
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const base = process.argv[2] ?? "http://localhost:5173";
const out = path.resolve(process.argv[3] ?? "../docs/screenshots");
fs.mkdirSync(out, { recursive: true });

const browser = await chromium.launch({ channel: "chrome" });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
const page = await context.newPage();
const shot = async (name, opts = {}) => {
  await page.waitForTimeout(1600); // let charts finish animating
  const file = path.join(out, `${name}.png`);
  await page.screenshot({ path: file, ...opts });
  console.log("saved", file);
};
const nav = async (label, heading) => {
  await page.getByRole("link", { name: label, exact: true }).first().click();
  await page.getByRole("heading", { name: heading, exact: true, level: 1 }).waitFor();
};

await page.goto(`${base}/login`);
await shot("00-login");
await page.getByLabel("Email").fill("demo@docpilot.example.com");
await page.getByLabel("Password").fill("docpilot-demo");
await page.getByRole("button", { name: "Sign in" }).click();
await page.getByText("Portfolio dashboard").waitFor();
await shot("01-dashboard");

await nav("Deadlines", "Deadlines");
await page.getByTestId("deadline").first().waitFor();
await shot("02-deadlines");

await page
  .getByRole("button", { name: /contract deadlines in the next/ })
  .first()
  .click();
await page.frameLocator("iframe[title='Email preview']").getByText("Open all deadlines").waitFor();
await shot("03-email-digest");
await page.keyboard.press("Escape");

await nav("Rulebook", "Rulebook");
await page.getByText("Notice period of 60 days or less").waitFor();
await shot("04-rulebook");

await nav("Documents", "Documents");
await page.getByText("Master Subscription Agreement").first().waitFor();
await shot("05-documents");

await page.getByText("Master Subscription Agreement").first().click();
await page.getByText("Rulebook check").waitFor();
await shot("06-document-detail");
await page
  .getByText(/will automatically renew/)
  .first()
  .click();
await shot("06b-document-risks");

await nav("Ask AI", "Ask across all documents");
await page
  .getByLabel("Question")
  .fill("What is the monthly rent for the Kingsway office and how large is the security deposit?");
await page.getByRole("button", { name: "Ask" }).click();
await page.getByTestId("answer").waitFor();
await shot("07-ask");

await nav("Team & audit", "Team & audit log");
await shot("08-team-audit");

await browser.close();
