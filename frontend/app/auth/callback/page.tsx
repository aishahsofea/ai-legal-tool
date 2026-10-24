"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { takePendingQuery, withQuery } from "@/lib/pendingQuery";
import { getSupabase } from "@/lib/supabaseClient";

// A page, not a route handler: the PKCE verifier lives in browser storage, and the client exchanges the ?code= on init.
export default function AuthCallback() {
  const router = useRouter();

  useEffect(() => {
    void getSupabase()
      .auth.getSession()
      .then(({ data }) => router.replace(withQuery(data.session ? "/workspace" : "/login", takePendingQuery())));
  }, [router]);

  return null;
}
