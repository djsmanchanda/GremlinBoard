#!/usr/bin/env node
// Assembles packaging/npm into an installable "gremlinboard" npm package.
//
// Run from the repo root: `node scripts/build-npm-package.mjs`
// (also exposed as `npm run build:npm`)
//
// Steps:
//   1. Clean packaging/npm/{web,wheels,widgets,build-info.json}
//   2. Build the web app (`npm run build`)
//   3. Normalize the Next standalone output into packaging/npm/web so that
//      `web/server.js` is a stable entrypoint
//   4. Build the gremlinboard-api wheel into packaging/npm/wheels
//   5. Copy the core widget packages into packaging/npm/widgets
//   6. Write packaging/npm/build-info.json
//   7. `npm pack` inside packaging/npm

import { execFile, spawn } from "node:child_process";
import { promisify } from "node:util";
import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const execFileAsync = promisify(execFile);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.dirname(__dirname);
const npmPkgDir = path.join(repoRoot, "packaging", "npm");
const webAppDir = path.join(repoRoot, "apps", "web");
const apiDir = path.join(repoRoot, "apps", "api");
const widgetsSrcDir = path.join(repoRoot, "widgets");

const CORE_WIDGETS = ["agent_overview", "countdown", "news", "pinboard", "sports", "trending"];

function log(message) {
  process.stdout.write(`[build-npm-package] ${message}\n`);
}

function runCommand(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    log(`$ ${command} ${args.join(" ")}`);
    const child = spawn(command, args, { stdio: "inherit", shell: process.platform === "win32", ...options });
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${command} ${args.join(" ")} exited with code ${code}`));
    });
  });
}

async function rmrf(target) {
  await fsp.rm(target, { recursive: true, force: true });
}

async function copyDir(src, dest) {
  await fsp.cp(src, dest, { recursive: true });
}

// ---------------------------------------------------------------------------
// Step 1: clean
// ---------------------------------------------------------------------------

async function cleanOutputs() {
  log("Cleaning previous build outputs...");
  await rmrf(path.join(npmPkgDir, "web"));
  await rmrf(path.join(npmPkgDir, "wheels"));
  await rmrf(path.join(npmPkgDir, "widgets"));
  await rmrf(path.join(npmPkgDir, "build-info.json"));
}

// ---------------------------------------------------------------------------
// Step 2: build web
// ---------------------------------------------------------------------------

async function buildWeb() {
  log("Building web app (npm run build)...");
  // Deliberately do not set NEXT_PUBLIC_GREMLINBOARD_API_URL so the baked
  // default in apps/web/lib/constants.ts (http://127.0.0.1:2555/api) applies.
  const env = { ...process.env };
  delete env.NEXT_PUBLIC_GREMLINBOARD_API_URL;
  await runCommand(npmCmd(), ["run", "build"], { cwd: repoRoot, env });
}

function npmCmd() {
  return process.platform === "win32" ? "npm.cmd" : "npm";
}

// ---------------------------------------------------------------------------
// Step 3: normalize standalone output
// ---------------------------------------------------------------------------

async function normalizeWebOutput() {
  const standaloneDir = path.join(webAppDir, ".next", "standalone");
  if (!fs.existsSync(standaloneDir)) {
    throw new Error(`Expected standalone output at ${standaloneDir} — did the Next build produce output: "standalone"?`);
  }

  const destWebDir = path.join(npmPkgDir, "web");
  log(`Copying standalone output ${standaloneDir} -> ${destWebDir} ...`);
  await copyDir(standaloneDir, destWebDir);

  // Standalone output does not include .next/static or public/ (Next's own
  // docs call this out) — copy them into the app's directory inside the
  // standalone tree ourselves. Find where server.js actually landed rather
  // than assuming apps/web/server.js, so a workspace layout change doesn't
  // silently break the build.
  const serverJsPath = await findServerJs(destWebDir);
  if (!serverJsPath) {
    throw new Error(`Could not locate server.js anywhere under ${destWebDir} after copying the standalone output.`);
  }
  const appDirInStandalone = path.dirname(serverJsPath);
  const relAppDir = path.relative(destWebDir, appDirInStandalone);
  log(`Found standalone server.js at web/${path.relative(destWebDir, serverJsPath)}`);

  const staticSrc = path.join(webAppDir, ".next", "static");
  if (fs.existsSync(staticSrc)) {
    const staticDest = path.join(appDirInStandalone, ".next", "static");
    await copyDir(staticSrc, staticDest);
    log(`Copied .next/static -> web/${path.relative(destWebDir, staticDest)}`);
  }

  const publicSrc = path.join(webAppDir, "public");
  if (fs.existsSync(publicSrc)) {
    const publicDest = path.join(appDirInStandalone, "public");
    await copyDir(publicSrc, publicDest);
    log(`Copied public/ -> web/${path.relative(destWebDir, publicDest)}`);
  }

  // Normalize the entrypoint: web/server.js must exist regardless of where
  // the workspace layout put the real standalone server.js. Next's generated
  // server.js resolves all its paths from its own __dirname (it even calls
  // process.chdir(__dirname) on startup), so a plain `require()` shim from a
  // different directory is safe — verified by running it end to end.
  const stableEntry = path.join(destWebDir, "server.js");
  if (relAppDir === ".") {
    // server.js already lands at web/server.js; nothing to normalize.
  } else {
    const requireTarget = "./" + path.relative(destWebDir, serverJsPath).split(path.sep).join("/");
    const shim = `require(${JSON.stringify(requireTarget)});\n`;
    await fsp.writeFile(stableEntry, shim, "utf-8");
    log(`Wrote normalization shim web/server.js -> ${requireTarget}`);
  }

  if (!fs.existsSync(stableEntry)) {
    throw new Error(`Normalization failed: ${stableEntry} does not exist.`);
  }
}

async function findServerJs(rootDir) {
  // Prefer the conventional workspace path if present.
  const conventional = path.join(rootDir, "apps", "web", "server.js");
  if (fs.existsSync(conventional)) return conventional;

  // Otherwise search shallowly (standalone output is not deep).
  const stack = [rootDir];
  while (stack.length > 0) {
    const dir = stack.pop();
    let entries;
    try {
      entries = await fsp.readdir(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      if (entry.name === "node_modules") continue;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        stack.push(full);
      } else if (entry.name === "server.js") {
        return full;
      }
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Step 4: build the wheel
// ---------------------------------------------------------------------------

async function findBuildPython() {
  const candidates =
    process.platform === "win32"
      ? [
          ["C:\\Users\\djsma\\micromamba\\envs\\gremlinboard\\python.exe", []],
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
    try {
      const { stdout, stderr } = await execFileAsync(command, [...args, "--version"], { timeout: 5000 });
      const versionText = `${stdout}${stderr}`.trim();
      const match = versionText.match(/Python\s+(\d+)\.(\d+)/i);
      if (!match) continue;
      const major = Number(match[1]);
      const minor = Number(match[2]);
      if (major > 3 || (major === 3 && minor >= 12)) {
        log(`Using Python for wheel build: ${versionText} (${command} ${args.join(" ")})`.trim());
        return { command, args };
      }
    } catch {
      // try next candidate
    }
  }
  throw new Error("No Python 3.12+ interpreter found on PATH to build the gremlinboard-api wheel.");
}

async function buildWheel() {
  const python = await findBuildPython();
  const wheelsDir = path.join(npmPkgDir, "wheels");
  await fsp.mkdir(wheelsDir, { recursive: true });
  await runCommand(python.command, [
    ...python.args,
    "-m",
    "pip",
    "wheel",
    "--no-deps",
    "-w",
    wheelsDir,
    apiDir,
  ]);

  const wheelFiles = (await fsp.readdir(wheelsDir)).filter((name) => name.endsWith(".whl"));
  if (wheelFiles.length === 0) {
    throw new Error(`pip wheel completed but no .whl file was produced in ${wheelsDir}`);
  }
  return wheelFiles[0];
}

// ---------------------------------------------------------------------------
// Step 5: copy core widgets
// ---------------------------------------------------------------------------

async function copyCoreWidgets() {
  const destWidgetsDir = path.join(npmPkgDir, "widgets");
  await fsp.mkdir(destWidgetsDir, { recursive: true });

  await fsp.copyFile(path.join(widgetsSrcDir, "__init__.py"), path.join(destWidgetsDir, "__init__.py"));

  for (const widgetId of CORE_WIDGETS) {
    const src = path.join(widgetsSrcDir, widgetId);
    if (!fs.existsSync(src)) {
      throw new Error(`Expected core widget directory not found: ${src}`);
    }
    const dest = path.join(destWidgetsDir, widgetId);
    await fsp.cp(src, dest, {
      recursive: true,
      filter: (source) => !source.split(path.sep).includes("__pycache__"),
    });
  }
  log(`Copied core widgets: ${CORE_WIDGETS.join(", ")}`);
}

// ---------------------------------------------------------------------------
// Step 6: build-info.json + package.json version sync
// ---------------------------------------------------------------------------

async function writeBuildInfo(wheelFilename) {
  const pkgJsonPath = path.join(npmPkgDir, "package.json");
  const pkgJson = JSON.parse(await fsp.readFile(pkgJsonPath, "utf-8"));

  const buildInfo = {
    version: pkgJson.version,
    builtAt: new Date().toISOString(),
    wheel: wheelFilename,
  };
  await fsp.writeFile(path.join(npmPkgDir, "build-info.json"), JSON.stringify(buildInfo, null, 2) + "\n", "utf-8");
  log(`Wrote build-info.json (version=${buildInfo.version}, wheel=${wheelFilename})`);
}

// ---------------------------------------------------------------------------
// Step 7: npm pack
// ---------------------------------------------------------------------------

async function npmPack() {
  log("Running npm pack...");
  await runCommand(npmCmd(), ["pack"], { cwd: npmPkgDir });

  const tarballs = (await fsp.readdir(npmPkgDir)).filter((name) => name.endsWith(".tgz"));
  tarballs.sort((a, b) => {
    const statA = fs.statSync(path.join(npmPkgDir, a)).mtimeMs;
    const statB = fs.statSync(path.join(npmPkgDir, b)).mtimeMs;
    return statB - statA;
  });
  return tarballs[0] ? path.join(npmPkgDir, tarballs[0]) : null;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  await cleanOutputs();
  await buildWeb();
  await normalizeWebOutput();
  const wheelFilename = await buildWheel();
  await copyCoreWidgets();
  await writeBuildInfo(wheelFilename);
  const tarballPath = await npmPack();

  log("Done.");
  if (tarballPath) {
    log(`Tarball: ${tarballPath}`);
  } else {
    log("Warning: could not locate the produced tarball.");
  }
}

main().catch((error) => {
  process.stderr.write(`[build-npm-package] FAILED: ${error?.stack ?? error}\n`);
  process.exit(1);
});
