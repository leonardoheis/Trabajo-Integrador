import { useEffect, useRef } from "react";

export default function OAuthPopupPage() {
  // Google's authorization code is single-use -- React 19 StrictMode's dev-only
  // double-invocation of useEffect would otherwise fire this exchange twice with the
  // same code, and the second call fails server-side (the code was already
  // consumed). This guard makes the effect body idempotent regardless of how many
  // times it's invoked.
  const hasExchanged = useRef(false);

  useEffect(() => {
    if (hasExchanged.current) {
      return;
    }
    hasExchanged.current = true;

    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");

    if (!code || !state) {
      window.close();
      return;
    }

    fetch(`/auth/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`, {
      credentials: "include",
    })
      .then((response) => response.json())
      .then((body: { access_token: string }) => {
        window.opener?.postMessage(
          { type: "oauth-token", token: body.access_token },
          window.location.origin,
        );
      })
      .finally(() => window.close());
  }, []);

  return <p>Signing in...</p>;
}
