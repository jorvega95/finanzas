// Rutas por feature (src/features/*).
import { createBrowserRouter, Navigate, Outlet } from "react-router-dom";
import AppLayout from "../components/AppLayout";
import AccountsPage from "../features/accounts/AccountsPage";
import CommitmentsPage from "../features/commitments/CommitmentsPage";
import DashboardPage from "../features/dashboard/DashboardPage";
import EventsPage from "../features/events/EventsPage";
import ForecastPage from "../features/forecast/ForecastPage";
import InvestmentsPage from "../features/investments/InvestmentsPage";
import MsiPage from "../features/msi/MsiPage";
import SettingsPage from "../features/settings/SettingsPage";
import { SpaceProvider } from "../features/spaces/SpaceProvider";
import TransactionsPage from "../features/transactions/TransactionsPage";

// GLO-07: modo local mono-usuario, sin login; el backend resuelve al dueño.
function Root() {
  return (
    <SpaceProvider>
      <Outlet />
    </SpaceProvider>
  );
}

export const router = createBrowserRouter([
  { path: "/login", element: <Navigate to="/" replace /> },
  {
    element: <Root />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { path: "/", element: <DashboardPage /> },
          { path: "/pronostico", element: <ForecastPage /> },
          { path: "/transacciones", element: <TransactionsPage /> },
          { path: "/cuentas", element: <AccountsPage /> },
          { path: "/tarjetas", element: <Navigate to="/cuentas" replace /> },
          { path: "/msi", element: <MsiPage /> },
          { path: "/eventos", element: <EventsPage /> },
          { path: "/compromisos", element: <CommitmentsPage /> },
          { path: "/inversiones", element: <InvestmentsPage /> },
          { path: "/ajustes", element: <SettingsPage /> },
        ],
      },
    ],
  },
]);
