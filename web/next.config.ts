import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",

  turbopack: { root: __dirname },
};

export default nextConfig;
