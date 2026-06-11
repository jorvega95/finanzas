// Login con Google y email/contraseña (R7, ESP-01). Textos es-MX.
import { useState, type FormEvent } from "react";
import { useAuth } from "../../auth/AuthProvider";
import { useTheme } from "../../lib/theme";

export default function LoginPage() {
  const { configured, signInWithGoogle, signInWithPassword, signUpWithPassword } =
    useAuth();
  const { theme, toggle } = useTheme();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setInfo(null);
    setBusy(true);
    try {
      if (mode === "signin") {
        await signInWithPassword(email, password);
      } else {
        await signUpWithPassword(email, password);
        setInfo("Revisa tu correo para confirmar tu cuenta.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al iniciar sesión");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-screen place-items-center p-4">
      <button
        onClick={toggle}
        className="btn-secondary absolute right-4 top-4"
        aria-label="Cambiar tema"
      >
        {theme === "dark" ? "☀️" : "🌙"}
      </button>

      <div className="card w-full max-w-sm p-8">
        <h1 className="text-2xl font-semibold">Finanzas</h1>
        <p className="mt-1 text-sm text-ink-muted dark:text-slate-400">
          Tu dinero, claro y en orden.
        </p>

        {!configured && (
          <p className="mt-6 rounded-lg bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-200">
            Falta configurar Supabase: copia <code>.env.example</code> a{" "}
            <code>.env</code> con tu URL y anon key.
          </p>
        )}

        <button
          onClick={() => signInWithGoogle().catch((e) => setError(e.message))}
          disabled={!configured || busy}
          className="btn-secondary mt-6 w-full"
        >
          <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden>
            <path
              fill="currentColor"
              d="M21.35 11.1H12v2.9h5.35c-.5 2.5-2.6 4.3-5.35 4.3a5.8 5.8 0 1 1 0-11.6c1.45 0 2.75.55 3.75 1.45l2.15-2.15A8.9 8.9 0 0 0 12 3.5a8.5 8.5 0 1 0 0 17c4.9 0 8.5-3.45 8.5-8.3 0-.35-.05-.75-.15-1.1Z"
            />
          </svg>
          Continuar con Google
        </button>

        <div className="my-6 flex items-center gap-3 text-xs text-ink-muted dark:text-slate-500">
          <span className="h-px flex-1 bg-line dark:bg-slate-800" />
          o con tu correo
          <span className="h-px flex-1 bg-line dark:bg-slate-800" />
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="email" className="label">
              Correo electrónico
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="input"
              placeholder="tu@correo.com"
            />
          </div>
          <div>
            <label htmlFor="password" className="label">
              Contraseña
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input"
              placeholder="••••••••"
            />
          </div>

          {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
          {info && <p className="text-sm text-emerald-700 dark:text-emerald-400">{info}</p>}

          <button type="submit" disabled={!configured || busy} className="btn-primary w-full">
            {mode === "signin" ? "Iniciar sesión" : "Crear cuenta"}
          </button>
        </form>

        <button
          onClick={() => setMode(mode === "signin" ? "signup" : "signin")}
          className="mt-4 w-full text-center text-sm text-accent hover:underline"
        >
          {mode === "signin"
            ? "¿No tienes cuenta? Regístrate"
            : "¿Ya tienes cuenta? Inicia sesión"}
        </button>
      </div>
    </main>
  );
}
