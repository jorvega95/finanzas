// Rutas por feature (src/features/*).
import { createBrowserRouter, Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import AppLayout from "../components/AppLayout";
import Placeholder from "../components/Placeholder";
import LoginPage from "../features/auth/LoginPage";
import CardsPage from "../features/cards/CardsPage";
import MsiPage from "../features/msi/MsiPage";
import SettingsPage from "../features/settings/SettingsPage";
import { SpaceProvider } from "../features/spaces/SpaceProvider";
import TransactionsPage from "../features/transactions/TransactionsPage";

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
  return (
    <SpaceProvider>
      <Outlet />
    </SpaceProvider>
  );
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
          { path: "/transacciones", element: <TransactionsPage /> },
          { path: "/tarjetas", element: <CardsPage /> },
          { path: "/msi", element: <MsiPage /> },
          { path: "/inversiones", element: <Placeholder title="Inversiones" /> },
          { path: "/ajustes", element: <SettingsPage /> },
        ],
      },
    ],
  },
]);
