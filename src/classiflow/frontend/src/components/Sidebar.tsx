import { useState } from "react";
import { NavLink } from "react-router";
import { useAuth } from "../auth/AuthContext";

const LINK_BASE = "flex items-center gap-3 rounded-md px-3 py-2 text-base border-l-2";
const ACTIVE_CLASSES =
  "border-[var(--color-accent)] bg-[var(--color-surface)] text-[var(--color-text)]";
const INACTIVE_CLASSES =
  "border-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text)]";

function linkClass({ isActive }: { isActive: boolean }): string {
  return `${LINK_BASE} ${isActive ? ACTIVE_CLASSES : INACTIVE_CLASSES}`;
}

function initials(email: string): string {
  const local = email.split("@")[0];
  const parts = local.split(/[._-]/);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return local.slice(0, 2).toUpperCase();
}

type NavItemProps = {
  to: string;
  label: string;
  end?: boolean;
  collapsed: boolean;
  icon: React.ReactNode;
};

function NavItem({ to, label, end, collapsed, icon }: NavItemProps) {
  return (
    <NavLink to={to} end={end} className={linkClass} title={collapsed ? label : undefined}>
      <span className="flex-shrink-0">{icon}</span>
      {!collapsed && <span>{label}</span>}
    </NavLink>
  );
}

const IconProcessing = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
  >
    <path d="M8 2v3M8 11v3M2 8h3M11 8h3M4.22 4.22l2.12 2.12M9.66 9.66l2.12 2.12M4.22 11.78l2.12-2.12M9.66 6.34l2.12-2.12" />
  </svg>
);
const IconClassification = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
  >
    <rect x="2" y="3" width="12" height="10" rx="1" />
    <path d="M5 7h6M5 9.5h4" />
  </svg>
);
const IconReview = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
  >
    <circle cx="8" cy="8" r="6" />
    <path d="M8 5v3l2 2" />
  </svg>
);
const IconChat = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
  >
    <path d="M2 3h12v8H9l-3 2v-2H2z" />
  </svg>
);
const IconUsers = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
  >
    <circle cx="6" cy="5" r="2.5" />
    <path d="M1 14c0-2.8 2.2-5 5-5s5 2.2 5 5" />
    <path d="M11 7a2 2 0 0 1 0 4M14 14c0-2-1.3-3.7-3-4.5" />
  </svg>
);
const IconAudit = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
  >
    <rect x="2" y="2" width="12" height="12" rx="1" />
    <path d="M5 5h6M5 8h6M5 11h3" />
  </svg>
);
const IconMetrics = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
  >
    <path d="M2 14V2" />
    <path d="M2 14h12" />
    <rect x="4.5" y="8" width="2.5" height="4" />
    <rect x="9" y="5" width="2.5" height="7" />
  </svg>
);
const IconCollapse = ({ collapsed }: { collapsed: boolean }) => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
  >
    {collapsed ? <path d="M6 4l4 4-4 4" /> : <path d="M10 4l-4 4 4 4" />}
  </svg>
);

export default function Sidebar() {
  const { user, isAdmin, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(false);

  return (
    <nav
      className="flex h-full flex-col justify-between border-r border-[var(--color-border)] bg-[var(--color-bg-inset)] p-3 transition-all duration-200"
      style={{ width: collapsed ? "56px" : "224px", minWidth: collapsed ? "56px" : "224px" }}
    >
      <div className="flex flex-col gap-1">
        {/* Logo + collapse toggle */}
        <div className="mb-3 flex items-center justify-between px-1">
          {collapsed ? (
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-[var(--color-accent)] font-mono text-xs font-bold text-white">
              CF
            </span>
          ) : (
            <span className="text-lg font-bold text-[var(--color-accent)]">Classiflow</span>
          )}
          <button
            onClick={() => setCollapsed((c) => !c)}
            className="rounded-md p-1 text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <IconCollapse collapsed={collapsed} />
          </button>
        </div>

        {!collapsed && (
          <span className="mt-1 px-3 text-[10px] font-semibold uppercase tracking-widest text-[var(--color-text-faint)]">
            Pipeline
          </span>
        )}
        <NavItem to="/" end label="Processing" collapsed={collapsed} icon={<IconProcessing />} />
        <NavItem
          to="/classification"
          label="Classification"
          collapsed={collapsed}
          icon={<IconClassification />}
        />
        <NavItem to="/review" label="Review Queue" collapsed={collapsed} icon={<IconReview />} />
        <NavItem to="/metrics" label="Metrics" collapsed={collapsed} icon={<IconMetrics />} />
        {!collapsed && (
          <span className="mt-2 px-3 text-[10px] font-semibold uppercase tracking-widest text-[var(--color-text-faint)]">
            Knowledge
          </span>
        )}
        <NavItem to="/chat" label="Chat" collapsed={collapsed} icon={<IconChat />} />
        {isAdmin && (
          <>
            {!collapsed && (
              <span className="mt-2 px-3 text-[10px] font-semibold uppercase tracking-widest text-[var(--color-text-faint)]">
                Admin
              </span>
            )}
            <NavItem to="/users" label="Users" collapsed={collapsed} icon={<IconUsers />} />
            <NavItem to="/audit" label="Audit Log" collapsed={collapsed} icon={<IconAudit />} />
          </>
        )}
      </div>

      {/* User + sign out */}
      <div className="flex flex-col gap-1 border-t border-[var(--color-border)] pt-3">
        {user && (
          <div
            className="flex items-center gap-3 rounded-md px-3 py-2"
            title={collapsed ? user.email : undefined}
          >
            {user.picture ? (
              <img
                src={user.picture}
                alt={user.email}
                className="h-7 w-7 flex-shrink-0 rounded-full object-cover"
                referrerPolicy="no-referrer"
              />
            ) : (
              <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-[var(--color-accent)] font-mono text-xs font-semibold text-white">
                {initials(user.email)}
              </span>
            )}
            {!collapsed && (
              <span className="truncate text-sm text-[var(--color-text-muted)]">{user.email}</span>
            )}
          </div>
        )}
        <button
          onClick={logout}
          className="flex items-center gap-3 rounded-md border-l-2 border-transparent px-3 py-2 text-base text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
          title={collapsed ? "Sign out" : undefined}
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            className="flex-shrink-0"
          >
            <path d="M6 2H2v12h4M10 5l4 3-4 3M6 8h8" />
          </svg>
          {!collapsed && <span>Sign out</span>}
        </button>
      </div>
    </nav>
  );
}
