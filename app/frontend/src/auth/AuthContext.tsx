import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { authApi, tokens } from "../lib/api";

export interface Store {
  id: number;
  code: string;
  name: string;
  store_type: string;
  state_name: string;
  state_code: string;
  gstin_number: string;
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
  business_units?: Store[];
  all_business_units?: boolean;
}

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  activeStore: Store | null;
  setActiveStore: (s: Store | null) => void;
}

const AuthContext = createContext<AuthContextValue>(null as unknown as AuthContextValue);

export const useAuth = () => useContext(AuthContext);

const STORE_KEY = "kdps_store";

function pickDefaultStore(u: User): Store | null {
  const saved = localStorage.getItem(STORE_KEY);
  if (saved) {
    const found = u.stores.find((s) => s.code === saved);
    if (found) return found;
  }
  if (u.scope_type === "store" && u.stores.length) return u.stores[0];
  return null; // "all" → network view
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeStore, setActiveStoreState] = useState<Store | null>(null);
  // Bumped on every login/logout/forced-expiry; a slow prior-session bootstrap
  // that resolves after the epoch changed must not clobber the new session.
  const sessionEpoch = useRef(0);

  function setActiveStore(s: Store | null) {
    setActiveStoreState(s);
    if (s) localStorage.setItem(STORE_KEY, s.code);
    else localStorage.removeItem(STORE_KEY);
  }

  useEffect(() => {
    let cancelled = false;
    const epoch = sessionEpoch.current;
    (async () => {
      if (tokens.access) {
        try {
          const { data } = await authApi.me();
          if (!cancelled && sessionEpoch.current === epoch) {
            setUser(data);
            setActiveStoreState(pickDefaultStore(data));
          }
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
      setUser(null);
      setActiveStoreState(null);
    }
    window.addEventListener("kdps:session-expired", onExpired);
    return () => window.removeEventListener("kdps:session-expired", onExpired);
  }, []);

  async function login(username: string, password: string) {
    sessionEpoch.current += 1;
    const { data } = await authApi.login(username, password);
    tokens.set({ access: data.access, refresh: data.refresh });
    setUser(data.user);
    setActiveStoreState(pickDefaultStore(data.user));
  }

  function logout() {
    sessionEpoch.current += 1;
    authApi.logout().catch(() => undefined);
    tokens.clear();
    setUser(null);
    setActiveStoreState(null);
  }

  return (
    <AuthContext.Provider
      value={{ user, loading, login, logout, activeStore, setActiveStore }}
    >
      {children}
    </AuthContext.Provider>
  );
}
