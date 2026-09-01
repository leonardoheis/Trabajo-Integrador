import { getToken, clearToken } from "../auth/tokenStorage";

export interface CurrentUser {
  email: string;
  isAdmin: boolean;
  picture: string | null;
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(path, { ...init, headers });
  if (response.status === 401) {
    clearToken();
    window.location.href = "/login";
  }
  return response;
}

export async function fetchCurrentUser(): Promise<CurrentUser> {
  const response = await apiFetch("/auth/me");
  if (!response.ok) {
    throw new Error(`GET /auth/me failed: ${response.status}`);
  }
  return response.json();
}

export async function logoutRequest(): Promise<void> {
  const response = await apiFetch("/auth/logout", { method: "POST" });
  if (!response.ok) {
    throw new Error(`POST /auth/logout failed: ${response.status}`);
  }
}
