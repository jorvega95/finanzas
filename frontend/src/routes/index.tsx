// Rutas por feature (src/features/*).
import { createBrowserRouter, Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import AppLayout from "../components/AppLayout";
import Placeholder from "../components/Placeholder";
import LoginPage from "../features/auth/LoginPage";

function Protected() {
  const { session, loading, configured } = useAuth();
  if (loading) {
    return (
      <main className="grid min-h-screen place-items-center text-sm text-ink-muted">
        Cargando…
      </main>
    );
  }
  if (!configured || !session) return <Navigate to="/login" replace />;
  return <Outlet />;
}

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    element: <Protected />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { path: "/", element: <Placeholder title="Dashboard" /> },
          { path: "/transacciones", element: <Placeholder title="Transacciones" /> },
          { path: "/tarjetas", element: <Placeholder title="Tarjetas" /> },
          { path: "/msi", element: <Placeholder title="Meses sin intereses" /> },
          { path: "/inversiones", element: <Placeholder title="Inversiones" /> },
          { path: "/ajustes", element: <Placeholder title="Ajustes" /> },
        ],
      },
    ],
  },
]);
