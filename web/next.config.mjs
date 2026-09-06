/** @type {import('next').NextConfig} */

// The engine is a separate service: Vercel hosts this UI, the Python graph runs where it
// can hold a sandbox, a vector store and durable checkpoints. See web/README.md.
//
// The deployed engine's URL is not a secret -- it is a public HTTP endpoint with no
// credentials -- so it is the production default rather than a dashboard setting nobody
// can see. Development still points at localhost, because a `npm run dev` that silently
// drives the live service is a trap. Either can be overridden with NEXT_PUBLIC_API_URL.
const ENGINE = "https://cogniflow-engine.onrender.com";

const nextConfig = {
  env: {
    NEXT_PUBLIC_API_URL:
      process.env.NEXT_PUBLIC_API_URL ??
      (process.env.NODE_ENV === "production" ? ENGINE : "http://127.0.0.1:8000"),
  },
};
export default nextConfig;
