import { Navigate, Outlet } from "react-router-dom";

import { AppShell } from "../shell/AppShell";
import { useAuth } from "./AuthContext";

export function ProtectedRoute() {
  const { user, loading } = useAuth();
  if (loading) return <div className="full-loader">Loading KDPS…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return (
    <AppShell>
      <Outlet />
    </AppShell>
  );
}
