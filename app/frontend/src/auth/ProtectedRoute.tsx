import { Navigate, Outlet, useLocation } from "react-router-dom";

import { KdpsLogo } from "../components/KdpsLogo";
import { AppShell } from "../shell/AppShell";
import { AccessDenied } from "./AccessDenied";
import { useAuth } from "./AuthContext";
import { canAccess } from "./routeAccess";

export function ProtectedRoute() {
  const { user, loading } = useAuth();
  const location = useLocation();
  // The first frame after a refresh is the mark, not bare text: this is the
  // whole screen for as long as the session check takes.
  if (loading) {
    return (
      <div className="full-loader">
        <KdpsLogo variant="mark" height={44} title="" />
        <span>Loading KDPS…</span>
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return (
    <AppShell>
      {canAccess(location.pathname, user) ? <Outlet /> : <AccessDenied />}
    </AppShell>
  );
}
