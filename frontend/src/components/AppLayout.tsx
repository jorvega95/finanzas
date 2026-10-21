// Shell de la app: sidebar de navegación + panel principal "inset" con header
// (sección actual, notificaciones y toggle de tema). En móvil el sidebar se
// abre como drawer.
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useSpace } from "../features/spaces/SpaceProvider";
import { useTheme } from "../lib/theme";
import NotificationBell from "./NotificationBell";
import Icon, { type IconName } from "./ui/Icon";

const NAV: { to: string; label: string; icon: IconName }[] = [
  { to: "/", label: "Dashboard", icon: "dashboard" },
  { to: "/pronostico", label: "Pronóstico", icon: "forecast" },
  { to: "/transacciones", label: "Transacciones", icon: "transactions" },
  { to: "/cuentas", label: "Cuentas", icon: "wallet" },
  { to: "/msi", label: "MSI", icon: "calendar" },
  { to: "/eventos", label: "Eventos", icon: "party" }, // EVT-01
  { to: "/compromisos", label: "Compromisos", icon: "target" }, // CXP-01
  { to: "/inversiones", label: "Inversiones", icon: "investments" },
  { to: "/ajustes", label: "Ajustes", icon: "settings" },
];

function currentLabel(pathname: string): string {
  const match = NAV.filter((n) => n.to !== "/" && pathname.startsWith(n.to))[0];
  return match?.label ?? "Dashboard";
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { me, activeSpace, setActiveSpace } = useSpace();
  const initial = (me.profile.display_name || "?").trim().charAt(0).toUpperCase();

  return (
    <div className="flex h-full flex-col gap-6 p-3">
      <div className="flex items-center gap-2.5 px-2 pt-1">
        <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-ink">
          <Icon name="card" className="size-4" />
        </span>
        <span className="font-mono text-sm font-semibold tracking-tight">Finanzas</span>
      </div>

      <nav className="flex flex-col gap-0.5">
        <p className="px-2 pb-1.5 text-[11px] font-medium uppercase tracking-wider text-ink-subtle">
          Plataforma
        </p>
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            onClick={onNavigate}
            className={({ isActive }) =>
              `flex items-center gap-2.5 rounded-lg px-2 py-2 text-sm transition md:py-1.5 ${
                isActive
                  ? "bg-muted font-medium text-ink"
                  : "text-ink-muted hover:bg-muted/60 hover:text-ink"
              }`
            }
          >
            <Icon name={item.icon} />
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="mt-auto space-y-2">
        {/* ESP-03/R8: switcher de espacio */}
        <label className="block px-2 text-[11px] font-medium uppercase tracking-wider text-ink-subtle">
          Espacio
        </label>
        <div className="relative">
          <select
            className="h-9 w-full appearance-none rounded-lg border border-line bg-card pl-3 pr-8 text-sm text-ink focus:border-accent focus:outline-none"
            value={activeSpace.id}
            onChange={(e) => setActiveSpace(e.target.value)}
            aria-label="Cambiar de espacio"
          >
            {me.spaces.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
                {s.type === "shared" ? " · compartido" : ""}
              </option>
            ))}
          </select>
          <Icon
            name="chevronsUpDown"
            className="pointer-events-none absolute right-2.5 top-1/2 size-3.5 -translate-y-1/2 text-ink-subtle"
          />
        </div>
        <div className="flex items-center gap-2.5 rounded-lg px-2 py-2">
          <span className="grid size-7 place-items-center rounded-full bg-accent text-xs font-semibold text-accent-ink">
            {initial}
          </span>
          <span className="truncate text-sm font-medium">{me.profile.display_name}</span>
        </div>
      </div>
    </div>
  );
}

export default function AppLayout() {
  const { theme, toggle } = useTheme();
  const { pathname } = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => setDrawerOpen(false), [pathname]);

  return (
    <div className="flex min-h-screen bg-canvas">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 md:block">
        <Sidebar />
      </aside>

      {drawerOpen && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-black/60" onClick={() => setDrawerOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 border-r border-line bg-canvas">
            <Sidebar onNavigate={() => setDrawerOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col md:py-2 md:pr-2">
        <div className="flex min-h-full flex-1 flex-col bg-surface md:rounded-2xl md:border md:border-line">
          <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-line bg-surface/85 px-4 backdrop-blur md:rounded-t-2xl md:px-6">
            <div className="flex items-center gap-2 text-sm">
              <button
                className="btn-ghost -ml-2 md:hidden"
                aria-label="Abrir menú"
                onClick={() => setDrawerOpen(true)}
              >
                <Icon name="menu" />
              </button>
              <Icon name="panel" className="hidden size-4 text-ink-subtle md:block" />
              <span className="font-medium">{currentLabel(pathname)}</span>
            </div>
            <div className="flex items-center gap-1">
              {/* REM-04: centro de notificaciones in-app */}
              <NotificationBell />
              <button onClick={toggle} className="btn-ghost" aria-label="Cambiar tema">
                <Icon name={theme === "dark" ? "sun" : "moon"} />
              </button>
            </div>
          </header>
          <main className="flex-1 px-4 py-6 md:px-8 md:py-8">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}
