import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ChevronDown, ChevronLeft, Lock, LogOut, MapPin, Menu, Tag, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { useAuth } from "../auth/AuthContext";
import { HostedPageContext } from "../components/PageHeader";
import { ThemeToggle } from "../theme/ThemeToggle";
import { GlobalSearch } from "./GlobalSearch";
import { NotificationBell } from "./NotificationBell";
import {
  headingOwning,
  isActiveFold,
  isActiveItem,
  isOneLineRow,
  itemPath,
  sectionTabsFor,
  sidebarRows,
  stripOwning,
  testId,
} from "./navConfig";
import type { NavFoldDef, NavItem, NavRow, VisibleSection } from "./navConfig";
import { chipClass, contextKey, switcherModel } from "./unitSwitcher";
import type { SwitcherOption } from "./unitSwitcher";
import "./AppShell.css";

const SIDEBAR_WIDTH_KEY = "kdps-sidebar-width";
const NAV_ORDER_KEY = "kdps-nav-item-order";
const NAV_COLLAPSED_KEY = "kdps-nav-collapsed";
const RAIL_KEY = "kdps-sidebar-rail";
// Kept in step with `.rail-flyout`'s `max-height` in AppShell.css.
const FLYOUT_MAX_HEIGHT = 420;
const MIN_SIDEBAR = 210;
const MAX_SIDEBAR = 390;
const RAIL_WIDTH = 64;

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

/** Rail state, remembered on this device (device-scoped, not per-person - the
 *  issue's own AC, over `design.md`'s "new localStorage key" and the grill's
 *  "per person": two of three agree and the AC is what QA drives). Separate
 *  from `SIDEBAR_WIDTH_KEY`: collapsing must never overwrite the dragged
 *  width, so expanding again restores it for free. */
function readRailCollapsed(): boolean {
  try {
    return localStorage.getItem(RAIL_KEY) === "1";
  } catch {
    return false;
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
  const [railCollapsed, setRailCollapsed] = useState<boolean>(() => readRailCollapsed());
  // Which multi-item section's flyout is open, by section code, or none. Only
  // ever set in rail mode - the mobile drawer and the expanded sidebar have no
  // flyout to close.
  const [openFlyout, setOpenFlyout] = useState<string | null>(null);
  // Where the open flyout's popover renders, in viewport coordinates. `.sidebar`
  // scrolls (`overflow-y: auto`), which per the CSS spec forces its `overflow-x`
  // to compute as `auto` too - a popover positioned beside the rail would be
  // clipped by that, invisibly, if it stayed a normal descendant. It is
  // portaled to `document.body` instead and placed by measuring the trigger,
  // so the sidebar's own scrolling can never clip it.
  const [flyoutAt, setFlyoutAt] = useState<{ top: number; left: number } | null>(null);
  const flyoutTriggerRef = useRef<HTMLButtonElement>(null);
  const flyoutPopoverRef = useRef<HTMLDivElement | null>(null);

  // The mobile drawer must never inherit the rail, even when it is mounted
  // mid-collapse: this is the one expression that keeps AC4 true at both
  // breakpoints, rather than leaving it to CSS to hide what the render kept.
  const rail = railCollapsed && !mobileOpen;

  function toggleRail() {
    const next = !railCollapsed;
    localStorage.setItem(RAIL_KEY, next ? "1" : "0");
    setRailCollapsed(next);
    setOpenFlyout(null);
  }

  // Positioned from the trigger each time, not just once: `.sidebar` scrolls
  // and the window resizes independently of React re-rendering, so a
  // position measured only on open goes stale under the trigger. Clamped to
  // the popover's own measured height so it never renders below the fold - a
  // `position: fixed` box can't be scrolled into view. Before the popover has
  // ever mounted (nothing to measure yet) `FLYOUT_MAX_HEIGHT` stands in as a
  // conservative ceiling; `popoverMounted` below replaces it with the real
  // height the moment the portal is in the DOM.
  const place = useCallback(() => {
    const trigger = flyoutTriggerRef.current;
    if (!trigger) return;
    const margin = 8;
    const rect = trigger.getBoundingClientRect();
    const height = flyoutPopoverRef.current?.offsetHeight ?? FLYOUT_MAX_HEIGHT;
    const maxTop = window.innerHeight - height - margin;
    const top = Math.max(margin, Math.min(rect.top, maxTop));
    const left = rect.right + margin;
    setFlyoutAt((current) => (current && current.top === top && current.left === left ? current : { top, left }));
  }, []);

  useEffect(() => {
    if (!openFlyout) {
      setFlyoutAt(null);
      return;
    }
    place();
    window.addEventListener("resize", place);
    document.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      document.removeEventListener("scroll", place, true);
    };
  }, [openFlyout, place]);

  // Fires once the popover actually mounts, so `place` can re-clamp against
  // its real height instead of the `FLYOUT_MAX_HEIGHT` ceiling it had to
  // guess with before anything existed to measure.
  const popoverMounted = useCallback(
    (node: HTMLDivElement | null) => {
      flyoutPopoverRef.current = node;
      if (node) place();
    },
    [place],
  );

  // Outside click and Esc close the open flyout - the same pattern every other
  // popup in this shell uses (`NotificationBell`'s bell-wrap), checked against
  // both halves of it: the trigger stayed in the sidebar, the popover is
  // portaled out to `document.body`, and neither alone is "the flyout".
  useEffect(() => {
    if (!openFlyout) return;
    const off = new AbortController();
    const { signal } = off;
    document.addEventListener(
      "pointerdown",
      (e) => {
        const target = e.target as Node;
        if (flyoutTriggerRef.current?.contains(target)) return;
        if (flyoutPopoverRef.current?.contains(target)) return;
        setOpenFlyout(null);
      },
      { signal },
    );
    document.addEventListener(
      "keydown",
      (e) => {
        if (e.key === "Escape") setOpenFlyout(null);
      },
      { signal },
    );
    return () => off.abort();
  }, [openFlyout]);

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
   *  whose whole point is to be one line. In the rail this draws as the icon
   *  alone, with the row's name as a native tooltip (design.md:96-98: no
   *  tooltip library) - the same link, the same gate, just narrower. */
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
    if (rail) {
      return (
        <Link
          key={row.key}
          to={row.to}
          onClick={onNavigate}
          aria-current={row.active ? "page" : undefined}
          title={row.label}
          className={`rail-link ${row.active ? "active" : ""}`}
          data-testid={row.testId}
        >
          <span className="nav-ic" style={{ color: `var(--layer-${row.layer})` }}>
            <Icon size={16} />
          </span>
        </Link>
      );
    }
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

  /** A multi-item section's rail row: an icon button that opens a flyout
   *  beside the rail, listing exactly the items `renderSection` would have
   *  drawn under the section head - `orderedItems`'s own output, never
   *  re-derived (navConfig.ts:543-544). Only a non-store persona ever reaches
   *  this: every store row is one-line (see the isOneLineRow test), so the
   *  flyout never renders for a store login (D10 §1). */
  function railFlyoutSection(s: VisibleSection, items: NavItem[], holdsActive: boolean) {
    const Icon = s.def.icon;
    const open = openFlyout === s.def.code;
    return (
      <div className="rail-flyout-wrap" key={s.def.code}>
        <button
          type="button"
          ref={open ? flyoutTriggerRef : undefined}
          className={`rail-link rail-flyout-trigger ${holdsActive ? "active" : ""}`}
          title={s.label}
          aria-expanded={open}
          onClick={() => setOpenFlyout((current) => (current === s.def.code ? null : s.def.code))}
          data-testid={`nav-section-${s.def.code}`}
        >
          <span className="nav-ic" style={{ color: `var(--layer-${s.def.layer})` }}>
            <Icon size={16} />
          </span>
        </button>
        {open &&
          flyoutAt &&
          createPortal(
            <div
              className="rail-flyout"
              ref={popoverMounted}
              style={{ top: flyoutAt.top, left: flyoutAt.left }}
              data-testid={`nav-flyout-${s.def.code}`}
            >
              <div className="rail-flyout-head">{s.label}</div>
              {items.map((it) => {
                const active = isActiveItem(it, pathname);
                return (
                  <Link
                    key={it.to}
                    to={it.to}
                    onClick={() => {
                      setOpenFlyout(null);
                      onNavigate();
                    }}
                    aria-current={active ? "page" : undefined}
                    className={`nav-item ${active ? "active" : ""}`}
                    data-testid={testId(s.def.code, it)}
                  >
                    {it.label}
                  </Link>
                );
              })}
            </div>,
            document.body,
          )}
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
    const row: NavRow = { kind: "section", key: s.def.code, section: s };
    if (isOneLineRow(row)) {
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
    if (rail) return railFlyoutSection(s, items, holdsActive);
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

  /** A strip: one link into the section's own first screen. Its other screens
   *  are the tab row `SectionTabsProvider` puts on those screens - so, like a
   *  fold, the dividing happens inside the page and never here (D10 §1). */
  function renderStrip(row: Extract<NavRow, { kind: "strip" }>) {
    return oneLineRow({
      key: row.key,
      icon: row.def.icon,
      layer: row.def.layer,
      // The first tab this person can see - never a screen access already hid.
      to: row.tabs[0].to,
      label: row.label,
      // Lit wherever this persona's sidebar draws the screen under this row -
      // including a screen of the section the strip lists no tab for.
      active: stripOwning(pathname, roleCode) === row.strip,
      testId: `nav-strip-${row.strip.section}`,
    });
  }

  return (
    <aside
      className={`sidebar ${mobileOpen ? "mobile-open" : ""} ${rail ? "rail" : ""}`}
      // Rail overrides only what this element renders at; `sidebarWidth` in
      // AppShell is untouched, so expanding again restores the dragged width
      // for free (design.md:98).
      style={{ width: rail ? RAIL_WIDTH : width }}
      data-testid="app-sidebar"
    >
      <div className="brand">
        <span className="brand-mark">K</span>
        <span className="brand-text">
          <b>KDPS</b>
          <small>Operating System</small>
        </span>
      </div>
      <nav className="nav" data-testid="sidebar-nav">
        {rows.map((row) =>
          row.kind === "section"
            ? renderSection(row.section)
            : row.kind === "fold"
              ? renderFold(row.fold)
              : renderStrip(row),
        )}
      </nav>
      <div className="sidebar-resizer" onPointerDown={onResizeStart} data-testid="sidebar-resizer" />
      <button
        type="button"
        className="sidebar-rail-toggle"
        onClick={toggleRail}
        aria-label={rail ? "Expand sidebar" : "Collapse sidebar"}
        data-testid="sidebar-rail-toggle"
      >
        <ChevronLeft size={16} className={`rail-chev ${rail ? "flipped" : ""}`} />
      </button>
    </aside>
  );
}

/** The tab row for a stripped section, put on the section's own screens (#227).
 *
 *  The screens are untouched: they render their own `PageHeader`, and this
 *  provides the `HostedPageContext` that header already knows how to draw - the
 *  same route the Inventory fold uses. Folding a section therefore never means
 *  editing the screens inside it.
 *
 *  Three rules, all of them from the grill:
 *   · The tabs are the ones the *sidebar* would have drawn, so a strip can never
 *     offer a screen access hid.
 *   · One surviving tab draws no row at all - a strip of one is not a choice.
 *   · Only a persona whose sidebar strips the section gets a row; an owner whose
 *     sidebar still expands Sell sees no second copy of their own menu.
 *
 *  A page with its own hosted header (the Inventory fold) nests its provider
 *  inside this one and wins by React context, so the fold keeps working. */
export function SectionTabsProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const { pathname } = useLocation();
  const strip = sectionTabsFor(pathname, user);
  if (!strip) return <>{children}</>;

  const row = (
    <div className="page-tabs" data-testid="section-tabs">
      {strip.tabs.map((tab) => {
        const on = tab.to === strip.active.to;
        return (
          <Link
            key={tab.to}
            to={tab.to}
            className={`page-tab ${on ? "active" : ""}`}
            aria-current={on ? "page" : undefined}
            data-testid={`section-tab-${itemPath(tab).split("/").pop() || "home"}`}
          >
            {tab.label}
          </Link>
        );
      })}
    </div>
  );

  return (
    <HostedPageContext.Provider value={{ crumb: strip.crumb, title: strip.title, tabs: row }}>
      {children}
    </HostedPageContext.Provider>
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
            <NotificationBell />
            <UserMenu />
          </div>
        </header>
        {/* Keyed on the working context: switching unit remounts the page, so
            every screen refetches under the new unit instead of leaving the
            previous store's numbers on screen. */}
        <main className="content" key={contextKey(activeStore, activeBrand)}>
          <SectionTabsProvider>{children}</SectionTabsProvider>
        </main>
      </div>
    </div>
  );
}
