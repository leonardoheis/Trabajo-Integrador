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

export function openOAuthPopup(): Promise<string> {
  return new Promise((resolve, reject) => {
    const popup = window.open("/auth/login", "classiflow-oauth", "width=500,height=650");
    if (!popup) {
      reject(new Error("Popup blocked"));
      return;
    }

    function onMessage(event: MessageEvent<unknown>): void {
      if (event.origin !== window.location.origin) {
        return;
      }
      if (!isOAuthTokenMessage(event.data)) {
        return;
      }
      window.removeEventListener("message", onMessage);
      clearInterval(pollClosed);
      resolve(event.data.token);
    }

    window.addEventListener("message", onMessage);

    const pollClosed = setInterval(() => {
      if (popup.closed) {
        clearInterval(pollClosed);
        window.removeEventListener("message", onMessage);
        reject(new Error("Popup closed before completing sign-in"));
      }
    }, 500);
  });
}
