import { RouterProvider } from "react-router-dom";
import { ToastProvider } from "./components/ui/Toast";
import { ThemeProvider } from "./lib/theme";
import { router } from "./routes";

export default function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </ThemeProvider>
  );
}
