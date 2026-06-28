import { createContext, useContext, useEffect, useState } from "react";
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

  function setActiveStore(s: Store | null) {
    setActiveStoreState(s);
    if (s) localStorage.setItem(STORE_KEY, s.code);
    else localStorage.removeItem(STORE_KEY);
  }

  useEffect(() => {
    (async () => {
      if (tokens.access) {
        try {
          const { data } = await authApi.me();
          setUser(data);
          setActiveStoreState(pickDefaultStore(data));
        } catch {
          tokens.clear();
        }
      }
      setLoading(false);
    })();
  }, []);

  async function login(username: string, password: string) {
    const { data } = await authApi.login(username, password);
    tokens.set({ access: data.access, refresh: data.refresh });
    setUser(data.user);
    setActiveStoreState(pickDefaultStore(data.user));
  }

  function logout() {
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
