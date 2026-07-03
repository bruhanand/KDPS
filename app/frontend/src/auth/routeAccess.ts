// Route → authorization rules for the client PWA (issue #37).
//
// ProtectedRoute only checks that a user is authenticated, so any logged-in
// user could load any page shell by typing the URL. The backend already 403s
// the data, so this is defense-in-depth + honest UX: mirror the server gates
// on the client so scoped users don't land on pages they have no business on.
import type { User } from "./AuthContext";

// Mirror of finledger/views.py `FINANCE_ROLES` — vendor/cash ledger reads.
export const FINANCE_ROLES = ["accounts", "owner", "it_admin"];
// Mirror of accounts/views.py `RBAC_ADMIN_ROLES` — user/role administration.
export const RBAC_ADMIN_ROLES = ["owner", "it_admin"];

interface AccessRule {
  prefix: string;
  // Any-of check against `user.nav_groups` (the server-driven nav authority).
  groups?: string[];
  // Any-of check against `user.role.code`, mirroring a finer backend gate.
  roles?: string[];
}

// Longest-prefix wins (sorted below), so more specific rules override the
// group-only fallbacks (e.g. /ledgers/vendor before /ledgers).
const RULES: AccessRule[] = [
  { prefix: "/ledgers/vendor", groups: ["ledgers"], roles: FINANCE_ROLES },
  { prefix: "/ledgers/cash", groups: ["ledgers"], roles: FINANCE_ROLES },
  { prefix: "/ledgers", groups: ["ledgers"] },
  { prefix: "/masters/users", groups: ["master_data"], roles: RBAC_ADMIN_ROLES },
  { prefix: "/masters", groups: ["master_data"] },
  { prefix: "/edges/rbac", groups: ["edges_admin"], roles: RBAC_ADMIN_ROLES },
  { prefix: "/edges", groups: ["edges_admin"] },
  { prefix: "/documents", groups: ["documents"] },
  // /inbound is reachable from both Store Ops and Documents.
  { prefix: "/inbound", groups: ["store_ops", "documents"] },
  { prefix: "/store", groups: ["store_ops"] },
  { prefix: "/controls", groups: ["controls"] },
  { prefix: "/intel", groups: ["intelligence"] },
].sort((a, b) => b.prefix.length - a.prefix.length);

function matches(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(prefix + "/");
}

// Pure guard: can `user` load `pathname`? Superusers always pass; unknown
// routes default-allow (harmless "coming soon" stubs stay reachable).
export function canAccess(pathname: string, user: User): boolean {
  if (user.is_superuser) return true;
  const rule = RULES.find((r) => matches(pathname, r.prefix));
  if (!rule) return true;
  if (rule.groups && !rule.groups.some((g) => user.nav_groups.includes(g))) return false;
  if (rule.roles && !rule.roles.includes(user.role?.code ?? "")) return false;
  return true;
}
