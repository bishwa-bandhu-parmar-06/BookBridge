import type { NextConfig } from "next";

// On Vercel the site must know where the API runs; without it every request would go to
// "localhost" on the student's own phone. Fail the build with a clear message instead.
if (process.env.VERCEL && !process.env.NEXT_PUBLIC_API_URL) {
  throw new Error(
    "Set NEXT_PUBLIC_API_URL in Vercel → Project → Settings → Environment Variables " +
      "(your backend address, e.g. https://bookbridge-api.onrender.com), then redeploy.",
  );
}

const nextConfig: NextConfig = {
  /* config options here */
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
};

export default nextConfig;
