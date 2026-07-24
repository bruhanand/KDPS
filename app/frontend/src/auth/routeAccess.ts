// Route → authorization rules for the client PWA.
//
// ProtectedRoute only checks that a user is authenticated, so any logged-in
// user could load any page shell by typing the URL. The backend already 403s
// the data, so this is defense-in-depth + honest UX: mirror the server gates
// on the client so scoped users don't land on pages they have no business on.
//
// Since #87 there is one authority for both the menu and the guard: the section
// manifest. Every rule below is *derived* from it — a screen's URL sits under
// its section's items, so what the sidebar hides, the URL bar hides too, and
// the two can't drift. Whether the user holds a section is the server's answer
// (`capabilities`, the SIDEBAR RBAC contract #85), never inferred here.
import { NAV_ITEMS, itemPath, meetsCapability, underPrefix } from "../shell/navConfig";
import type { Capability } from "../shell/navConfig";
import type { User } from "./AuthContext";

export { PAYROLL_ROLES, meetsCapability } from "../shell/navConfig";

interface AccessRule {
  prefix: string;
  /** Section code the caller must hold at any capability above `none`. */
  section: string;
  /** Any-of check against `user.role.code`, mirroring a finer backend gate. */
  roles?: string[];
  /** Rung the caller must hold on `section`, mirroring a finer backend gate —
   *  e.g. the ledgers need `money: manage` (`finledger.IsBooksKeeper`). */
  minCapability?: Capability;
}

// Longest-prefix wins, so a specific rule overrides its section's general one
// (e.g. /money/vendor's finance-only gate beats plain /money). Deep links own
// no rule — the section hosting the screen keeps it.
const RULES: AccessRule[] = NAV_ITEMS.filter((i) => !i.deepLink)
  .map((i) => ({
    prefix: itemPath(i),
    section: i.section,
    roles: i.roles,
    minCapability: i.minCapability,
  }))
  .sort((a, b) => b.prefix.length - a.prefix.length);

export function canAccess(pathname: string, user: User): boolean {
  if (user.is_superuser) return true;
  // React Router matches route paths case-insensitively, but our rule prefixes
  // are lowercase — lowercase the path so mixed-case URLs (e.g. /MONEY/VENDOR)
  // can't slip past a rule into the default-allow branch.
  const normalized = pathname.toLowerCase();
  // "/" is Home's dashboard, not a prefix of the whole app — match it exactly.
  const rule =
    normalized === "/"
      ? RULES.find((r) => r.prefix === "/")
      : RULES.find((r) => r.prefix !== "/" && underPrefix(normalized, r.prefix));
  // Unknown path: no screen claims it, so there is nothing to protect. It is
  // either a legacy URL on its way to a redirect (resolved by the router, then
  // guarded at its new home) or a 404-ish stub.
  if (!rule) return true;
  const held = user.capabilities?.[rule.section];
  if ((held ?? "none") === "none") return false;
  if (rule.minCapability && !meetsCapability(held, rule.minCapability)) return false;
  if (rule.roles && !rule.roles.includes(user.role?.code ?? "")) return false;
  return true;
}
