import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  eslint: {
    // Linting is a separate, explicit script (`npm run lint`).
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;
