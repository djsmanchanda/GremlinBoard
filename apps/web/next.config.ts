import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  typedRoutes: true,
  experimental: {
    externalDir: true,
  },
};

export default nextConfig;
