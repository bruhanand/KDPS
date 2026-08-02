import { Navigate, Outlet, useLocation } from "react-router-dom";

import { KdpsLogo } from "../components/KdpsLogo";
import { roomAt } from "../routes";
import { AppShell } from "../shell/AppShell";
import { TillProvider } from "../till/TillProvider";
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
  const allowed = canAccess(location.pathname, user);
  const room = allowed ? roomAt(location.pathname) : undefined;
  const shell = (
    <AppShell room={room}>
      {allowed ? <Outlet /> : <AccessDenied />}
    </AppShell>
  );
  // Billing's till must sit above the shell so the top bar can show its live
  // status. Other Sell screens keep their route-local provider.
  return room === "counter" ? <TillProvider>{shell}</TillProvider> : shell;
}
