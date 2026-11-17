import type { NextConfig } from "next";

// The browser only ever talks to this app; /api/* is passed through to the Python API.
// `seo dev` sets SEO_API_URL when it starts the API on another port.
const api = process.env.SEO_API_URL ?? "http://127.0.0.1:8000";

const config: NextConfig = {
  // The browser tests use their own build folder, so they can run while `seo dev` is up
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  // Keep Next's dev badge away from the sidebar's theme switcher
  devIndicators: { position: "bottom-right" },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};

export default config;
