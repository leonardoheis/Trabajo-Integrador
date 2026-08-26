import { apiFetch } from "./auth";

export interface AllowedUserRecord {
  email: string;
  isActive: boolean;
  isAdmin: boolean;
  isBlocked: boolean;
  createdAt: string;
}

export async function fetchUsers(): Promise<AllowedUserRecord[]> {
  const response = await apiFetch("/users");
  if (!response.ok) {
    throw new Error(`GET /users failed: ${response.status}`);
  }
  return response.json();
}

export async function createUser(email: string, isAdmin: boolean): Promise<AllowedUserRecord> {
  const response = await apiFetch("/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, isAdmin }),
  });
  if (!response.ok) {
    throw new Error(`POST /users failed: ${response.status}`);
  }
  return response.json();
}

export async function updateUser(
  email: string,
  changes: { isActive?: boolean; isAdmin?: boolean; isBlocked?: boolean },
): Promise<AllowedUserRecord> {
  const response = await apiFetch(`/users/${encodeURIComponent(email)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });
  if (!response.ok) {
    throw new Error(`PATCH /users/${email} failed: ${response.status}`);
  }
  return response.json();
}

export async function deleteUser(email: string): Promise<void> {
  const response = await apiFetch(`/users/${encodeURIComponent(email)}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(`DELETE /users/${email} failed: ${response.status}`);
  }
}
