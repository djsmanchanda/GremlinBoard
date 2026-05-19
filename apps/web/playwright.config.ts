import { defineConfig, devices } from "@playwright/test";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";

const configDir = __dirname;
const repoRoot = resolve(configDir, "../..");

const startManagedWebServer =
  process.env.PLAYWRIGHT_SKIP_WEBSERVER !== "1" && (Boolean(process.env.CI) || process.env.PLAYWRIGHT_START_WEBSERVER === "1");
const webPort = Number(process.env.GREMLINBOARD_E2E_WEB_PORT ?? (startManagedWebServer ? 3100 : 3000));
const apiPort = Number(process.env.GREMLINBOARD_E2E_API_PORT ?? 8000);
const webBaseURL = process.env.GREMLINBOARD_WEB_URL ?? process.env.PLAYWRIGHT_BASE_URL ?? `http://127.0.0.1:${webPort}`;
const apiBaseURL = process.env.NEXT_PUBLIC_GREMLINBOARD_API_URL ?? `http://127.0.0.1:${apiPort}/api`;
const e2eDatabasePath = join(repoRoot, "data", "gremlinboard-e2e.db").replace(/\\/g, "/");

function findSystemBrowserChannel() {
  if (process.env.CI || process.env.PLAYWRIGHT_DISABLE_SYSTEM_BROWSER_FALLBACK === "1") {
    return undefined;
  }

  const localAppData = process.env.LOCALAPPDATA;
  const programFiles = process.env.ProgramFiles;
  const programFilesX86 = process.env["ProgramFiles(x86)"];
  const candidates =
    process.platform === "win32"
      ? [
          { channel: "chrome", path: localAppData ? join(localAppData, "Google/Chrome/Application/chrome.exe") : "" },
          { channel: "chrome", path: programFiles ? join(programFiles, "Google/Chrome/Application/chrome.exe") : "" },
          { channel: "chrome", path: programFilesX86 ? join(programFilesX86, "Google/Chrome/Application/chrome.exe") : "" },
          { channel: "msedge", path: programFiles ? join(programFiles, "Microsoft/Edge/Application/msedge.exe") : "" },
          { channel: "msedge", path: programFilesX86 ? join(programFilesX86, "Microsoft/Edge/Application/msedge.exe") : "" },
        ]
      : [
          { channel: "chrome", path: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" },
          { channel: "msedge", path: "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" },
          { channel: "chrome", path: "/usr/bin/google-chrome" },
          { channel: "chrome", path: "/usr/bin/google-chrome-stable" },
          { channel: "msedge", path: "/usr/bin/microsoft-edge" },
        ];

  return candidates.find((candidate) => candidate.path && existsSync(candidate.path))?.channel;
}

const browserChannel = process.env.PLAYWRIGHT_CHANNEL ?? process.env.PLAYWRIGHT_BROWSER_CHANNEL ?? findSystemBrowserChannel();
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;

export default defineConfig({
  testDir: "./tests",
  outputDir: "./test-results/playwright",
  timeout: 30_000,
  expect: {
    timeout: 8_000,
  },
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    ...devices["Desktop Chrome"],
    baseURL: webBaseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: process.env.PLAYWRIGHT_RECORD_VIDEO === "1" ? "retain-on-failure" : "off",
    colorScheme: "dark",
    ...(browserChannel ? { channel: browserChannel } : {}),
    ...(executablePath ? { launchOptions: { executablePath } } : {}),
  },
  projects: [
    {
      name: browserChannel ? `chromium-${browserChannel}` : "chromium",
    },
  ],
  webServer:
    !startManagedWebServer
      ? undefined
      : [
          {
            command: `python -m uvicorn --app-dir apps/api gremlinboard_api.main:app --host 127.0.0.1 --port ${apiPort}`,
            cwd: repoRoot,
            url: `${apiBaseURL}/health`,
            reuseExistingServer: !process.env.CI,
            timeout: 120_000,
            env: {
              GREMLINBOARD_DATABASE_URL: `sqlite+aiosqlite:///${e2eDatabasePath}`,
              GREMLINBOARD_WEB_ORIGIN: webBaseURL,
            },
          },
          {
            command: `node ../../node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port ${webPort}`,
            cwd: configDir,
            url: webBaseURL,
            reuseExistingServer: !process.env.CI,
            timeout: 120_000,
            env: {
              NEXT_PUBLIC_GREMLINBOARD_API_URL: apiBaseURL,
            },
          },
        ],
});
