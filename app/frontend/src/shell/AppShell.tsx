import { useState } from "react";
import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { Bell, ChevronDown, Lock, LogOut, MapPin, Menu, Search, X } from "lucide-react";

import { useAuth } from "../auth/AuthContext";
import type { Store } from "../auth/AuthContext";
import { ThemeToggle } from "../theme/ThemeToggle";
import { NAV } from "./navConfig";
import type { NavGroup, NavItem } from "./navConfig";
import "./AppShell.css";

const SIDEBAR_WIDTH_KEY = "kdps-sidebar-width";
const NAV_ORDER_KEY = "kdps-nav-item-order";
const MIN_SIDEBAR = 210;
const MAX_SIDEBAR = 390;

type DraggedItem = { groupKey: string; to: string } | null;
type NavOrder = Record<string, string[]>;

function initials(name: string, fallback: string): string {
  const src = (name || fallback).trim();
  const parts = src.split(/\s+/);
  return (parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "");
}

function StoreSwitcher() {
  const { user, activeStore, setActiveStore } = useAuth();
  const [open, setOpen] = useState(false);
  if (!user) return null;
  const canSeeAll = user.scope_type === "all" || user.scope_type === "entity";
  const label = activeStore ? `${activeStore.code} · ${activeStore.name}` : "All stores";
  const state = activeStore ? activeStore.state_name : "Network";
  const locked = !canSeeAll && user.stores.length <= 1;

  function pick(s: Store | null) {
    setActiveStore(s);
    setOpen(false);
  }

  if (locked) {
    return (
      <div className="switcher-btn locked" data-testid="store-switcher">
        <Lock size={14} />
        <span className="switcher-label">{label}</span>
        <span className={`chip chip-${state === "Bihar" ? "amber" : "blue"}`}>{state}</span>
      </div>
    );
  }

  return (
    <div className="switcher">
      <button className="switcher-btn" onClick={() => setOpen((o) => !o)} data-testid="store-switcher">
        <MapPin size={15} />
        <span className="switcher-label">{label}</span>
        <span className={`chip chip-${state === "Bihar" ? "amber" : state === "Jharkhand" ? "blue" : "navy"}`}>
          {state}
        </span>
        <ChevronDown size={15} />
      </button>
      {open && (
        <>
          <div className="dropdown-backdrop" onClick={() => setOpen(false)} />
          <div className="dropdown" data-testid="store-switcher-menu">
            <div className="dropdown-head">Context · store &amp; GSTIN</div>
            {canSeeAll && (
              <button className="dropdown-item" onClick={() => pick(null)}>
                <span>All stores (network)</span>
                <span className="chip chip-navy">Both states</span>
              </button>
            )}
            {user.stores.map((s) => (
              <button
                key={s.id}
                className={`dropdown-item ${activeStore?.id === s.id ? "active" : ""}`}
                onClick={() => pick(s)}
                data-testid={`store-option-${s.code}`}
              >
                <span>
                  <b>{s.code}</b> · {s.name}
                </span>
                <span className={`chip chip-${s.state_name === "Bihar" ? "amber" : "blue"}`}>
                  {s.state_name}
                </span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function UserMenu() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  if (!user) return null;
  return (
    <div className="usermenu">
      <button className="user-btn" onClick={() => setOpen((o) => !o)} data-testid="user-menu">
        <span className="avatar">{initials(user.full_name, user.username).toUpperCase()}</span>
        <span className="user-meta">
          <span className="user-name">{user.full_name || user.username}</span>
          <span className="user-role">{user.role?.name ?? (user.is_superuser ? "Administrator" : "")}</span>
        </span>
        <ChevronDown size={15} />
      </button>
      {open && (
        <>
          <div className="dropdown-backdrop" onClick={() => setOpen(false)} />
          <div className="dropdown dropdown-right" data-testid="user-menu-dropdown">
            <div className="dropdown-head">{user.username} · {user.scope_label}</div>
            <div className="dropdown-theme" onClick={(e) => e.stopPropagation()}>
              <span>Theme</span>
              <ThemeToggle />
            </div>
            <button
              className="dropdown-item"
              onClick={() => {
                logout();
                navigate("/login");
              }}
              data-testid="logout-button"
            >
              <span>Sign out</span>
              <LogOut size={15} />
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function readNavOrder(): NavOrder {
  try {
    return JSON.parse(localStorage.getItem(NAV_ORDER_KEY) || "{}") as NavOrder;
  } catch {
    return {};
  }
}

function orderedItems(group: NavGroup, order: NavOrder): NavItem[] {
  const saved = order[group.key] ?? [];
  const known = new Set(group.items.map((i) => i.to));
  const byPath = new Map(group.items.map((i) => [i.to, i]));
  return [
    ...saved.filter((to) => known.has(to)).map((to) => byPath.get(to)!),
    ...group.items.filter((i) => !saved.includes(i.to)),
  ];
}

function Sidebar({
  width,
  onResizeStart,
  mobileOpen,
  onNavigate,
}: {
  width: number;
  onResizeStart: (e: React.PointerEvent<HTMLDivElement>) => void;
  mobileOpen: boolean;
  onNavigate: () => void;
}) {
  const { user } = useAuth();
  const [navOrder, setNavOrder] = useState<NavOrder>(() => readNavOrder());
  const [dragged, setDragged] = useState<DraggedItem>(null);
  if (!user) return null;
  const groups = NAV.filter((g) => user.nav_groups.includes(g.key));

  function moveItem(group: NavGroup, targetTo: string) {
    if (!dragged || dragged.groupKey !== group.key || dragged.to === targetTo) return;
    const current = orderedItems(group, navOrder).map((i) => i.to);
    const from = current.indexOf(dragged.to);
    const to = current.indexOf(targetTo);
    if (from < 0 || to < 0) return;
    const next = [...current];
    const [picked] = next.splice(from, 1);
    next.splice(to, 0, picked);
    const updated = { ...navOrder, [group.key]: next };
    setNavOrder(updated);
    localStorage.setItem(NAV_ORDER_KEY, JSON.stringify(updated));
  }

  return (
    <aside className={`sidebar ${mobileOpen ? "mobile-open" : ""}`} style={{ width }} data-testid="app-sidebar">
      <div className="brand">
        <span className="brand-mark">K</span>
        <span className="brand-text">
          <b>KDPS</b>
          <small>Operating System</small>
        </span>
      </div>
      <nav className="nav" data-testid="sidebar-nav">
        {groups.map((g) => {
          const Icon = g.icon;
          const items = orderedItems(g, navOrder).filter(
            (it) => !it.roles || user.is_superuser || it.roles.includes(user.role?.code ?? ""),
          );
          const single = items.length === 1;
          return (
            <div className="nav-group" key={g.key}>
              <div className="nav-group-head">
                <span className="nav-ic" style={{ color: `var(--layer-${g.layer})` }}>
                  <Icon size={16} />
                </span>
                {single ? (
                  <NavLink
                    to={items[0].to}
                    end
                    onClick={onNavigate}
                    className={({ isActive }) => `nav-grouplink ${isActive ? "active" : ""}`}
                    data-testid={`nav-${g.key}`}
                  >
                    {g.label}
                  </NavLink>
                ) : (
                  <span className="nav-group-label">{g.label}</span>
                )}
              </div>
              {!single && (
                <div className="nav-items">
                  {items.map((it) => (
                    <NavLink
                      key={it.to}
                      to={it.to}
                      draggable
                      onDragStart={() => setDragged({ groupKey: g.key, to: it.to })}
                      onDragEnd={() => setDragged(null)}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={(e) => {
                        e.preventDefault();
                        moveItem(g, it.to);
                      }}
                      onClick={onNavigate}
                      className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
                      data-testid={`nav-${g.key}-${it.to.split("/").pop()}`}
                    >
                      {it.label}
                    </NavLink>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </nav>
      <div className="sidebar-resizer" onPointerDown={onResizeStart} data-testid="sidebar-resizer" />
    </aside>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const saved = Number(localStorage.getItem(SIDEBAR_WIDTH_KEY));
    return Number.isFinite(saved) && saved >= MIN_SIDEBAR && saved <= MAX_SIDEBAR ? saved : 258;
  });

  function startResize(e: React.PointerEvent<HTMLDivElement>) {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = sidebarWidth;
    let latestWidth = startWidth;
    document.body.classList.add("sidebar-resizing");
    const onMove = (ev: PointerEvent) => {
      const next = Math.min(MAX_SIDEBAR, Math.max(MIN_SIDEBAR, startWidth + ev.clientX - startX));
      latestWidth = next;
      setSidebarWidth(next);
    };
    const onUp = () => {
      document.body.classList.remove("sidebar-resizing");
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      localStorage.setItem(SIDEBAR_WIDTH_KEY, String(latestWidth));
    };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
  }

  return (
    <div className="shell">
      <Sidebar
        width={sidebarWidth}
        onResizeStart={startResize}
        mobileOpen={mobileNavOpen}
        onNavigate={() => setMobileNavOpen(false)}
      />
      {mobileNavOpen && (
        <div className="sidebar-backdrop" onClick={() => setMobileNavOpen(false)} data-testid="sidebar-backdrop" />
      )}
      <div className="main">
        <header className="topbar">
          <button
            className="icon-btn menu-btn"
            onClick={() => setMobileNavOpen((o) => !o)}
            aria-label={mobileNavOpen ? "Close navigation" : "Open navigation"}
            data-testid="mobile-nav-toggle"
          >
            {mobileNavOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
          <StoreSwitcher />
          <div className="topbar-search">
            <Search size={15} />
            <input placeholder="Search documents, items, vendors…" data-testid="global-search" />
          </div>
          <div className="topbar-right">
            <button className="icon-btn" data-testid="notifications">
              <Bell size={18} />
              <span className="dot" />
            </button>
            <UserMenu />
          </div>
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
