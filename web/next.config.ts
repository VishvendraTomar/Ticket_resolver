import path from "node:path";

import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// One .env for the whole repo (see /.env.example). Only NEXT_PUBLIC_* values
// reach the browser bundle; nothing else is read by the web app.
loadEnvConfig(path.resolve(process.cwd(), ".."));

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async redirects() {
    return [
      { source: "/w/:workspaceId", destination: "/w/:workspaceId/members", permanent: false },
    ];
  },
};

export default nextConfig;
