import axios from "axios";
import type { AxiosRequestConfig, AxiosResponse } from "axios";

import type { components, paths } from "./api-schema";

// Same-origin when unset (platform proxy routes /api → backend on same host).
// Set REACT_APP_BACKEND_URL explicitly only for cross-origin dev (e.g. local FE → remote API).
const BASE = (import.meta.env.REACT_APP_BACKEND_URL as string) || "";

export const api = axios.create({ baseURL: `${BASE}/api`, withCredentials: true });

// Sessions live in the httpOnly `access_token`/`refresh_token` cookies the
// backend already sets on login/refresh (`accounts.views._set_auth_cookies`) —
// nothing token-shaped is ever kept in localStorage or any other JS-readable
// spot, so an XSS bug on this page can't walk off with a bearer token. Bumped
// by `AuthContext` on every login/logout so a stale request's failed refresh
// (kicked off *before* a fresh login/logout) never clobbers the session that
// already replaced it — same race this file used to guard by comparing
// localStorage's refresh token before/after, now done with a counter because
// there is no longer a client-readable token to compare.
let authEpoch = 0;
export const authSession = {
  bump() {
    authEpoch += 1;
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
  if (unitContext.unit) config.headers["X-KDPS-Unit"] = unitContext.unit;
  if (unitContext.brand) config.headers["X-KDPS-Brand"] = unitContext.brand;
  return config;
});

// Single-flight refresh: N simultaneous 401s share one /auth/refresh call, so a
// rotating refresh token is spent exactly once (the backend blacklists after
// rotation). The refresh cookie is httpOnly — nothing to read or pass here, the
// browser attaches it and the new access/refresh cookies land in the response.
let refreshPromise: Promise<void> | null = null;

function refreshAccessToken(): Promise<void> {
  refreshPromise ??= axios
    .post(`${BASE}/api/auth/refresh`, {}, { withCredentials: true })
    .then(() => undefined)
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
    if (error.response?.status === 401 && original && !original._retry) {
      original._retry = true;
      const epochAtStart = authEpoch;
      try {
        await refreshAccessToken();
        return api(original);
      } catch {
        // Only fire the expiry event if a newer login/logout hasn't already
        // moved past this attempt — see the `authEpoch` note above.
        if (authEpoch === epochAtStart) {
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
  // The refresh token is read straight off the httpOnly cookie server-side
  // (`LogoutView`), so there is nothing for this call to carry.
  logout: () => api.post("/auth/logout", {}),
};

export type ApiSchemas = components["schemas"];
type ApiPath = keyof paths;
type PathWithoutPrefix<P extends ApiPath> = P extends `/api${infer Rest}` ? Rest : P;
type ApiRelativePath = PathWithoutPrefix<ApiPath>;
type FullApiPath<P extends ApiRelativePath> = `/api${P}` & ApiPath;
type ApiOperation<P extends ApiRelativePath, Method extends PropertyKey> =
  paths[FullApiPath<P>] extends infer Path
    ? Method extends keyof Path
      ? Path[Method]
      : never
    : never;
type JsonBody<Response> = Response extends {
  content: { "application/json": infer Body };
}
  ? Body
  : never;
type SuccessBody<Operation> = Operation extends { responses: infer Responses }
  ? Responses extends { 200: infer Ok }
    ? JsonBody<Ok>
    : Responses extends { 201: infer Created }
      ? JsonBody<Created>
      : never
  : never;

function toApiPath(path: ApiRelativePath): ApiPath {
  return `/api${path}` as ApiPath;
}

export const typedApi = {
  get<TPath extends ApiRelativePath>(
    path: TPath,
    config?: AxiosRequestConfig,
  ): Promise<AxiosResponse<SuccessBody<ApiOperation<TPath, "get">>>> {
    return api.get<SuccessBody<ApiOperation<TPath, "get">>>(
      toApiPath(path).replace("/api", ""),
      config,
    );
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

/** Flatten one DRF error value — a string, or a list/dict of them — to a sentence. */
function firstSentence(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = firstSentence(item);
      if (found) return found;
    }
    return "";
  }
  if (value && typeof value === "object") {
    for (const nested of Object.values(value)) {
      const found = firstSentence(nested);
      if (found) return found;
    }
  }
  return "";
}

export function apiErrorMessage(e: unknown): string {
  const data = (e as { response?: { data?: unknown } })?.response?.data;
  // `detail` is what a refusal raised by a view or permission carries, and it
  // is the sentence written for the user, so it wins. A serializer refusal
  // arrives keyed by field instead (`{"roles": ["Floor rule: …"]}`) — the
  // message is just as deliberate, and falling through to "something went
  // wrong" would tell the user nothing about a rule they just hit.
  const detail = (data as { detail?: unknown })?.detail;
  // The D10 endpoints answer `{"error": "<sentence>", "code": "<CODE>"}` instead
  // (`core/refusals.py`), so `error` is read by name too. The fallback below
  // would find it by walking the object — but only while `error` is declared
  // before `code`, and a body whose message depends on its key order is one
  // reorder away from showing a store person "SCOPE_DENIED".
  const error = (data as { error?: unknown })?.error;
  return (
    firstSentence(detail) ||
    firstSentence(error) ||
    firstSentence(data) ||
    "Something went wrong. Please try again."
  );
}
