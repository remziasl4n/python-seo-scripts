import { defineConfig } from "@playwright/test";

/**
 * Browser tests against the real API and web app, in your installed Chrome (no browser
 * download). They use their own database and ports, so your run history and a running
 * `seo dev` are untouched. Run with: pnpm e2e
 */
const API_PORT = 8100;
const WEB_PORT = 3100;

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: "list",
  use: { baseURL: `http://127.0.0.1:${WEB_PORT}`, channel: "chrome", headless: true },
  webServer: [
    {
      command: `uv run seo db setup && uv run seo api --port ${API_PORT} --no-reload`,
      cwd: "..",
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      env: { DATABASE_URL: "postgresql+psycopg:///seo_toolkit_e2e" },
      timeout: 60_000,
      reuseExistingServer: false,
    },
    {
      command: "corepack pnpm dev",
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: {
        PORT: String(WEB_PORT),
        SEO_API_URL: `http://127.0.0.1:${API_PORT}`,
        NEXT_DIST_DIR: ".next-e2e", // separate from `seo dev`'s .next, which Next locks
        COREPACK_ENABLE_DOWNLOAD_PROMPT: "0",
      },
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
});
