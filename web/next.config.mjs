/** @type {import('next').NextConfig} */
const nextConfig = {
  // The engine is a separate service: Vercel hosts this UI, the Python graph runs where
  // it can hold a sandbox, a vector store and durable checkpoints. See web/README.md.
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000",
  },
};
export default nextConfig;
