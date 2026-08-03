// Preview-only wrapper for the Claude Design import (`/design-sync`).
//
// Most KDPS components read the router (NavLink, useNavigate, useLocation), so
// they throw when rendered bare in a design-system preview card. This wraps
// them in an in-memory router so the card renders the real component with no
// browser history and no network. It is never imported by the app itself — the
// converter pulls it in via `extraEntries` and `cfg.provider`.
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";

export function DsPreviewProvider({ children }: { children: ReactNode }) {
  return <MemoryRouter initialEntries={["/"]}>{children}</MemoryRouter>;
}
