import { useState } from "react";
import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { Bell, ChevronDown, LogOut, MapPin, Search } from "lucide-react";

import { useAuth } from "../auth/AuthContext";
import type { Store } from "../auth/AuthContext";
import { NAV } from "./navConfig";
import "./AppShell.css";

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

  function pick(s: Store | null) {
    setActiveStore(s);
    setOpen(false);
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

function Sidebar() {
  const { user } = useAuth();
  if (!user) return null;
  const groups = NAV.filter((g) => user.nav_groups.includes(g.key));
  return (
    <aside className="sidebar">
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
          const single = g.items.length === 1;
          return (
            <div className="nav-group" key={g.key}>
              <div className="nav-group-head">
                <span className="nav-ic" style={{ color: `var(--layer-${g.layer})` }}>
                  <Icon size={16} />
                </span>
                {single ? (
                  <NavLink
                    to={g.items[0].to}
                    end
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
                  {g.items.map((it) => (
                    <NavLink
                      key={it.to}
                      to={it.to}
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
    </aside>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="shell">
      <Sidebar />
      <div className="main">
        <header className="topbar">
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
