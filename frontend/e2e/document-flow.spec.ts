import { expect, test } from "@playwright/test";
import path from "node:path";

const SAMPLES = path.resolve(import.meta.dirname, "../../samples");

test("register, upload a contract, review risks and ask a cited question", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`;

  // 1. Create a workspace
  await page.goto("/login");
  await page.getByRole("button", { name: "Create a workspace" }).click();
  await page.getByLabel("Organization").fill("E2E Logistics");
  await page.getByLabel("Your name").fill("Erin Tester");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("e2e-password-123");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page.getByText("No documents yet")).toBeVisible();

  // 2. Upload a document; it is processed by the background worker
  await page.getByRole("link", { name: "Documents" }).first().click();
  await expect(page.getByRole("heading", { name: "Documents", exact: true })).toBeVisible();
  await page
    .getByTestId("file-input")
    .setInputFiles(path.join(SAMPLES, "01-brightline-saas-subscription-agreement.md"));
  const row = page.getByRole("row", { name: /Master Subscription Agreement/ });
  await expect(row.getByText("ready")).toBeVisible({ timeout: 20_000 });

  // 3. Review extracted insights - every quote is verified against the source text
  await row.getByRole("link").first().click();
  await expect(page.getByRole("heading", { name: /Master Subscription Agreement/ })).toBeVisible();
  await expect(page.getByText("Automatic renewal", { exact: true })).toBeVisible();
  await expect(page.getByText("Brightline Software Inc.", { exact: true })).toBeVisible();
  await expect(page.getByText("Unverified quote")).toHaveCount(0);

  // 4. Ask a question scoped to this document and check the cited answer
  await page.getByLabel("Question").fill("How much notice is required to stop the renewal?");
  await page.getByRole("button", { name: "Ask" }).click();
  const answer = page.getByTestId("answer");
  await expect(answer).toContainText("90 days");
  await expect(answer.getByRole("button", { name: /section/ }).first()).toBeVisible();

  // 5. Deadlines: an auto-renewing contract (dates relative to today, so the test never goes stale)
  const fmt = (d: Date) => d.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
  const termEnd = new Date(Date.now() + 120 * 86_400_000);
  const contract = [
    "# Fleet Fuel Card Agreement",
    "",
    `This Agreement is entered into between Northwind Logistics Ltd. (the "Customer") and FuelNet Cards Inc. (the "Supplier").`,
    "",
    `1. Term. The initial term ends on ${fmt(termEnd)}. This Agreement will automatically renew for successive twelve (12) month terms unless either party gives 90 days' written notice of non-renewal.`,
    "",
    "2. Fees. The Customer shall pay a monthly fee of USD 900.00. Invoices are payable within 30 days.",
  ].join("\n");
  await page.getByRole("link", { name: "Documents" }).first().click();
  await page
    .getByTestId("file-input")
    .setInputFiles({ name: "fuel-card-agreement.md", mimeType: "text/markdown", buffer: Buffer.from(contract) });
  await expect(page.getByRole("row", { name: /Fleet Fuel Card Agreement/ }).getByText("ready")).toBeVisible({
    timeout: 20_000,
  });

  await page.getByRole("link", { name: "Deadlines" }).first().click();
  const cancelRow = page
    .getByTestId("deadline")
    .filter({ hasText: "Last day to cancel auto-renewal (90-day notice)" })
    .filter({ hasText: "Fleet Fuel Card Agreement" });
  await expect(cancelRow).toBeVisible();
  await expect(cancelRow).toContainText("In 30 days");
  await cancelRow.getByRole("button", { name: "Mark handled" }).click();
  await cancelRow.getByPlaceholder(/Note/).fill("Notice sent to FuelNet");
  await cancelRow.getByRole("button", { name: "Confirm" }).click();
  await expect(cancelRow).toHaveCount(0);
  await page.getByRole("tab", { name: "handled" }).click();
  await expect(page.getByText(/Notice sent to FuelNet/)).toBeVisible();

  // 6. Rulebook: a new company rule is applied to existing documents immediately
  await page.getByRole("link", { name: "Rulebook" }).first().click();
  await page.getByLabel("Rule name").fill("Notice period of 60 days or less");
  await page.getByRole("button", { name: "Add rule and check all documents" }).click();
  await expect(page.getByText("2 documents fail")).toBeVisible();

  // 7. Dashboard reflects deadlines and rulebook results
  await page.getByRole("link", { name: "Dashboard" }).first().click();
  await expect(page.getByText("Rulebook issues", { exact: true })).toBeVisible();
  await expect(page.getByText("Upcoming deadlines")).toBeVisible();
});

test("unauthenticated users are redirected to sign in", async ({ page }) => {
  await page.goto("/documents");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
});
