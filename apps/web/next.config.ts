import type { NextConfig } from "next";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "../..");

const nextConfig: NextConfig = {
  output: "standalone",
  typedRoutes: true,
  outputFileTracingRoot: repoRoot,
  experimental: {
    externalDir: true,
  },
};

export default nextConfig;
