interface OAuthTokenMessage {
  type: "oauth-token";
  token: string;
}

function isOAuthTokenMessage(data: unknown): data is OAuthTokenMessage {
  return (
    typeof data === "object" &&
    data !== null &&
    "type" in data &&
    (data as { type: unknown }).type === "oauth-token" &&
    "token" in data &&
    typeof (data as { token: unknown }).token === "string"
  );
}

// Google's own OAuth pages (accounts.google.com) set a Cross-Origin-Opener-Policy
// that makes reading popup.closed from the opener unreliable mid-flow (the browser
// logs a COOP warning and the check can misfire), so this can't use a
// closed-popup poll as its failure signal -- only the postMessage the popup itself
// sends on success. A generous timeout is the fallback for "the user gave up or
// closed it," not a tight poll loop.
const _SIGN_IN_TIMEOUT_MS = 2 * 60 * 1000;

export function openOAuthPopup(): Promise<string> {
  return new Promise((resolve, reject) => {
    const popup = window.open("/auth/login", "classiflow-oauth", "width=500,height=650");
    if (!popup) {
      reject(new Error("Popup blocked"));
      return;
    }

    function cleanup(): void {
      window.removeEventListener("message", onMessage);
      clearTimeout(timeoutId);
    }

    function onMessage(event: MessageEvent<unknown>): void {
      if (event.origin !== window.location.origin) {
        return;
      }
      if (!isOAuthTokenMessage(event.data)) {
        return;
      }
      cleanup();
      resolve(event.data.token);
    }

    window.addEventListener("message", onMessage);

    const timeoutId = setTimeout(() => {
      cleanup();
      reject(new Error("Sign-in timed out"));
    }, _SIGN_IN_TIMEOUT_MS);
  });
}
