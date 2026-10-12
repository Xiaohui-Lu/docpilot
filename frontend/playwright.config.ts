import { defineConfig, devices } from "@playwright/test";

// The E2E suite boots its own backend (fresh SQLite DB, offline demo model) and Vite dev server on
// separate ports, so it never touches your local data and needs no API key.
const API_PORT = 8011;
const WEB_PORT = 5181;
const python =
  process.env.E2E_PYTHON ?? (process.platform === "win32" ? "..\\backend\\.venv\\Scripts\\python.exe" : "python");
const dbFile = `e2e-${Date.now()}.db`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], ...(process.env.CI ? {} : { channel: "chrome" }) },
    },
  ],
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --port ${API_PORT}`,
      cwd: "../backend",
      url: `http://localhost:${API_PORT}/healthz`,
      env: {
        DOCPILOT_DATABASE_URL: `sqlite:///./${dbFile}`,
        DOCPILOT_LLM_PROVIDER: "demo",
        DOCPILOT_WORKER_POLL_SECONDS: "0.3",
        DOCPILOT_CORS_ORIGINS: `http://localhost:${WEB_PORT}`,
      },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npx vite --port ${WEB_PORT} --strictPort`,
      url: `http://localhost:${WEB_PORT}`,
      env: { VITE_API_PROXY: `http://localhost:${API_PORT}` },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
