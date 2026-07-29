import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { authApi, tokens, unitContext } from "../lib/api";

export interface Store {
  id: number;
  code: string;
  name: string;
  store_type: string;
  state_name: string;
  state_code: string;
  gstin_number: string;
}

export interface Brand {
  id: number;
  code: string;
  name: string;
}

export interface Role {
  code: string;
  name: string;
  landing_page: string;
  nav_groups: string[];
}

// SIDEBAR RBAC contract (issue #85): the server decides what each person may
// see and do. These describe the new authenticated-user payload; the shell
// re-housing (#87) consumes them. Optional here so nothing that reads the
// legacy `nav_groups` shell needs to change in this contract-only slice.
export interface NavSection {
  code: string;
  label: string;
  order: number;
  capability: "view" | "operate" | "approve" | "manage";
  scope_label: string; // exact RBAC-sheet wording, e.g. "Own store"
}

export interface User {
  id: number;
  username: string;
  full_name: string;
  is_superuser: boolean;
  role: Role | null;
  scope_type: string;
  scope_label: string;
  entity: number | null;
  entity_name?: string;
  stores: Store[];
  nav_groups: string[];
  landing_page: string;
  // New RBAC contract (may be absent when talking to an older backend).
  sections?: NavSection[];
  capabilities?: Record<string, NavSection["capability"]>;
  /** Stored actor policies this person satisfies — the questions the capability
   *  ladder cannot ask, because two roles can share a rung of one section and
   *  still differ on a single action inside it (#75). */
  actions?: string[];
  business_units?: Store[];
  all_business_units?: boolean;
  // What the top-bar switcher offers (issue #88). A brand manager works across
  // every store inside their own brands, so they get a brand filter where
  // everyone else gets a unit list. Both come from the server — never inferred
  // here from the role code.
  business_unit_mode?: "units" | "brands";
  assigned_brands?: Brand[];
}

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  activeStore: Store | null;
  setActiveStore: (s: Store | null) => void;
  activeBrand: Brand | null;
  setActiveBrand: (b: Brand | null) => void;
}

const AuthContext = createContext<AuthContextValue>(null as unknown as AuthContextValue);

export const useAuth = () => useContext(AuthContext);

const STORE_KEY = "kdps_store";
const BRAND_KEY = "kdps_brand";

/** The units this person may act in — server payload only, with the legacy
 *  `stores` field as the fallback for an older backend. */
export function allowedUnits(u: User): Store[] {
  return u.business_units ?? u.stores ?? [];
}

/** Is the switcher a brand filter rather than a unit list? */
export function isBrandScoped(u: User): boolean {
  return u.business_unit_mode === "brands";
}

/** The unit to open in. A remembered choice counts only if the server still
 *  lists it; someone with exactly one unit and no network view is locked into
 *  it, so the context is never ambiguous. */
function pickDefaultStore(u: User): Store | null {
  if (isBrandScoped(u)) return null;
  const units = allowedUnits(u);
  const saved = localStorage.getItem(STORE_KEY);
  if (saved) {
    const found = units.find((s) => s.code === saved);
    if (found) return found;
  }
  if (!u.all_business_units && units.length === 1) return units[0];
  return null; // network view (or nothing to act in at all)
}

function pickDefaultBrand(u: User): Brand | null {
  if (!isBrandScoped(u)) return null;
  const brands = u.assigned_brands ?? [];
  const saved = localStorage.getItem(BRAND_KEY);
  const found = saved ? brands.find((b) => b.code === saved) : undefined;
  if (found) return found;
  return brands.length === 1 ? brands[0] : null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeStore, setActiveStoreState] = useState<Store | null>(null);
  const [activeBrand, setActiveBrandState] = useState<Brand | null>(null);
  // Bumped on every login/logout/forced-expiry; a slow prior-session bootstrap
  // that resolves after the epoch changed must not clobber the new session.
  const sessionEpoch = useRef(0);

  /** Set the context React renders *and* the one axios sends, together. The
   *  header is read synchronously by the request interceptor, so it must not
   *  wait for an effect — a screen's fetch can fire before a parent effect runs
   *  and would otherwise carry the previous unit. */
  function applyContext(store: Store | null, brand: Brand | null) {
    setActiveStoreState(store);
    setActiveBrandState(brand);
    unitContext.set({ unit: store?.code, brand: brand?.name });
  }

  function setActiveStore(s: Store | null) {
    applyContext(s, null);
    if (s) localStorage.setItem(STORE_KEY, s.code);
    else localStorage.removeItem(STORE_KEY);
  }

  function setActiveBrand(b: Brand | null) {
    applyContext(null, b);
    if (b) localStorage.setItem(BRAND_KEY, b.code);
    else localStorage.removeItem(BRAND_KEY);
  }

  function startSession(u: User) {
    setUser(u);
    applyContext(pickDefaultStore(u), pickDefaultBrand(u));
  }

  function endSession() {
    setUser(null);
    applyContext(null, null);
  }

  useEffect(() => {
    let cancelled = false;
    const epoch = sessionEpoch.current;
    (async () => {
      if (tokens.access) {
        try {
          const { data } = await authApi.me();
          if (!cancelled && sessionEpoch.current === epoch) startSession(data);
        } catch {
          if (!cancelled && sessionEpoch.current === epoch) tokens.clear();
        }
      }
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    function onExpired() {
      sessionEpoch.current += 1;
      endSession();
    }
    window.addEventListener("kdps:session-expired", onExpired);
    return () => window.removeEventListener("kdps:session-expired", onExpired);
  }, []);

  async function login(username: string, password: string) {
    sessionEpoch.current += 1;
    const { data } = await authApi.login(username, password);
    tokens.set({ access: data.access, refresh: data.refresh });
    startSession(data.user);
  }

  function logout() {
    sessionEpoch.current += 1;
    authApi.logout().catch(() => undefined);
    tokens.clear();
    endSession();
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login,
        logout,
        activeStore,
        setActiveStore,
        activeBrand,
        setActiveBrand,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
