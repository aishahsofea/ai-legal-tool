import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { Page } from "@playwright/test";

function supabaseUrl(): string {
  if (process.env.NEXT_PUBLIC_SUPABASE_URL) return process.env.NEXT_PUBLIC_SUPABASE_URL;
  const env = readFileSync(join(__dirname, "..", ".env.local"), "utf8");
  return /^NEXT_PUBLIC_SUPABASE_URL=(.+)$/m.exec(env)![1].trim();
}

export async function signIn(page: Page) {
  const key = `sb-${new URL(supabaseUrl()).hostname.split(".")[0]}-auth-token`;
  const session = {
    access_token: "probe",
    refresh_token: "probe",
    token_type: "bearer",
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    user: { id: "probe", email: "probe@example.com", user_metadata: {}, aud: "authenticated" },
  };
  await page.addInitScript(([k, v]) => window.localStorage.setItem(k, v), [key, JSON.stringify(session)]);
  await page.route("**/threads", (route) => route.fulfill({ json: [] }));
}
