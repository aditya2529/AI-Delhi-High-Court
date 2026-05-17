#!/usr/bin/env node
/**
 * dev-frontend.mjs - cross-platform Next.js dev launcher with port fallback.
 *
 * Why this exists
 * ---------------
 * `npm run dev` previously hard-coded `next dev -p 3000`. On Windows laptops
 * (the founder, the lawyer-pilot testers) port 3000 is commonly held by
 * a stale Node process from a previous session, which made `next dev` exit
 * immediately with EADDRINUSE. The fix is to probe a small port range and
 * launch on the first free one.
 *
 * Algorithm
 * ---------
 *   - If PORT is set in the environment, honour it exactly. No fallback;
 *     the operator asked for that port specifically.
 *   - Otherwise, probe 3000..3010 and pick the first one not in use.
 *   - If all are taken, exit 1 with an actionable Windows + Unix one-liner.
 *
 * No new npm dependency: uses the Node stdlib `net` module only.
 *
 * Runs on Node >= 20 (matches package.json engines).
 */

import net from "node:net";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const DEFAULT_START = 3000;
const DEFAULT_END = 3010;

/**
 * Check whether a port is free for binding on 0.0.0.0.
 *
 * We open a listener on the candidate port. If listening fails with
 * EADDRINUSE (or anything else), we treat the port as taken. We close
 * the listener immediately on success so we don't hold the port between
 * the probe and the actual `next dev` spawn (TOCTOU window is tiny, and
 * `next dev` will surface a real error if it loses the race).
 */
function isPortFree(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.unref();
    server.once("error", () => resolve(false));
    server.once("listening", () => {
      server.close(() => resolve(true));
    });
    // Bind to 0.0.0.0 to match what `next dev` does, so a free probe here
    // means `next dev` will also succeed.
    server.listen(port, "0.0.0.0");
  });
}

async function pickPort(start, end) {
  for (let p = start; p <= end; p++) {
    if (await isPortFree(p)) return p;
  }
  return null;
}

async function main() {
  let port;

  if (process.env.PORT) {
    const explicit = Number.parseInt(process.env.PORT, 10);
    if (!Number.isInteger(explicit) || explicit < 1 || explicit > 65535) {
      console.error(`dev-frontend: PORT=${process.env.PORT} is not a valid TCP port.`);
      process.exit(1);
    }
    port = explicit;
    console.log(`dev-frontend: PORT env set; using ${port} without fallback.`);
  } else {
    const free = await pickPort(DEFAULT_START, DEFAULT_END);
    if (free === null) {
      console.error(
        `dev-frontend: every port in ${DEFAULT_START}..${DEFAULT_END} is in use.`,
      );
      console.error("");
      console.error("Free one up, then re-run:");
      console.error("  Windows (PowerShell):");
      console.error("    netstat -ano | findstr :3000");
      console.error("    Stop-Process -Id <pid>");
      console.error("  macOS / Linux:");
      console.error("    lsof -ti :3000 | xargs kill -9");
      process.exit(1);
    }
    port = free;
    if (port !== DEFAULT_START) {
      console.warn(
        `dev-frontend: port ${DEFAULT_START} busy; falling back to ${port}.`,
      );
    }
  }

  // Resolve the frontend directory relative to this script's location so
  // running `node scripts/dev/dev-frontend.mjs` from the repo root works,
  // and so does `npm run dev` from inside frontend/.
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = path.dirname(__filename);
  const frontendDir = path.resolve(__dirname, "..", "..", "frontend");

  // Use `npx next dev` rather than a direct require to stay agnostic of
  // monorepo layout. On Windows the binary is next.cmd; spawn with
  // shell: true so PATHEXT lookup works.
  const args = ["next", "dev", "-p", String(port)];
  const child = spawn("npx", args, {
    cwd: frontendDir,
    stdio: "inherit",
    shell: true,
    env: { ...process.env, PORT: String(port) },
  });

  child.on("exit", (code, signal) => {
    if (signal) {
      // Forward the signal exit semantics for parent shells / supervisors.
      process.kill(process.pid, signal);
    } else {
      process.exit(code ?? 0);
    }
  });

  // Forward Ctrl+C and SIGTERM to the child so cleanup is correct.
  for (const sig of ["SIGINT", "SIGTERM"]) {
    process.on(sig, () => {
      if (!child.killed) child.kill(sig);
    });
  }
}

main().catch((err) => {
  console.error("dev-frontend: unexpected error:", err);
  process.exit(1);
});
