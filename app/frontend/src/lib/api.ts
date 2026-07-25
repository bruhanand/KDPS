import axios from "axios";
import type { AxiosRequestConfig } from "axios";

import type { components, paths } from "./api-schema";

// Same-origin when unset (platform proxy routes /api → backend on same host).
// Set REACT_APP_BACKEND_URL explicitly only for cross-origin dev (e.g. local FE → remote API).
const BASE = (import.meta.env.REACT_APP_BACKEND_URL as string) || "";

export const api = axios.create({ baseURL: `${BASE}/api`, withCredentials: true });

const ACCESS_KEY = "kdps_access";
const REFRESH_KEY = "kdps_refresh";

export const tokens = {
  get access() {
    return localStorage.getItem(ACCESS_KEY);
  },
  get refresh() {
    return localStorage.getItem(REFRESH_KEY);
  },
  set({ access, refresh }: { access: string; refresh?: string }) {
    localStorage.setItem(ACCESS_KEY, access);
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

// The business unit — or, for a brand manager, the brand — the person picked in
// the top-bar switcher (#88). Sent on every call so the server narrows its answer
// to that unit. It can only ever *narrow*: the server intersects the header with
// what the caller is entitled to and refuses anything outside it, so nothing here
// is a permission. Held outside React because the interceptor needs it
// synchronously, before any screen's fetch runs.
let activeUnitCode = "";
let activeBrandName = "";

export const unitContext = {
  get unit() {
    return activeUnitCode;
  },
  get brand() {
    return activeBrandName;
  },
  /** Both are set together: choosing one clears the other. */
  set(next: { unit?: string; brand?: string }) {
    activeUnitCode = next.unit ?? "";
    activeBrandName = next.brand ?? "";
  },
};

api.interceptors.request.use((config) => {
  const t = tokens.access;
  if (t) config.headers.Authorization = `Bearer ${t}`;
  if (unitContext.unit) config.headers["X-KDPS-Unit"] = unitContext.unit;
  if (unitContext.brand) config.headers["X-KDPS-Brand"] = unitContext.brand;
  return config;
});

// Single-flight refresh: N simultaneous 401s share one /auth/refresh call, so a
// rotating refresh token is spent exactly once (the backend blacklists after rotation).
let refreshPromise: Promise<string> | null = null;

function refreshAccessToken(): Promise<string> {
  refreshPromise ??= axios
    .post(
      `${BASE}/api/auth/refresh`,
      { refresh: tokens.refresh },
      { withCredentials: true },
    )
    .then(({ data }) => {
      tokens.set({ access: data.access, refresh: data.refresh });
      return data.access as string;
    })
    .finally(() => {
      refreshPromise = null;
    });
  return refreshPromise;
}

// Refresh the access token once on a 401, then replay the request.
api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && original && !original._retry && tokens.refresh) {
      original._retry = true;
      const staleRefresh = tokens.refresh;
      try {
        const access = await refreshAccessToken();
        original.headers.Authorization = `Bearer ${access}`;
        return api(original);
      } catch {
        // Only wipe tokens if a newer login hasn't already replaced them — a
        // losing racer must never clear the fresh session's credentials.
        if (tokens.refresh === staleRefresh) {
          tokens.clear();
          window.dispatchEvent(new Event("kdps:session-expired"));
        }
      }
    }
    return Promise.reject(error);
  },
);

export const authApi = {
  login: (username: string, password: string) =>
    api.post("/auth/login", { username, password }),
  me: () => api.get("/auth/me"),
  // Read tokens at call time and pass the header explicitly so logout survives
  // the request-interceptor microtask even after tokens.clear() runs.
  logout: () => {
    const refresh = tokens.refresh;
    const access = tokens.access;
    return api.post(
      "/auth/logout",
      { refresh },
      { headers: access ? { Authorization: `Bearer ${access}` } : {} },
    );
  },
};

export type ApiSchemas = components["schemas"];
type ApiPath = keyof paths;
type PathWithoutPrefix<P extends ApiPath> = P extends `/api${infer Rest}` ? Rest : P;
type ApiRelativePath = PathWithoutPrefix<ApiPath>;

function toApiPath(path: ApiRelativePath): ApiPath {
  return `/api${path}` as ApiPath;
}

export const typedApi = {
  get<TPath extends ApiRelativePath>(path: TPath, config?: AxiosRequestConfig) {
    return api.get(toApiPath(path).replace("/api", ""), config);
  },
  post<TPath extends ApiRelativePath>(path: TPath, data?: unknown, config?: AxiosRequestConfig) {
    return api.post(toApiPath(path).replace("/api", ""), data, config);
  },
  patch<TPath extends ApiRelativePath>(path: TPath, data?: unknown, config?: AxiosRequestConfig) {
    return api.patch(toApiPath(path).replace("/api", ""), data, config);
  },
  put<TPath extends ApiRelativePath>(path: TPath, data?: unknown, config?: AxiosRequestConfig) {
    return api.put(toApiPath(path).replace("/api", ""), data, config);
  },
};

export function apiErrorMessage(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail) return JSON.stringify(detail);
  return "Something went wrong. Please try again.";
}
