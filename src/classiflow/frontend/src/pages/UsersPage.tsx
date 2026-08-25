import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchUsers, createUser, updateUser, deleteUser } from "../api/users";
import DataTable, { type Column } from "../components/DataTable";
import type { AllowedUserRecord } from "../api/users";

export default function UsersPage() {
  const [newEmail, setNewEmail] = useState("");
  const queryClient = useQueryClient();

  const { data: users = [] } = useQuery({ queryKey: ["users"], queryFn: fetchUsers });

  function invalidate(): void {
    queryClient.invalidateQueries({ queryKey: ["users"] });
  }

  async function handleAdd(): Promise<void> {
    if (!newEmail) return;
    await createUser(newEmail, false);
    setNewEmail("");
    invalidate();
  }

  const columns: Column<AllowedUserRecord>[] = [
    { header: "Email", render: (u) => u.email },
    { header: "Active", render: (u) => (u.isActive ? "Yes" : "No") },
    { header: "Admin", render: (u) => (u.isAdmin ? "Yes" : "No") },
    { header: "Blocked", render: (u) => (u.isBlocked ? "Yes" : "No") },
    {
      header: "Actions",
      render: (u) => (
        <div className="flex gap-2">
          <button
            onClick={() => updateUser(u.email, { isBlocked: !u.isBlocked }).then(invalidate)}
            className="text-sm text-[var(--color-accent)]"
          >
            {u.isBlocked ? "Unblock" : "Block"}
          </button>
          <button
            onClick={() => updateUser(u.email, { isAdmin: !u.isAdmin }).then(invalidate)}
            className="text-sm text-[var(--color-accent)]"
          >
            {u.isAdmin ? "Revoke admin" : "Make admin"}
          </button>
          <button
            onClick={() => deleteUser(u.email).then(invalidate)}
            className="text-sm text-[var(--color-danger)]"
          >
            Delete
          </button>
        </div>
      ),
    },
  ];

  return (
    <div className="p-6">
      <h1 className="mb-4 text-xl font-semibold">Users</h1>
      <div className="mb-4 flex gap-2">
        <input
          placeholder="new.user@example.com"
          value={newEmail}
          onChange={(e) => setNewEmail(e.target.value)}
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] p-2 text-sm"
        />
        <button
          onClick={handleAdd}
          className="rounded-md bg-[var(--color-accent)] px-3 py-2 text-sm text-white"
        >
          Add
        </button>
      </div>
      <DataTable columns={columns} rows={users} rowKey={(u) => u.email} />
    </div>
  );
}
