import axios from "axios";
import type { AxiosRequestConfig } from "axios";

import type { components, paths } from "./api-schema";

const BASE = (import.meta.env.REACT_APP_BACKEND_URL as string) || "";

export const api = axios.create({ baseURL: `${BASE}/api` });

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

api.interceptors.request.use((config) => {
  const t = tokens.access;
  if (t) config.headers.Authorization = `Bearer ${t}`;
  return config;
});

// Refresh the access token once on a 401, then replay the request.
api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && original && !original._retry && tokens.refresh) {
      original._retry = true;
      try {
        const { data } = await axios.post(`${BASE}/api/auth/refresh`, {
          refresh: tokens.refresh,
        });
        tokens.set({ access: data.access, refresh: data.refresh });
        original.headers.Authorization = `Bearer ${data.access}`;
        return api(original);
      } catch {
        tokens.clear();
      }
    }
    return Promise.reject(error);
  },
);

export const authApi = {
  login: (username: string, password: string) =>
    api.post("/auth/login", { username, password }),
  me: () => api.get("/auth/me"),
  logout: () => api.post("/auth/logout", { refresh: tokens.refresh }),
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
