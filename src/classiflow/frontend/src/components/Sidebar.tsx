import { NavLink } from "react-router";
import { useAuth } from "../auth/AuthContext";

const LINK_CLASS = "block rounded-md px-3 py-2 text-sm border-l-2 border-transparent";
const ACTIVE_CLASS =
  "border-[var(--color-accent)] bg-[var(--color-surface)] text-[var(--color-text)]";
const INACTIVE_CLASS = "text-[var(--color-text-muted)] hover:text-[var(--color-text)]";

function linkClass({ isActive }: { isActive: boolean }): string {
  return `${LINK_CLASS} ${isActive ? ACTIVE_CLASS : INACTIVE_CLASS}`;
}

export default function Sidebar() {
  const { isAdmin, logout } = useAuth();

  return (
    <nav className="flex h-full w-56 flex-col justify-between border-r border-[var(--color-border)] bg-[var(--color-bg-inset)] p-4">
      <div className="flex flex-col gap-1">
        <p className="mb-4 px-3 text-lg font-bold text-[var(--color-accent)]">Classiflow</p>
        <NavLink to="/" end className={linkClass}>
          Processing
        </NavLink>
        <NavLink to="/classification" className={linkClass}>
          Classification
        </NavLink>
        <NavLink to="/chat" className={linkClass}>
          Chat
        </NavLink>
        {isAdmin && (
          <>
            <NavLink to="/users" className={linkClass}>
              Users
            </NavLink>
            <NavLink to="/audit" className={linkClass}>
              Audit Log
            </NavLink>
          </>
        )}
      </div>
      <button onClick={logout} className={`${LINK_CLASS} ${INACTIVE_CLASS} text-left`}>
        Sign out
      </button>
    </nav>
  );
}
