// Shell de la app: sidebar de navegación + header con espacio activo,
// toggle de tema y cierre de sesión.
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { useSpace } from "../features/spaces/SpaceProvider";
import { useTheme } from "../lib/theme";

const NAV = [
  { to: "/", label: "Dashboard", icon: "📊" },
  { to: "/pronostico", label: "Pronóstico", icon: "🔮" },
  { to: "/transacciones", label: "Transacciones", icon: "💸" },
  { to: "/tarjetas", label: "Tarjetas", icon: "💳" },
  { to: "/msi", label: "MSI", icon: "📅" },
  { to: "/inversiones", label: "Inversiones", icon: "📈" },
  { to: "/ajustes", label: "Ajustes", icon: "⚙️" },
];

export default function AppLayout() {
  const { signOut } = useAuth();
  const { theme, toggle } = useTheme();
  const { me, activeSpace, setActiveSpace } = useSpace();

  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-60 shrink-0 border-r border-line bg-card p-4 dark:border-slate-800 dark:bg-slate-900 md:flex md:flex-col">
        <div className="mb-8 px-2 text-lg font-semibold">Finanzas</div>
        <nav className="space-y-1">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${
                  isActive
                    ? "bg-accent/10 font-medium text-accent-strong dark:text-teal-300"
                    : "text-ink-muted hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
                }`
              }
            >
              <span aria-hidden>{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto px-2 text-xs text-ink-muted dark:text-slate-500">
          {me.profile.display_name}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-line bg-card px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-ink-muted dark:text-slate-400">Espacio:</span>
            {/* ESP-03/R8: switcher de espacio */}
            <select
              className="input w-auto py-1"
              value={activeSpace.id}
              onChange={(e) => setActiveSpace(e.target.value)}
              aria-label="Cambiar de espacio"
            >
              {me.spaces.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                  {s.type === "shared" ? " 👥" : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={toggle} className="btn-secondary" aria-label="Cambiar tema">
              {theme === "dark" ? "☀️" : "🌙"}
            </button>
            <button onClick={() => void signOut()} className="btn-secondary">
              Salir
            </button>
          </div>
        </header>
        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
