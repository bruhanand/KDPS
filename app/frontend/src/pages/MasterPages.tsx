import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Save, ShieldCheck, UserPlus, Users, X } from "lucide-react";

import { api, apiErrorMessage, typedApi } from "../lib/api";
import type { ApiSchemas } from "../lib/api";
import { useAuth } from "../auth/AuthContext";
import { CommercialBadge, StatusChip } from "../lib/format";

function useList<T>(url: string) {
  const [data, setData] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let live = true;
    api
      .get(url)
      .then((r) => live && setData(r.data))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [url]);
  return { data, loading };
}

function Screen({
  eyebrow,
  title,
  count,
  children,
}: {
  eyebrow: string;
  title: string;
  count: number;
  children: ReactNode;
}) {
  return (
    <div className="page-pad">
      <p className="eyebrow">{eyebrow}</p>
      <h1 className="h1 h2-rust" style={{ marginBottom: 4 }}>{title}</h1>
      <p className="lead" style={{ marginBottom: 20 }}>{count} record{count === 1 ? "" : "s"}</p>
      {children}
    </div>
  );
}

interface Store {
  id: number;
  code: string;
  name: string;
  store_type: string;
  city: string;
  state_name: string;
  gstin_number: string;
}

export function StoresPage() {
  const { data } = useList<Store>("/masters/stores");
  return (
    <Screen eyebrow="Master data" title="Stores & Warehouses" count={data.length}>
      <div className="table-wrap">
        <table className="data" data-testid="stores-table">
          <thead>
            <tr>
              <th>Code</th>
              <th>Name</th>
              <th>Type</th>
              <th>City</th>
              <th>State</th>
              <th>GSTIN</th>
            </tr>
          </thead>
          <tbody>
            {data.map((s) => (
              <tr key={s.id} data-testid={`store-row-${s.code}`}>
                <td><b className="mono">{s.code}</b></td>
                <td>{s.name}</td>
                <td><StatusChip status={s.store_type} tone={s.store_type === "warehouse" ? "navy" : "green"} /></td>
                <td>{s.city || "—"}</td>
                <td><span className={`chip chip-${s.state_name === "Bihar" ? "amber" : "blue"}`}>{s.state_name}</span></td>
                <td className="mono" style={{ fontSize: 12.5 }}>{s.gstin_number}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Screen>
  );
}

interface Brand {
  id: number;
  code: string;
  name: string;
  ownership: string;
  return_terms: string;
  commercial_label: string;
}

export function BrandsPage() {
  const { data } = useList<Brand>("/masters/brands");
  return (
    <Screen eyebrow="Master data" title="Brands" count={data.length}>
      <div className="table-wrap">
        <table className="data" data-testid="brands-table">
          <thead>
            <tr>
              <th>Brand</th>
              <th>Ownership</th>
              <th>Return terms</th>
              <th>Commercial model</th>
            </tr>
          </thead>
          <tbody>
            {data.map((b) => (
              <tr key={b.id} data-testid={`brand-row-${b.code}`}>
                <td><b>{b.name}</b></td>
                <td>{b.ownership === "owned" ? "KDPS-owned" : "Brand-owned"}</td>
                <td style={{ textTransform: "capitalize" }}>{b.return_terms}</td>
                <td><CommercialBadge label={b.commercial_label} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Screen>
  );
}

interface Season {
  id: number;
  code: string;
  name: string;
  status: string;
  sort_order: number;
}

export function SeasonsPage() {
  const { data } = useList<Season>("/masters/seasons");
  return (
    <Screen eyebrow="Master data" title="Season Calendar" count={data.length}>
      <div className="table-wrap">
        <table className="data" data-testid="seasons-table">
          <thead>
            <tr>
              <th>Code</th>
              <th>Name</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {data.map((s) => (
              <tr key={s.id} data-testid={`season-row-${s.code}`}>
                <td><b className="mono">{s.code}</b></td>
                <td>{s.name}</td>
                <td><StatusChip status={s.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Screen>
  );
}

interface Gstin {
  id: number;
  gstin: string;
  state_name: string;
  state_code: string;
  legal_entity_name: string;
}

export function GstinsPage() {
  const { data } = useList<Gstin>("/masters/gstins");
  return (
    <Screen eyebrow="Master data" title="GSTIN Registry" count={data.length}>
      <div className="table-wrap">
        <table className="data" data-testid="gstins-table">
          <thead>
            <tr>
              <th>GSTIN</th>
              <th>State</th>
              <th>State code</th>
              <th>Legal entity</th>
            </tr>
          </thead>
          <tbody>
            {data.map((g) => (
              <tr key={g.id} data-testid={`gstin-row-${g.state_code}`}>
                <td className="mono"><b>{g.gstin}</b></td>
                <td><span className={`chip chip-${g.state_name === "Bihar" ? "amber" : "blue"}`}>{g.state_name}</span></td>
                <td className="mono">{g.state_code}</td>
                <td>{g.legal_entity_name}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Screen>
  );
}

type AdminRole = ApiSchemas["AdminRole"];
type AdminUser = ApiSchemas["AdminUser"];
type StoreMini = ApiSchemas["StoreMini"];

interface AdminMeta {
  nav_groups: string[];
  scope_types: { value: string; label: string }[];
  stores: { id: number; code: string; name: string; store_type: string }[];
}

const blankUser = {
  id: 0,
  username: "",
  full_name: "",
  role_id: "",
  scope_type: "all",
  store_ids: [] as number[],
  is_active: true,
  is_staff: false,
  password: "",
};

const blankRole = {
  id: 0,
  code: "",
  name: "",
  description: "",
  landing_page: "home",
  nav_groups: ["home"],
  is_active: true,
};

function storeLabel(stores: StoreMini[] | undefined): string {
  if (!stores?.length) return "Network-wide";
  return stores.map((s) => s.code).join(", ");
}

function normalizeNavGroups(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

export function UsersRolesPage() {
  const { user } = useAuth();
  const canEdit = Boolean(user?.is_superuser || ["owner", "it_admin"].includes(user?.role?.code ?? ""));
  const [tab, setTab] = useState<"users" | "roles">("users");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [roles, setRoles] = useState<AdminRole[]>([]);
  const [meta, setMeta] = useState<AdminMeta>({ nav_groups: [], scope_types: [], stores: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [userForm, setUserForm] = useState(blankUser);
  const [roleForm, setRoleForm] = useState(blankRole);

  const roleOptions = useMemo(() => roles.filter((r) => r.is_active), [roles]);

  function loadAll() {
    setLoading(true);
    setError("");
    Promise.all([
      typedApi.get("/auth/admin/users"),
      typedApi.get("/auth/admin/roles"),
      typedApi.get("/auth/admin/meta"),
    ])
      .then(([u, r, m]) => {
        setUsers(u.data as AdminUser[]);
        setRoles(r.data as AdminRole[]);
        setMeta(m.data as AdminMeta);
      })
      .catch((e) => setError(apiErrorMessage(e)))
      .finally(() => setLoading(false));
  }

  useEffect(loadAll, []);

  function editUser(u: AdminUser) {
    setTab("users");
    setError("");
    setOk("");
    setUserForm({
      id: u.id,
      username: u.username,
      full_name: u.full_name ?? "",
      role_id: u.role?.id ? String(u.role.id) : "",
      scope_type: u.scope_type ?? "all",
      store_ids: (u.stores ?? []).map((s) => s.id),
      is_active: u.is_active ?? true,
      is_staff: u.is_staff ?? false,
      password: "",
    });
  }

  function editRole(r: AdminRole) {
    setTab("roles");
    setError("");
    setOk("");
    setRoleForm({
      id: r.id,
      code: r.code,
      name: r.name,
      description: r.description ?? "",
      landing_page: r.landing_page ?? "home",
      nav_groups: normalizeNavGroups(r.nav_groups),
      is_active: r.is_active ?? true,
    });
  }

  function toggleStore(id: number) {
    setUserForm((f) => ({
      ...f,
      store_ids: f.store_ids.includes(id) ? f.store_ids.filter((x) => x !== id) : [...f.store_ids, id],
    }));
  }

  function toggleNav(key: string) {
    setRoleForm((f) => ({
      ...f,
      nav_groups: f.nav_groups.includes(key) ? f.nav_groups.filter((x) => x !== key) : [...f.nav_groups, key],
    }));
  }

  async function saveUser() {
    setError("");
    setOk("");
    const payload = {
      username: userForm.username,
      full_name: userForm.full_name,
      role_id: userForm.role_id ? Number(userForm.role_id) : null,
      scope_type: userForm.scope_type,
      store_ids: userForm.scope_type === "store" ? userForm.store_ids : [],
      is_active: userForm.is_active,
      is_staff: userForm.is_staff,
      ...(userForm.password ? { password: userForm.password } : {}),
    };
    try {
      if (userForm.id) await typedApi.patch(`/auth/admin/users/${userForm.id}` as "/auth/admin/users/{id}", payload);
      else await typedApi.post("/auth/admin/users", payload);
      setUserForm(blankUser);
      setOk("User saved.");
      loadAll();
    } catch (e) {
      setError(apiErrorMessage(e));
    }
  }

  async function saveRole() {
    setError("");
    setOk("");
    const payload = {
      code: roleForm.code,
      name: roleForm.name,
      description: roleForm.description,
      landing_page: roleForm.landing_page,
      nav_groups: roleForm.nav_groups,
      is_active: roleForm.is_active,
    };
    try {
      if (roleForm.id) await typedApi.patch(`/auth/admin/roles/${roleForm.id}` as "/auth/admin/roles/{id}", payload);
      else await typedApi.post("/auth/admin/roles", payload);
      setRoleForm(blankRole);
      setOk("Role saved.");
      loadAll();
    } catch (e) {
      setError(apiErrorMessage(e));
    }
  }

  if (!canEdit) {
    return (
      <div className="page-pad">
        <p className="eyebrow">Master data · access</p>
        <h1 className="h1 h2-rust">Users & Roles</h1>
        <div className="card section-card" data-testid="rbac-denied">Only Owner and IT Admin users can edit users and roles.</div>
      </div>
    );
  }

  return (
    <div className="page-pad" data-testid="users-roles-page">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Master data · RBAC</p>
          <h1 className="h1 h2-rust">Users & Roles</h1>
        </div>
        <div className="spacer" />
        <div className="seg" data-testid="rbac-tabs">
          <button className={`seg-btn ${tab === "users" ? "active" : ""}`} onClick={() => setTab("users")} data-testid="rbac-users-tab"><Users size={14} /> Users</button>
          <button className={`seg-btn ${tab === "roles" ? "active" : ""}`} onClick={() => setTab("roles")} data-testid="rbac-roles-tab"><ShieldCheck size={14} /> Roles</button>
        </div>
      </div>

      {error && <div className="warn-note" data-testid="rbac-error">{error}</div>}
      {ok && <div className="ok-note" data-testid="rbac-ok">{ok}</div>}

      {tab === "users" ? (
        <>
          <div className="card section-card" data-testid="user-editor-card">
            <div className="toolbar" style={{ marginBottom: 12 }}>
              <h3 className="h3">{userForm.id ? "Edit user" : "Create user"}</h3>
              <div className="spacer" />
              {userForm.id ? <button className="btn btn-sm" onClick={() => setUserForm(blankUser)} data-testid="user-editor-clear"><X size={14} /> New</button> : null}
            </div>
            <div className="form-grid wide-form">
              <input className="input" placeholder="Username" value={userForm.username} onChange={(e) => setUserForm({ ...userForm, username: e.target.value })} data-testid="user-username-input" />
              <input className="input" placeholder="Full name" value={userForm.full_name} onChange={(e) => setUserForm({ ...userForm, full_name: e.target.value })} data-testid="user-full-name-input" />
              <select className="select" value={userForm.role_id} onChange={(e) => setUserForm({ ...userForm, role_id: e.target.value })} data-testid="user-role-select">
                <option value="">No role</option>
                {roleOptions.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
              <select className="select" value={userForm.scope_type} onChange={(e) => setUserForm({ ...userForm, scope_type: e.target.value, store_ids: e.target.value === "store" ? userForm.store_ids : [] })} data-testid="user-scope-select">
                {meta.scope_types.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
              <input className="input" type="password" placeholder={userForm.id ? "New password (optional)" : "Password"} value={userForm.password} onChange={(e) => setUserForm({ ...userForm, password: e.target.value })} data-testid="user-password-input" />
              <label className="check-row"><input type="checkbox" checked={userForm.is_active} onChange={(e) => setUserForm({ ...userForm, is_active: e.target.checked })} data-testid="user-active-checkbox" /> Active</label>
              <label className="check-row"><input type="checkbox" checked={userForm.is_staff} onChange={(e) => setUserForm({ ...userForm, is_staff: e.target.checked })} data-testid="user-staff-checkbox" /> Staff admin</label>
              <button className="btn btn-cta" onClick={saveUser} disabled={!userForm.username || !userForm.role_id || (!userForm.id && !userForm.password)} data-testid="user-save-button"><Save size={15} /> Save user</button>
            </div>
            {userForm.scope_type === "store" && (
              <div className="toggle-grid" data-testid="user-store-picker">
                {meta.stores.map((s) => (
                  <button key={s.id} type="button" className={`toggle-chip ${userForm.store_ids.includes(s.id) ? "active" : ""}`} onClick={() => toggleStore(s.id)} data-testid={`user-store-toggle-${s.code}`}>{s.code} · {s.name}</button>
                ))}
              </div>
            )}
          </div>

          <div className="table-wrap">
            <table className="data" data-testid="users-table">
              <thead><tr><th>User</th><th>Role</th><th>Scope</th><th>Stores</th><th>Status</th><th /></tr></thead>
              <tbody>
                {loading ? <tr><td colSpan={6}>Loading…</td></tr> : users.map((u) => (
                  <tr key={u.id} data-testid={`user-row-${u.username}`}>
                    <td><b>{u.full_name || u.username}</b><div className="mono" style={{ fontSize: 12 }}>{u.username}</div></td>
                    <td>{u.role?.name ?? "—"}</td>
                    <td>{u.scope_label}</td>
                    <td>{storeLabel(u.stores)}</td>
                    <td><span className={`chip chip-${u.is_active ? "green" : "red"}`}>{u.is_active ? "Active" : "Inactive"}</span></td>
                    <td><button className="btn btn-sm" onClick={() => editUser(u)} data-testid={`edit-user-${u.username}`}><UserPlus size={13} /> Edit</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <>
          <div className="card section-card" data-testid="role-editor-card">
            <div className="toolbar" style={{ marginBottom: 12 }}>
              <h3 className="h3">{roleForm.id ? "Edit role" : "Create role"}</h3>
              <div className="spacer" />
              {roleForm.id ? <button className="btn btn-sm" onClick={() => setRoleForm(blankRole)} data-testid="role-editor-clear"><X size={14} /> New</button> : null}
            </div>
            <div className="form-grid wide-form">
              <input className="input" placeholder="Role code" value={roleForm.code} onChange={(e) => setRoleForm({ ...roleForm, code: e.target.value })} data-testid="role-code-input" />
              <input className="input" placeholder="Role name" value={roleForm.name} onChange={(e) => setRoleForm({ ...roleForm, name: e.target.value })} data-testid="role-name-input" />
              <input className="input" placeholder="Landing page" value={roleForm.landing_page} onChange={(e) => setRoleForm({ ...roleForm, landing_page: e.target.value })} data-testid="role-landing-input" />
              <input className="input" placeholder="Description" value={roleForm.description} onChange={(e) => setRoleForm({ ...roleForm, description: e.target.value })} data-testid="role-desc-input" />
              <label className="check-row"><input type="checkbox" checked={roleForm.is_active} onChange={(e) => setRoleForm({ ...roleForm, is_active: e.target.checked })} data-testid="role-active-checkbox" /> Active</label>
              <button className="btn btn-cta" onClick={saveRole} disabled={!roleForm.code || !roleForm.name || roleForm.nav_groups.length === 0} data-testid="role-save-button"><Save size={15} /> Save role</button>
            </div>
            <div className="toggle-grid" data-testid="role-nav-picker">
              {meta.nav_groups.map((key) => (
                <button key={key} type="button" className={`toggle-chip ${roleForm.nav_groups.includes(key) ? "active" : ""}`} onClick={() => toggleNav(key)} data-testid={`role-nav-toggle-${key}`}>{key.replace(/_/g, " ")}</button>
              ))}
            </div>
          </div>

          <div className="table-wrap">
            <table className="data" data-testid="roles-table">
              <thead><tr><th>Role</th><th>Landing</th><th>Nav groups</th><th className="num">Users</th><th>Status</th><th /></tr></thead>
              <tbody>
                {loading ? <tr><td colSpan={6}>Loading…</td></tr> : roles.map((r) => (
                  <tr key={r.id} data-testid={`role-row-${r.code}`}>
                    <td><b>{r.name}</b><div className="mono" style={{ fontSize: 12 }}>{r.code}{r.is_system ? " · system" : ""}</div></td>
                    <td className="mono">{r.landing_page}</td>
                    <td>{normalizeNavGroups(r.nav_groups).map((n) => <span key={n} className="chip chip-navy" style={{ marginRight: 5, marginBottom: 4 }}>{n}</span>)}</td>
                    <td className="num">{r.user_count}</td>
                    <td><span className={`chip chip-${r.is_active ? "green" : "red"}`}>{r.is_active ? "Active" : "Inactive"}</span></td>
                    <td><button className="btn btn-sm" onClick={() => editRole(r)} data-testid={`edit-role-${r.code}`}><ShieldCheck size={13} /> Edit</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
