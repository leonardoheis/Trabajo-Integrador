import { Outlet } from "react-router";
import Sidebar from "./Sidebar";
import ThemeToggle from "./ThemeToggle";

export default function Layout() {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="absolute right-4 top-3 z-10">
          <ThemeToggle />
        </div>
        <Outlet />
      </main>
    </div>
  );
}
