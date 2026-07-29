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
import { itemOwning, itemPath, itemVisible, normalizePath } from "../shell/navConfig";
import type { User } from "./AuthContext";

export function canAccess(pathname: string, user: User): boolean {
  if (user.is_superuser) return true;
  // The screen this URL belongs to, longest match first — so /money/vendor's
  // finance-only gate beats plain /money, and a mixed-case or trailing-slash
  // URL can't slip past into the default-allow branch.
  const screen = itemOwning(pathname);
  // Unknown path: no screen claims it, so there is nothing to protect. It is
  // either a legacy URL on its way to a redirect (resolved by the router, then
  // guarded at its new home) or a 404-ish stub.
  if (!screen) return true;
  const held = user.capabilities?.[screen.section];
  if ((held ?? "none") === "none") return false;
  // A URL strictly under the item's own path — a document, not the list/create
  // screen itself — answers to `childMinCapability` where the item sets one
  // (#119: a PT stays readable below the rung its own making screen needs).
  const isChild = itemPath(screen) !== normalizePath(pathname);
  const gate =
    isChild && screen.childMinCapability
      ? { ...screen, minCapability: screen.childMinCapability }
      : screen;
  return itemVisible(gate, held, user.role?.code ?? "", false);
}
