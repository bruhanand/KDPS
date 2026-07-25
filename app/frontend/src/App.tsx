import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { ModulePage } from "./pages/ModulePage";
import { Login } from "./pages/Login";
import { PROTECTED_ROUTES } from "./routes";
import { resolveLegacyPath } from "./shell/navConfig";

/** Anything the route table doesn't claim. A pre-#87 URL (a bookmark, a link in
 *  someone's WhatsApp) redirects to that screen's new home, keeping its tail and
 *  query; anything else is an unbuilt corner and says so. */
function LegacyOrStub() {
  const { pathname, search, hash } = useLocation();
  const target = resolveLegacyPath(pathname);
  return target ? <Navigate to={target + search + hash} replace /> : <ModulePage />;
}

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
            <Route path="*" element={<LegacyOrStub />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
