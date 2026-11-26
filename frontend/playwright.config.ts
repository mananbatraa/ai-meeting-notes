import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { defineConfig, devices } from "@playwright/test";

// End-to-end tests run the real backend (FastAPI, SQLite, job queue) in offline demo
// mode, so no Whisper model or API key is needed, behind the real Vite dev server.
const API_PORT = Number(process.env.E2E_API_PORT ?? 8765);
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 5175);
const dataDir = process.env.E2E_DATA_DIR ?? mkdtempSync(join(tmpdir(), "amn-e2e-"));

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  timeout: 30_000,
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port ${API_PORT}`,
      cwd: "../backend",
      url: `http://127.0.0.1:${API_PORT}/healthz`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        AMN_EXTRACTOR: "fake",
        AMN_TRANSCRIBER: "fake",
        AMN_DATABASE_URL: `sqlite:///${join(dataDir, "meetings.db")}`,
        AMN_UPLOAD_DIR: join(dataDir, "uploads"),
        AMN_CORS_ORIGINS: `["http://127.0.0.1:${WEB_PORT}"]`,
      },
    },
    {
      command: `npx vite --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: { VITE_API_PROXY: `http://127.0.0.1:${API_PORT}` },
    },
  ],
});
