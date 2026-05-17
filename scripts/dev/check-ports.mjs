#!/usr/bin/env node
/**
 * check-ports.mjs - warn if the default backend/frontend dev ports are busy.
 *
 * Called from setup.ps1 and setup.sh at the very end. Exits 0 always so it
 * is purely advisory; the dev launcher (dev-frontend.mjs) handles the actual
 * fallback for the frontend, and uvicorn surfaces its own EADDRINUSE for the
 * backend if the founder ignores the warning.
 *
 * Probes:
 *   - 8000  (FastAPI default; BACKEND_PORT in .env.example)
 *   - 3000  (Next.js default)
 *
 * No new dependencies; uses Node stdlib `net` only.
 */

import net from "node:net";

const PORTS = [
  { port: 8000, label: "backend (FastAPI)" },
  { port: 3000, label: "frontend (Next.js)" },
];

function isPortFree(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.unref();
    server.once("error", () => resolve(false));
    server.once("listening", () => server.close(() => resolve(true)));
    server.listen(port, "0.0.0.0");
  });
}

const results = await Promise.all(
  PORTS.map(async ({ port, label }) => ({
    port,
    label,
    free: await isPortFree(port),
  })),
);

const busy = results.filter((r) => !r.free);
if (busy.length === 0) {
  console.log("check-ports: 8000 and 3000 are free.");
  process.exit(0);
}

console.log("");
console.log("check-ports: WARNING - the following dev ports are in use:");
for (const { port, label } of busy) {
  console.log(`  - ${port}  (${label})`);
}
console.log("");
console.log("The frontend dev script auto-falls-back to the next free port");
console.log("in 3000..3010. The backend does NOT fall back. To free a port:");
console.log("");
console.log("  Windows (PowerShell):");
console.log("    netstat -ano | findstr :8000");
console.log("    Stop-Process -Id <pid>");
console.log("");
console.log("  macOS / Linux:");
console.log("    lsof -ti :8000 | xargs kill -9");
console.log("");
// Advisory only.
process.exit(0);
