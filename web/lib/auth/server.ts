import { createNeonAuth, type NeonAuth } from "@neondatabase/auth/next/server";

let authInstance: NeonAuth | null = null;

/**
 * Build the server auth client only when a request needs it. Next evaluates route and
 * proxy modules while building, including on machines that intentionally have no
 * deployment credentials.
 */
export function getNeonAuth(): NeonAuth {
  if (authInstance) return authInstance;

  const baseUrl = process.env.NEON_AUTH_BASE_URL;
  if (!baseUrl) {
    throw new Error("NEON_AUTH_BASE_URL is not set");
  }

  const cookieSecret = process.env.NEON_AUTH_COOKIE_SECRET;
  if (!cookieSecret) {
    throw new Error("NEON_AUTH_COOKIE_SECRET is not set");
  }

  authInstance = createNeonAuth({
    baseUrl,
    cookies: { secret: cookieSecret },
  });
  return authInstance;
}
