import { defineConfig, devices } from "@playwright/test";

// End-to-end: the real FastAPI backend (mock LLM, real sandbox + verification gate) and the
// production Next.js build. Run from frontend/: `npx playwright test`.
const API_PORT = 8765;
const WEB_PORT = 3100;
const API_KEY = "e2e-test-key";

export default defineConfig({
  testDir: "./e2e",
  timeout: 240_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
    // RECORD=1 records the run (used to make the README demo GIF).
    video: process.env.RECORD ? { mode: "on", size: { width: 1440, height: 1000 } } : "off",
    viewport: { width: 1440, height: 1000 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } }],
  webServer: [
    {
      // Repo root: in-memory checkpoints/events, mock LLM, real sandbox tools.
      command: `uv run polymath serve --port ${API_PORT} --memory --mock-llm`,
      cwd: "..",
      url: `http://localhost:${API_PORT}/health`,
      env: { POLYMATH_API_KEY: API_KEY, POLYMATH_NO_DOTENV: "1", LITELLM_MODE: "PRODUCTION" },
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npm run build && npx next start -p ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}`,
      env: { POLYMATH_API_URL: `http://localhost:${API_PORT}`, POLYMATH_API_KEY: API_KEY },
      reuseExistingServer: false,
      timeout: 300_000,
    },
  ],
});
