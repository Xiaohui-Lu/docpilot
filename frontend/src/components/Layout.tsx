import clsx from "clsx";
import { BookCheck, CalendarClock, FileText, LayoutDashboard, LogOut, MessageSquareText, Users } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../lib/auth";

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="size-8" aria-hidden>
        <rect width="32" height="32" rx="8" fill="#1f8a70" />
        <path d="M10 8h8l6 6v10a2 2 0 0 1-2 2H10a2 2 0 0 1-2-2V10a2 2 0 0 1 2-2z" fill="#f5f3ee" />
        <path d="M18 8v6h6" fill="#a7dcc9" />
        <path d="M12 18l3 3 6-7" stroke="#12343b" strokeWidth="2.4" fill="none" strokeLinecap="round" />
      </svg>
      <div>
        <div className="text-[15px] font-semibold leading-none text-white">DocPilot</div>
        <div className="mt-1 text-[11px] leading-none text-brand-200/80">Contract deadlines & risk</div>
      </div>
    </div>
  );
}

export function Layout() {
  const { user, orgName, logout, can } = useAuth();
  const nav = [
    { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
    { to: "/deadlines", label: "Deadlines", icon: CalendarClock },
    { to: "/documents", label: "Documents", icon: FileText },
    { to: "/rules", label: "Rulebook", icon: BookCheck },
    { to: "/ask", label: "Ask AI", icon: MessageSquareText },
    ...(can("admin") ? [{ to: "/team", label: "Team & audit", icon: Users }] : []),
  ];

  return (
    <div className="flex min-h-full">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col bg-night px-4 py-5 md:flex">
        <Logo />
        <nav className="mt-8 flex flex-col gap-1" aria-label="Main">
          {nav.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
                  isActive ? "bg-white/10 text-white" : "text-brand-100/70 hover:bg-white/5 hover:text-white",
                )
              }
            >
              <Icon className="size-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto rounded-xl bg-white/5 p-3">
          <div className="truncate text-sm font-medium text-white">{user?.name}</div>
          <div className="truncate text-xs text-brand-100/60">{orgName}</div>
          <div className="mt-2 flex items-center justify-between">
            <span className="rounded bg-brand-500/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-200">
              {user?.role}
            </span>
            <button
              onClick={logout}
              className="flex items-center gap-1 text-xs text-brand-100/70 hover:text-white"
              type="button"
            >
              <LogOut className="size-3.5" /> Sign out
            </button>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile top bar */}
        <header className="flex items-center justify-between bg-night px-4 py-3 md:hidden">
          <Logo />
          <button onClick={logout} className="text-xs text-brand-100" type="button">
            Sign out
          </button>
        </header>
        <nav className="flex gap-1 overflow-x-auto border-b border-line bg-white px-3 py-2 md:hidden" aria-label="Main">
          {nav.map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                clsx(
                  "whitespace-nowrap rounded-md px-3 py-1.5 text-sm",
                  isActive ? "bg-paper font-medium" : "text-muted",
                )
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <main className="mx-auto w-full max-w-[1280px] flex-1 px-4 py-6 sm:px-8 sm:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
