"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { getSupabase } from "@/lib/supabaseClient";

// A page, not a route handler: the PKCE verifier lives in browser storage, and the client exchanges the ?code= on init.
export default function AuthCallback() {
  const router = useRouter();

  useEffect(() => {
    void getSupabase()
      .auth.getSession()
      .then(({ data }) => router.replace(data.session ? "/workspace" : "/login"));
  }, [router]);

  return null;
}
