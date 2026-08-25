import { useEffect } from "react";

export default function OAuthPopupPage() {
  useEffect(() => {
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
