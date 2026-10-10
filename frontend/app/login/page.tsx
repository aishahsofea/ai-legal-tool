"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getSupabase } from "@/lib/supabaseClient";
import { useSession } from "@/lib/useSession";

export default function Login() {
  const router = useRouter();
  const session = useSession();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (session) router.replace("/workspace");
  }, [session, router]);

  const signIn = async () => {
    setError(null);
    const { error } = await getSupabase().auth.signInWithOAuth({
      provider: "github",
      options: { redirectTo: `${window.location.origin}/auth/callback` },
    });
    if (error) setError(error.message);
  };

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-[360px] rounded-xl border border-(--line) bg-(--surface) p-8 shadow-[var(--shadow-raised)]">
        <span className="text-xs font-semibold tracking-[0.24em] text-(--text)">LOCUS</span>
        <h1 className="m-0 mb-6 mt-4 font-serif text-3xl font-light text-(--text)">Sign in</h1>
        <button
          type="button"
          onClick={signIn}
          disabled={session !== null}
          className="inline-flex min-h-10 w-full items-center justify-center rounded-lg border-none bg-(--accent) px-4 py-2 text-xs font-semibold tracking-[0.04em] text-(--surface) transition-colors duration-200 hover:bg-(--accent-deep) disabled:opacity-60"
        >
          Continue with GitHub
        </button>
        {error && <p role="alert" className="m-0 mt-4 text-sm text-(--danger)">{error}</p>}
      </div>
    </main>
  );
}
