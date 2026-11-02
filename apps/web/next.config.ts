import type { NextConfig } from "next";

// The browser talks to the Next.js server, which forwards API calls to the
// backend. That keeps one public port (3000) and avoids CORS entirely; in
// Docker the target is the `api` service, locally it is 127.0.0.1:8000.
const apiProxyTarget = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  experimental: {
    // Live model comparisons run several provider calls sequentially and can
    // take a minute or more; the 30 s default proxy timeout would cut the
    // response off even though the API finished the work.
    proxyTimeout: 300_000,
  },
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${apiProxyTarget}/api/v1/:path*`,
      },
    ];
  },
  // Baseline hardening. A strict Content-Security-Policy needs nonce plumbing
  // through the App Router and is tracked as future work in the threat model.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
