import { useEffect, useState } from "react";

type Theme = "light" | "dark";

function getInitial(): Theme {
  try {
    const stored = localStorage.getItem("cf-theme");
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // ignore
  }
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(getInitial);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("cf-theme", theme);
    } catch {
      // ignore
    }
  }, [theme]);

  return (
    <button
      onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
      className="flex items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text)]"
      title="Toggle light/dark mode"
    >
      {theme === "dark" ? (
        <>
          <svg
            width="13"
            height="13"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          >
            <circle cx="8" cy="8" r="3.5" />
            <path d="M8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3.05 3.05l1.06 1.06M11.89 11.89l1.06 1.06M3.05 12.95l1.06-1.06M11.89 4.11l1.06-1.06" />
          </svg>
          Light
        </>
      ) : (
        <>
          <svg
            width="13"
            height="13"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          >
            <path d="M13.5 8.5a6 6 0 0 1-7-7 6 6 0 1 0 7 7z" />
          </svg>
          Dark
        </>
      )}
    </button>
  );
}
