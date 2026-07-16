#!/usr/bin/env node
// GremlinBoard CLI — Node stdlib only, no runtime npm dependencies.
//
// Subcommands: start (default), stop, status, --help
//
// This file intentionally mirrors two pieces of Python behavior exactly:
//   - apps/api/gremlinboard_api/config.py `default_data_dir()` (data dir resolution)
//   - the packaged-mode startup guard in apps/api/gremlinboard_api/main.py
//     (GREMLINBOARD_WIDGETS_DIR must point at the bundled core widgets)

import { spawn, execFile } from "node:child_process";
import { promisify } from "node:util";
import net from "node:net";
import http from "node:http";
import fs from "node:fs";
import fsp from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const execFileAsync = promisify(execFile);

const API_PORT = 2555;
const WEB_PORT = 7555;

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
// bin/gremlinboard.mjs -> packaging/npm (the installed package root)
const pkgRoot = path.dirname(__dirname);

function readBuildInfo() {
  const buildInfoPath = path.join(pkgRoot, "build-info.json");
  try {
    return JSON.parse(fs.readFileSync(buildInfoPath, "utf-8"));
  } catch {
    return null;
  }
}

function readPackageVersion() {
  try {
    const pkg = JSON.parse(fs.readFileSync(path.join(pkgRoot, "package.json"), "utf-8"));
    return pkg.version ?? "0.0.0";
  } catch {
    return "0.0.0";
  }
}

// Mirrors default_data_dir() in apps/api/gremlinboard_api/config.py EXACTLY.
function defaultDataDir() {
  const envOverride = process.env.GREMLINBOARD_DATA_DIR;
  if (envOverride) {
    return envOverride;
  }
  if (process.platform === "win32") {
    const base = process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local");
    return path.join(base, "GremlinBoard");
  }
  if (process.platform === "darwin") {
    return path.join(os.homedir(), "Library", "Application Support", "GremlinBoard");
  }
  const xdgDataHome = process.env.XDG_DATA_HOME;
  const base = xdgDataHome ? xdgDataHome : path.join(os.homedir(), ".local", "share");
  return path.join(base, "gremlinboard");
}

const dataDir = defaultDataDir();
const runtimeDir = path.join(dataDir, "runtime");
const venvDir = path.join(runtimeDir, "venv");
const installedVersionFile = path.join(runtimeDir, "installed-version.txt");
const launcherDir = path.join(dataDir, "launcher");
const instancesFile = path.join(launcherDir, "npm-instances.json");
const apiLogFile = path.join(launcherDir, "npm-api.log");
const webLogFile = path.join(launcherDir, "npm-web.log");

function venvPythonPath() {
  if (process.platform === "win32") {
    return path.join(venvDir, "Scripts", "python.exe");
  }
  return path.join(venvDir, "bin", "python");
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function log(message) {
  process.stdout.write(`${message}\n`);
}

function err(message) {
  process.stderr.write(`${message}\n`);
}

async function ensureDir(dir) {
  await fsp.mkdir(dir, { recursive: true });
}

function checkPortListening(port, host = "127.0.0.1", timeoutMs = 300) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolve(result);
    };
    socket.setTimeout(timeoutMs);
    socket.once("connect", () => finish(true));
    socket.once("timeout", () => finish(false));
    socket.once("error", () => finish(false));
    socket.connect(port, host);
  });
}

function httpProbe(url, timeoutMs = 1500) {
  return new Promise((resolve) => {
    const request = http.get(url, { timeout: timeoutMs }, (res) => {
      res.resume();
      resolve(res.statusCode !== undefined && res.statusCode < 500);
    });
    request.on("error", () => resolve(false));
    request.on("timeout", () => {
      request.destroy();
      resolve(false);
    });
  });
}

async function waitFor(predicate, timeoutMs, intervalMs = 1000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await predicate()) {
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  return false;
}

function isProcessAlive(pid) {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function readInstances() {
  try {
    const raw = await fsp.readFile(instancesFile, "utf-8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

async function writeInstances(data) {
  await ensureDir(launcherDir);
  await fsp.writeFile(instancesFile, JSON.stringify(data, null, 2), "utf-8");
}

async function clearInstances() {
  try {
    await fsp.unlink(instancesFile);
  } catch {
    // already gone
  }
}

// ---------------------------------------------------------------------------
// Python discovery
// ---------------------------------------------------------------------------

const PYTHON_INSTALL_HINT = `Python 3.12+ is required but was not found on PATH.

Install it with one of:
  Windows:  winget install Python.Python.3.12
  macOS:    brew install python@3.12
  Linux:    sudo apt install python3.12 python3.12-venv

Then re-run this command.`;

function parsePythonVersion(versionOutput) {
  const match = versionOutput.match(/Python\s+(\d+)\.(\d+)\.(\d+)/i);
  if (!match) return null;
  return { major: Number(match[1]), minor: Number(match[2]), patch: Number(match[3]) };
}

async function tryPythonCandidate(command, args) {
  try {
    const { stdout, stderr } = await execFileAsync(command, [...args, "--version"], { timeout: 5000 });
    const versionText = `${stdout}${stderr}`.trim();
    const version = parsePythonVersion(versionText);
    if (!version) return null;
    if (version.major > 3 || (version.major === 3 && version.minor >= 12)) {
      return { command, args, version, versionText };
    }
    return null;
  } catch {
    return null;
  }
}

async function findSystemPython() {
  const candidates =
    process.platform === "win32"
      ? [
          ["py", ["-3.12"]],
          ["python3.12", []],
          ["python3", []],
          ["python", []],
        ]
      : [
          ["python3.12", []],
          ["python3", []],
          ["python", []],
        ];

  for (const [command, args] of candidates) {
    const found = await tryPythonCandidate(command, args);
    if (found) return found;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Venv bootstrap + wheel install
// ---------------------------------------------------------------------------

function runCommand(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: "inherit", ...options });
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${command} ${args.join(" ")} exited with code ${code}`));
    });
  });
}

async function ensureVenv() {
  const venvPython = venvPythonPath();
  if (fs.existsSync(venvPython)) {
    return venvPython;
  }

  const python = await findSystemPython();
  if (!python) {
    err(PYTHON_INSTALL_HINT);
    process.exit(1);
  }

  log(`Python found: ${python.versionText} (${python.command})`);
  log(`Creating virtual environment at ${venvDir} ...`);
  await ensureDir(runtimeDir);
  await runCommand(python.command, [...python.args, "-m", "venv", venvDir]);

  if (!fs.existsSync(venvPython)) {
    err(`Virtual environment creation appeared to succeed but ${venvPython} is missing.`);
    process.exit(1);
  }
  return venvPython;
}

function findWheelFile() {
  const wheelsDir = path.join(pkgRoot, "wheels");
  if (!fs.existsSync(wheelsDir)) return null;
  const entries = fs.readdirSync(wheelsDir).filter((name) => name.endsWith(".whl"));
  if (entries.length === 0) return null;
  return path.join(wheelsDir, entries[0]);
}

async function ensureApiInstalled(venvPython) {
  const buildInfo = readBuildInfo();
  const packageVersion = buildInfo?.version ?? readPackageVersion();

  let installedVersion = null;
  try {
    installedVersion = (await fsp.readFile(installedVersionFile, "utf-8")).trim();
  } catch {
    installedVersion = null;
  }

  if (installedVersion === packageVersion) {
    return;
  }

  const wheel = findWheelFile();
  if (!wheel) {
    err(`No bundled wheel found under ${path.join(pkgRoot, "wheels")}. The npm package may be corrupt.`);
    process.exit(1);
  }

  log("Installing GremlinBoard API runtime (first run needs network access to fetch dependencies from PyPI)...");
  await runCommand(venvPython, ["-m", "pip", "install", "--upgrade", wheel]);

  await ensureDir(runtimeDir);
  await fsp.writeFile(installedVersionFile, packageVersion, "utf-8");
  log(`Installed gremlinboard-api ${packageVersion}.`);
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

function printHelp() {
  log(`gremlinboard — run the full GremlinBoard stack locally

Usage:
  gremlinboard [start]   Start the API (port ${API_PORT}) and web (port ${WEB_PORT}) servers
  gremlinboard stop      Stop a running managed instance
  gremlinboard status    Show whether GremlinBoard is running
  gremlinboard --help    Show this message

Data directory: ${dataDir}
(override with GREMLINBOARD_DATA_DIR)`);
}

async function cmdStart() {
  // Port check FIRST: fast, side-effect-free refusal before any venv/pip work.
  const [apiPortBusy, webPortBusy] = await Promise.all([
    checkPortListening(API_PORT),
    checkPortListening(WEB_PORT),
  ]);
  if (apiPortBusy || webPortBusy) {
    const busy = [];
    if (apiPortBusy) busy.push(API_PORT);
    if (webPortBusy) busy.push(WEB_PORT);
    err(
      `Cannot start: port${busy.length > 1 ? "s" : ""} ${busy.join(", ")} already in use.\n` +
        `Another GremlinBoard instance (or something else) is already listening. ` +
        `Run "gremlinboard stop" if you started it with this CLI, or free the port(s) yourself.`,
    );
    process.exit(1);
  }

  const venvPython = await ensureVenv();
  await ensureApiInstalled(venvPython);

  const widgetsDir = path.join(pkgRoot, "widgets");
  if (!fs.existsSync(widgetsDir)) {
    err(`Bundled widgets directory not found at ${widgetsDir}. The npm package may be corrupt.`);
    process.exit(1);
  }
  const webServerPath = path.join(pkgRoot, "web", "server.js");
  if (!fs.existsSync(webServerPath)) {
    err(`Bundled web server not found at ${webServerPath}. The npm package may be corrupt.`);
    process.exit(1);
  }

  await ensureDir(launcherDir);
  const apiLog = fs.openSync(apiLogFile, "a");
  const webLog = fs.openSync(webLogFile, "a");

  log(`Starting GremlinBoard API on 127.0.0.1:${API_PORT} ...`);
  const apiProcess = spawn(
    venvPython,
    ["-m", "uvicorn", "gremlinboard_api.main:app", "--host", "127.0.0.1", "--port", String(API_PORT), "--no-access-log"],
    {
      detached: true,
      windowsHide: true,
      stdio: ["ignore", apiLog, apiLog],
      env: { ...process.env, GREMLINBOARD_WIDGETS_DIR: widgetsDir },
    },
  );
  apiProcess.unref();

  log(`Starting GremlinBoard web on 127.0.0.1:${WEB_PORT} ...`);
  const webProcess = spawn(process.execPath, [webServerPath], {
    detached: true,
    windowsHide: true,
    stdio: ["ignore", webLog, webLog],
    cwd: path.dirname(webServerPath),
    env: { ...process.env, PORT: String(WEB_PORT), HOSTNAME: "127.0.0.1" },
  });
  webProcess.unref();

  const packageVersion = readBuildInfo()?.version ?? readPackageVersion();
  await writeInstances({
    apiPid: apiProcess.pid,
    webPid: webProcess.pid,
    startedAt: new Date().toISOString(),
    version: packageVersion,
  });

  const apiHealthy = await waitFor(() => httpProbe(`http://127.0.0.1:${API_PORT}/api/health`), 60000);
  const webHealthy = apiHealthy && (await waitFor(() => httpProbe(`http://127.0.0.1:${WEB_PORT}`), 60000));

  if (!apiHealthy || !webHealthy) {
    err("GremlinBoard failed to become healthy within 60 seconds.");
    err(`API log: ${apiLogFile}`);
    err(`Web log: ${webLogFile}`);
    await killProcessTree(apiProcess.pid);
    await killProcessTree(webProcess.pid);
    await clearInstances();
    process.exit(1);
  }

  log("");
  log("GremlinBoard is running:");
  log(`  Board:  http://127.0.0.1:${WEB_PORT}`);
  log(`  System: http://127.0.0.1:${WEB_PORT}/system`);
  log(`  Studio: http://127.0.0.1:${WEB_PORT}/studio`);
  log(`  API:    http://127.0.0.1:${API_PORT}/api`);
  log("");
  log(`Logs: ${apiLogFile}, ${webLogFile}`);
  log('Run "gremlinboard stop" to shut it down.');
}

async function killProcessTree(pid) {
  if (!pid) return;
  if (process.platform === "win32") {
    await new Promise((resolve) => {
      execFile("taskkill", ["/PID", String(pid), "/T", "/F"], () => resolve());
    });
    return;
  }
  try {
    process.kill(-pid, "SIGKILL");
  } catch {
    try {
      process.kill(pid, "SIGKILL");
    } catch {
      // already dead
    }
  }
}

async function cmdStop() {
  const instances = await readInstances();
  if (!instances) {
    log("GremlinBoard is not running (no tracked instance found).");
    return;
  }

  const { apiPid, webPid } = instances;
  const apiWasAlive = isProcessAlive(apiPid);
  const webWasAlive = isProcessAlive(webPid);

  if (!apiWasAlive && !webWasAlive) {
    log("Tracked GremlinBoard processes were already stopped.");
    await clearInstances();
    return;
  }

  log("Stopping GremlinBoard...");
  await killProcessTree(apiPid);
  await killProcessTree(webPid);
  await clearInstances();
  log("Stopped.");
}

async function cmdStatus() {
  const instances = await readInstances();

  if (!instances) {
    // Nothing tracked for this data dir. Ports are fixed and global, so a
    // process might still be listening on 2555/7555 — but it belongs to a
    // different data dir / different launcher, not to this one. Report
    // "not running" from this data dir's point of view rather than
    // attributing someone else's stack to it.
    log("GremlinBoard status: not running");
    log("");
    log(`Data directory: ${dataDir}`);
    log("(no tracked instance found for this data directory)");
    return;
  }

  const apiPid = instances.apiPid ?? null;
  const webPid = instances.webPid ?? null;
  const apiPidAlive = isProcessAlive(apiPid);
  const webPidAlive = isProcessAlive(webPid);

  const [apiHealthy, webHealthy] = await Promise.all([
    httpProbe(`http://127.0.0.1:${API_PORT}/api/health`),
    httpProbe(`http://127.0.0.1:${WEB_PORT}`),
  ]);

  const running = apiPidAlive || webPidAlive;

  log(`GremlinBoard status: ${running ? "running" : "not running"}`);
  log("");
  log(`  Component  PID        Process   Health`);
  log(`  API        ${String(apiPid ?? "-").padEnd(10)} ${(apiPidAlive ? "alive" : "down").padEnd(9)} ${apiHealthy ? "ok" : "unreachable"}`);
  log(`  Web        ${String(webPid ?? "-").padEnd(10)} ${(webPidAlive ? "alive" : "down").padEnd(9)} ${webHealthy ? "ok" : "unreachable"}`);
  log("");
  log(`Data directory: ${dataDir}`);
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

async function main() {
  const args = process.argv.slice(2);
  const command = args[0];

  if (command === "--help" || command === "-h" || command === "help") {
    printHelp();
    return;
  }

  if (command === "stop") {
    await cmdStop();
    return;
  }

  if (command === "status") {
    await cmdStatus();
    return;
  }

  if (command === undefined || command === "start") {
    await cmdStart();
    return;
  }

  err(`Unknown command: ${command}`);
  printHelp();
  process.exit(1);
}

main().catch((error) => {
  err(`GremlinBoard CLI error: ${error?.stack ?? error}`);
  process.exit(1);
});
