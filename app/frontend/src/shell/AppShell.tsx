import { Fragment, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Bell, ChevronDown, ChevronRight, Lock, LogOut, MapPin, Menu, Tag, X } from "lucide-react";

import { useAuth } from "../auth/AuthContext";
import { ThemeToggle } from "../theme/ThemeToggle";
import { GlobalSearch } from "./GlobalSearch";
import { isActiveItem, itemPath, layoutSidebar, visibleSections } from "./navConfig";
import type { NavItem, NavRow, VisibleSection } from "./navConfig";
import { chipClass, contextKey, switcherModel } from "./unitSwitcher";
import type { SwitcherOption } from "./unitSwitcher";
import "./AppShell.css";

const SIDEBAR_WIDTH_KEY = "kdps-sidebar-width";
const NAV_ORDER_KEY = "kdps-nav-item-order";
const MORE_OPEN_KEY = "kdps-sidebar-more-open";
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

function readNavOrder(): NavOrder {
  try {
    return JSON.parse(localStorage.getItem(NAV_ORDER_KEY) || "{}") as NavOrder;
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
  const [dragged, setDragged] = useState<DraggedItem>(null);
  // "More" holds the sections a persona uses now and then, collapsed until
  // asked for. The choice sticks the way the sidebar's width does.
  const [moreOpen, setMoreOpen] = useState(() => localStorage.getItem(MORE_OPEN_KEY) === "1");
  if (!user) return null;
  // What this person may reach, then how their persona reads it (#96). The
  // second step can only rearrange the first — never add to it.
  const bands = layoutSidebar(visibleSections(user), user.role?.code ?? "");

  function toggleMore() {
    setMoreOpen((open) => {
      localStorage.setItem(MORE_OPEN_KEY, open ? "0" : "1");
      return !open;
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

  /** The one line a screen gets, wherever it sits. */
  function itemTestId(section: VisibleSection, item: NavItem): string {
    return `nav-${section.def.code}-${itemPath(item).split("/").pop() || "home"}`;
  }

  const slug = (label: string) => label.toLowerCase().replace(/\s+/g, "-");

  /** A section, as it has always rendered: its name, then its items.
   *
   *  Inside a group (`nested`) it shows its items only while you are in it, and
   *  otherwise stands as a single line into its own first screen. Three
   *  sections under Inventory would be fifteen lines expanded — longer than the
   *  flat list the grouping was meant to shorten — and one click still lands on
   *  Receive (GRN), Transfers or Stock on Hand, with the rest of the section
   *  unfolding once you are there. */
  function sectionBlock(s: VisibleSection, nested = false) {
    const Icon = s.def.icon;
    const items = orderedItems(s.def.code, s.items, navOrder);
    // One visible item ⇒ the section *is* that link, rather than a heading over
    // a single line. (Shortening the store's screen is the grouping's job, not
    // this rule's — see `layoutSidebar`.)
    const single = items.length === 1 || (nested && !s.items.some((i) => isActiveItem(i, pathname)));
    return (
      <div className="nav-group" key={s.def.code}>
        <div className="nav-group-head">
          <span className="nav-ic" style={{ color: `var(--layer-${s.def.layer})` }}>
            <Icon size={16} />
          </span>
          {single ? (
            <Link
              to={items[0].to}
              onClick={onNavigate}
              aria-current={isActiveItem(items[0], pathname) ? "page" : undefined}
              className={`nav-grouplink ${isActiveItem(items[0], pathname) ? "active" : ""}`}
              data-testid={`nav-${s.def.code}`}
            >
              {s.label}
            </Link>
          ) : (
            <span className="nav-group-label">{s.label}</span>
          )}
        </div>
        {!single && (
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
                  data-testid={itemTestId(s, it)}
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

  /** Is the screen you are on inside this row? */
  function rowIsActive(row: NavRow): boolean {
    if (row.kind === "item") return isActiveItem(row.item, pathname);
    const sections = row.kind === "group" ? row.sections : [row.section];
    return sections.some((s) => s.items.some((i) => isActiveItem(i, pathname)));
  }

  function navRow(row: NavRow) {
    if (row.kind === "section") return sectionBlock(row.section);
    if (row.kind === "group") {
      // A heading over sections, each of which keeps its own name — "Transfer"
      // reads "Transfer" inside Inventory too.
      const Icon = row.icon;
      return (
        <div className="nav-group" key={row.key}>
          <div className="nav-group-head">
            <span className="nav-ic" style={{ color: `var(--layer-${row.layer})` }}>
              <Icon size={16} />
            </span>
            <span className="nav-group-label">{row.label}</span>
          </div>
          <div className="nav-nested" data-testid={`nav-group-${slug(row.label)}`}>
            {row.sections.map((s) => sectionBlock(s, true))}
          </div>
        </div>
      );
    }
    // One item of a section, standing as its own heading.
    const Icon = row.section.def.icon;
    const active = isActiveItem(row.item, pathname);
    return (
      <div className="nav-group" key={row.key}>
        <div className="nav-group-head">
          <span className="nav-ic" style={{ color: `var(--layer-${row.section.def.layer})` }}>
            <Icon size={16} />
          </span>
          <Link
            to={row.item.to}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={`nav-grouplink ${active ? "active" : ""}`}
            data-testid={itemTestId(row.section, row.item)}
          >
            {row.item.label}
          </Link>
        </div>
      </div>
    );
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
        {bands.map((band, i) =>
          band.collapsible ? (
            <div className="nav-band" key={band.label ?? i}>
              {/* Collapsed, the band can be hiding the screen you are on — so
                  it carries the highlight itself and the sidebar never goes
                  dark under you. It does not spring open: the daily list is
                  what a store person should meet each morning. */}
              <button
                type="button"
                className={`nav-band-toggle ${moreOpen ? "open" : ""} ${
                  !moreOpen && band.rows.some(rowIsActive) ? "active" : ""
                }`}
                aria-expanded={moreOpen}
                onClick={toggleMore}
                data-testid={`nav-band-${slug(band.label ?? "more")}`}
              >
                <ChevronRight size={14} />
                <span>{band.label}</span>
              </button>
              {moreOpen && band.rows.map(navRow)}
            </div>
          ) : (
            // No wrapper: an unlabelled band is simply the top of the list, and
            // every persona without a shape of its own renders exactly as before.
            <Fragment key={band.label ?? i}>{band.rows.map(navRow)}</Fragment>
          ),
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
            <button className="icon-btn" data-testid="notifications">
              <Bell size={18} />
              <span className="dot" />
            </button>
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
