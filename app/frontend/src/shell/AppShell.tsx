import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Bell, ChevronDown, Lock, LogOut, MapPin, Menu, Tag, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { useAuth } from "../auth/AuthContext";
import { api } from "../lib/api";
import { ThemeToggle } from "../theme/ThemeToggle";
import { GlobalSearch } from "./GlobalSearch";
import { headingOwning, isActiveFold, isActiveItem, sidebarRows, testId } from "./navConfig";
import type { NavFoldDef, NavItem, VisibleSection } from "./navConfig";
import { chipClass, contextKey, switcherModel } from "./unitSwitcher";
import type { SwitcherOption } from "./unitSwitcher";
import "./AppShell.css";

const SIDEBAR_WIDTH_KEY = "kdps-sidebar-width";
const NAV_ORDER_KEY = "kdps-nav-item-order";
const NAV_COLLAPSED_KEY = "kdps-nav-collapsed";
const MIN_SIDEBAR = 210;
const MAX_SIDEBAR = 390;

type DraggedItem = { sectionCode: string; to: string } | null;
type NavOrder = Record<string, string[]>;

function initials(name: string, fallback: string): string {
  const src = (name || fallback).trim();
  const parts = src.split(/\s+/);
  return (parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "");
}

/** The unit (or brand) the person is working in. Everything it offers comes
 *  from the server payload — see `unitSwitcher.ts`; this only renders it. */
function UnitSwitcher() {
  const { user, activeStore, activeBrand, setActiveStore, setActiveBrand } = useAuth();
  const [open, setOpen] = useState(false);
  if (!user) return null;
  const model = switcherModel(user, activeStore, activeBrand);

  function pick(option: SwitcherOption) {
    if (option.kind === "unit") setActiveStore(option.store);
    else if (option.kind === "brand") setActiveBrand(option.brand);
    else if (option.kind === "all-units") setActiveStore(null);
    else setActiveBrand(null);
    setOpen(false);
  }

  function isActive(option: SwitcherOption): boolean {
    if (option.kind === "unit") return activeStore?.id === option.store.id;
    if (option.kind === "brand") return activeBrand?.id === option.brand.id;
    if (option.kind === "all-units") return activeStore === null;
    return activeBrand === null;
  }

  if (model.locked) {
    return (
      <div className="switcher-btn locked" data-testid="store-switcher">
        <Lock size={14} />
        <span className="switcher-label">{model.label}</span>
        <span className={`chip ${chipClass(model.chip)}`}>{model.chip}</span>
      </div>
    );
  }

  return (
    <div className="switcher">
      <button className="switcher-btn" onClick={() => setOpen((o) => !o)} data-testid="store-switcher">
        {model.mode === "brands" ? <Tag size={15} /> : <MapPin size={15} />}
        <span className="switcher-label">{model.label}</span>
        <span className={`chip ${chipClass(model.chip)}`}>{model.chip}</span>
        <ChevronDown size={15} />
      </button>
      {open && (
        <>
          <div className="dropdown-backdrop" onClick={() => setOpen(false)} />
          <div className="dropdown" data-testid="store-switcher-menu">
            <div className="dropdown-head">
              {model.mode === "brands" ? "Context · brand" : "Context · store & GSTIN"}
            </div>
            {model.options.map((option) => (
              <button
                key={option.label}
                className={`dropdown-item ${isActive(option) ? "active" : ""}`}
                onClick={() => pick(option)}
                data-testid={
                  option.kind === "unit"
                    ? `store-option-${option.store.code}`
                    : option.kind === "brand"
                      ? `brand-option-${option.brand.code}`
                      : `option-${option.kind}`
                }
              >
                <span>{option.label}</span>
                <span className={`chip ${chipClass(option.chip)}`}>{option.chip}</span>
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

/** Anyone who decides an approval says so here, so the bell can recount.
 *
 *  A DOM event rather than a store: the bell and the inbox are the only two
 *  things that care, they are never mounted together outside the shell, and one
 *  line beats a context for a fact this small. */
export const APPROVALS_CHANGED = "kdps:approvals-changed";

export function announceApprovalsChanged() {
  window.dispatchEvent(new Event(APPROVALS_CHANGED));
}

/** The bell, told what it is ringing about.
 *
 *  It used to be a dead button with a permanent red dot: nothing to click, and a
 *  dot that said "something needs you" whether or not anything did. It now
 *  counts the documents actually waiting on this person's decision and opens the
 *  inbox — and shows nothing at all when there is nothing to show. */
function ApprovalsBell() {
  const [waiting, setWaiting] = useState<number | null>(null);
  // Re-counted on every navigation *and* whenever a decision is made, not once
  // per session: clearing the last item used to leave the bell insisting one
  // document was still waiting, right beside a page saying nothing was.
  const { pathname } = useLocation();
  useEffect(() => {
    function count() {
      api
        .get("/approvals/inbox")
        .then((r) => setWaiting(r.data?.length ?? 0))
        .catch(() => setWaiting(null));
    }
    count();
    window.addEventListener(APPROVALS_CHANGED, count);
    return () => window.removeEventListener(APPROVALS_CHANGED, count);
  }, [pathname]);
  const label = waiting
    ? `${waiting} document${waiting === 1 ? "" : "s"} waiting for your approval`
    : "Approvals inbox — nothing waiting for you";
  return (
    <Link to="/approvals" className="icon-btn" aria-label={label} title={label} data-testid="notifications">
      <Bell size={18} />
      {!!waiting && (
        <span className="bell-count" data-testid="notifications-count">
          {waiting > 9 ? "9+" : waiting}
        </span>
      )}
    </Link>
  );
}

function readNavOrder(): NavOrder {
  try {
    return JSON.parse(localStorage.getItem(NAV_ORDER_KEY) || "{}") as NavOrder;
  } catch {
    return {};
  }
}

/** Section codes the person has folded away, remembered across sessions.
 *
 *  Thirteen sections, all of them open, put ~45 links in front of an owner and
 *  pushed Money, Reports and Setup below the fold on a laptop: the sidebar was
 *  a list to scroll rather than a map to read. Folding is the ERP norm for a
 *  reason. Everything stays open by default, so nobody loses a link they had. */
function readCollapsed(): Record<string, true> {
  try {
    return JSON.parse(localStorage.getItem(NAV_COLLAPSED_KEY) || "{}") as Record<string, true>;
  } catch {
    return {};
  }
}

function orderedItems(code: string, items: NavItem[], order: NavOrder): NavItem[] {
  const saved = order[code] ?? [];
  const known = new Set(items.map((i) => i.to));
  const byPath = new Map(items.map((i) => [i.to, i]));
  return [
    ...saved.filter((to) => known.has(to)).map((to) => byPath.get(to)!),
    ...items.filter((i) => !saved.includes(i.to)),
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
  const { pathname } = useLocation();
  const [navOrder, setNavOrder] = useState<NavOrder>(() => readNavOrder());
  const [collapsed, setCollapsed] = useState<Record<string, true>>(() => readCollapsed());
  const [dragged, setDragged] = useState<DraggedItem>(null);

  // Landing inside a folded section unfolds it: the sidebar must always be able
  // to show where you are, however you got there (search, deep link, redirect).
  // The heading to unfold is the one this person's sidebar draws the screen
  // under, which is not always the section that owns it - a store person on
  // Attendance is standing under Home.
  const roleCode = user?.role?.code ?? "";
  useEffect(() => {
    const heading = headingOwning(pathname, roleCode);
    if (!heading || !collapsed[heading]) return;
    setCollapsed((current) => {
      const next = { ...current };
      delete next[heading];
      localStorage.setItem(NAV_COLLAPSED_KEY, JSON.stringify(next));
      return next;
    });
  }, [pathname, collapsed, roleCode]);

  if (!user) return null;
  const rows = sidebarRows(user);

  function toggleSection(code: string) {
    setCollapsed((current) => {
      const next = { ...current };
      if (next[code]) delete next[code];
      else next[code] = true;
      localStorage.setItem(NAV_COLLAPSED_KEY, JSON.stringify(next));
      return next;
    });
  }

  function moveItem(section: VisibleSection, targetTo: string) {
    const code = section.def.code;
    if (!dragged || dragged.sectionCode !== code || dragged.to === targetTo) return;
    const current = orderedItems(code, section.items, navOrder).map((i) => i.to);
    const from = current.indexOf(dragged.to);
    const to = current.indexOf(targetTo);
    if (from < 0 || to < 0) return;
    const next = [...current];
    const [picked] = next.splice(from, 1);
    next.splice(to, 0, picked);
    const updated = { ...navOrder, [code]: next };
    setNavOrder(updated);
    localStorage.setItem(NAV_ORDER_KEY, JSON.stringify(updated));
  }

  /** A row that is simply a link: a section with one visible item, or a fold,
   *  whose whole point is to be one line. */
  function oneLineRow(row: {
    key: string;
    icon: LucideIcon;
    layer: string;
    to: string;
    label: string;
    active: boolean;
    testId: string;
  }) {
    const Icon = row.icon;
    return (
      <div className="nav-group" key={row.key}>
        <div className="nav-group-head">
          <span className="nav-ic" style={{ color: `var(--layer-${row.layer})` }}>
            <Icon size={16} />
          </span>
          <Link
            to={row.to}
            onClick={onNavigate}
            aria-current={row.active ? "page" : undefined}
            className={`nav-grouplink ${row.active ? "active" : ""}`}
            data-testid={row.testId}
          >
            {row.label}
          </Link>
        </div>
      </div>
    );
  }

  /** One section: its head, plus its items when it has more than one. */
  function renderSection(s: VisibleSection) {
    const Icon = s.def.icon;
    const items = orderedItems(s.def.code, s.items, navOrder);
    // One visible item ⇒ the section *is* that link, because a heading you must
    // open to reach a single line is a click that buys nothing. It is a tidying,
    // not a shaping: what a persona's sidebar *contains* is the layout's job
    // (`applyLayout` in the manifest), never this.
    const open = !collapsed[s.def.code];
    const holdsActive = items.some((i) => isActiveItem(i, pathname));
    if (items.length === 1) {
      return oneLineRow({
        key: s.def.code,
        icon: Icon,
        layer: s.def.layer,
        to: items[0].to,
        label: s.label,
        active: isActiveItem(items[0], pathname),
        testId: `nav-${s.def.code}`,
      });
    }
    return (
      <div className="nav-group" key={s.def.code}>
        {(
          <button
            type="button"
            className="nav-group-head nav-group-toggle"
            aria-expanded={open}
            onClick={() => toggleSection(s.def.code)}
            data-testid={`nav-section-${s.def.code}`}
          >
            <span className="nav-ic" style={{ color: `var(--layer-${s.def.layer})` }}>
              <Icon size={16} />
            </span>
            <span className={`nav-group-label ${holdsActive ? "holds-active" : ""}`}>
              {s.label}
            </span>
            <ChevronDown size={14} className={`nav-chev ${open ? "open" : ""}`} />
          </button>
        )}
        {open && (
          <div className="nav-items">
            {items.map((it) => {
              const active = isActiveItem(it, pathname);
              return (
                <Link
                  key={it.to}
                  to={it.to}
                  draggable
                  onDragStart={() => setDragged({ sectionCode: s.def.code, to: it.to })}
                  onDragEnd={() => setDragged(null)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault();
                    moveItem(s, it.to);
                  }}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  className={`nav-item ${active ? "active" : ""}`}
                  data-testid={testId(s.def.code, it)}
                >
                  {it.label}
                </Link>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  /** A fold: one link to one page whose tabs are the screens it folds. It draws
   *  exactly like a one-item section, because that is what it is to the reader
   *  - the dividing happens inside the page, never here (D10 §1). */
  function renderFold(fold: NavFoldDef) {
    return oneLineRow({
      key: fold.to,
      icon: fold.icon,
      layer: fold.layer,
      to: fold.to,
      label: fold.heading,
      active: isActiveFold(fold, pathname),
      testId: `nav-fold-${fold.heading.toLowerCase()}`,
    });
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
        {rows.map((row) =>
          row.kind === "section" ? renderSection(row.section) : renderFold(row.fold),
        )}
      </nav>
      <div className="sidebar-resizer" onPointerDown={onResizeStart} data-testid="sidebar-resizer" />
    </aside>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { activeStore, activeBrand } = useAuth();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const saved = Number(localStorage.getItem(SIDEBAR_WIDTH_KEY));
    return Number.isFinite(saved) && saved >= MIN_SIDEBAR && saved <= MAX_SIDEBAR ? saved : 258;
  });

  // The drag in progress, or null. Holding it as state means the listeners are
  // torn down by the effect's cleanup rather than by the pointerup handler — a
  // drag released outside the window, cancelled by the OS, or interrupted by a
  // logout never fires pointerup, and used to leave a live pointermove listener
  // re-rendering the whole shell on every mouse move for the life of the page.
  const [resizeFrom, setResizeFrom] = useState<{ x: number; width: number } | null>(null);

  useEffect(() => {
    if (!resizeFrom) return;
    const drag = new AbortController();
    const { signal } = drag;
    let latestWidth = resizeFrom.width;
    document.body.classList.add("sidebar-resizing");
    const onMove = (ev: PointerEvent) => {
      latestWidth = Math.min(
        MAX_SIDEBAR,
        Math.max(MIN_SIDEBAR, resizeFrom.width + ev.clientX - resizeFrom.x),
      );
      setSidebarWidth(latestWidth);
    };
    const onEnd = () => setResizeFrom(null);
    document.addEventListener("pointermove", onMove, { signal });
    document.addEventListener("pointerup", onEnd, { signal });
    document.addEventListener("pointercancel", onEnd, { signal });
    return () => {
      drag.abort();
      document.body.classList.remove("sidebar-resizing");
      localStorage.setItem(SIDEBAR_WIDTH_KEY, String(latestWidth));
    };
  }, [resizeFrom]);

  function startResize(e: React.PointerEvent<HTMLDivElement>) {
    e.preventDefault();
    setResizeFrom({ x: e.clientX, width: sidebarWidth });
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
          <UnitSwitcher />
          <GlobalSearch />
          <div className="topbar-right">
            <ApprovalsBell />
            <UserMenu />
          </div>
        </header>
        {/* Keyed on the working context: switching unit remounts the page, so
            every screen refetches under the new unit instead of leaving the
            previous store's numbers on screen. */}
        <main className="content" key={contextKey(activeStore, activeBrand)}>
          {children}
        </main>
      </div>
    </div>
  );
}
