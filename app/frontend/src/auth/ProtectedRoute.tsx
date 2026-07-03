import { Navigate, Outlet, useLocation } from "react-router-dom";

import { AppShell } from "../shell/AppShell";
import { AccessDenied } from "./AccessDenied";
import { useAuth } from "./AuthContext";
import { canAccess } from "./routeAccess";

export function ProtectedRoute() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="full-loader">Loading KDPS…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return (
    <AppShell>
      {canAccess(location.pathname, user) ? <Outlet /> : <AccessDenied />}
    </AppShell>
  );
}
