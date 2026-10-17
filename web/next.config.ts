import path from "node:path";
import type { NextConfig } from "next";

// Static export: `next build` writes web/out/. The engine does not serve it.
// GET / on :8000 is window/index.html. Development runs `next dev -p 3100`
// against the engine on :8000.
const nextConfig: NextConfig = {
  output: "export",
  // Without this, Turbopack infers its workspace root from a stray
  // package-lock.json in the home directory (warning in the dev log).
  turbopack: { root: __dirname },
};

export default nextConfig;
