import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { Login } from "./pages/Login";
import { PROTECTED_ROUTES } from "./routes";
import { LegacyRedirect } from "./shell/LegacyRedirect";

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<ProtectedRoute />}>
            {PROTECTED_ROUTES.map((r) => (
              <Route key={r.id} path={r.path} element={r.element} />
            ))}
            {/* Anything the route table doesn't claim. */}
            <Route path="*" element={<LegacyRedirect />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
