import {
  BookOpenText,
  Boxes,
  FileText,
  LayoutDashboard,
  PackageMinus,
  Plug,
  ShieldCheck,
  ShoppingCart,
  Sparkles,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { FINANCE_ROLES, RBAC_ADMIN_ROLES } from "../auth/routeAccess";

export interface NavItem {
  label: string;
  to: string;
  // Optional finer gate: only these role codes see this item (mirrors a
  // backend permission tighter than the group). Omitted → group access is
  // enough. Kept in sync with the route guard in auth/routeAccess.ts.
  roles?: string[];
}

export interface NavGroup {
  key: string; // matches a user nav_group
  label: string;
  icon: LucideIcon;
  layer: string; // CSS layer-* token suffix
  items: NavItem[];
}

export const NAV: NavGroup[] = [
  {
    key: "home",
    label: "Home",
    icon: LayoutDashboard,
    layer: "home",
    // The approvals inbox is an "everywhere" surface (system.md · Maker-checker),
    // so it hangs off Home — the one group every role has — not off Controls,
    // which store and warehouse roles cannot see.
    items: [
      { label: "Dashboard", to: "/" },
      { label: "Approvals", to: "/approvals" },
    ],
  },
  {
    key: "store_ops",
    label: "Store Ops",
    icon: ShoppingCart,
    layer: "store",
    items: [
      { label: "Sell", to: "/store/sell" },
      { label: "Stock Receive", to: "/inbound" },
      { label: "Count", to: "/store/count" },
    ],
  },
  {
    key: "outbound",
    label: "Outbound",
    icon: PackageMinus,
    layer: "outbound",
    items: [
      { label: "Transfers", to: "/outbound/transfers" },
      { label: "Return to Vendor", to: "/outbound/rtvs" },
      { label: "Adjustments", to: "/outbound/adjustments" },
      { label: "Write-offs", to: "/outbound/writeoffs" },
      { label: "V-Flip", to: "/outbound/vflips" },
    ],
  },
  {
    key: "documents",
    label: "Documents",
    icon: FileText,
    layer: "documents",
    items: [
      { label: "Bookings", to: "/documents/bookings" },
      { label: "Stock Receive", to: "/inbound" },
      { label: "PT File Operation", to: "/documents/pt-mapper" },
      { label: "Sales", to: "/documents/sales" },
      { label: "Transfers", to: "/documents/transfers" },
      { label: "Returns", to: "/documents/returns" },
      { label: "Payments", to: "/documents/payments" },
    ],
  },
  {
    key: "master_data",
    label: "Master Data",
    icon: Boxes,
    layer: "master",
    items: [
      { label: "Stores", to: "/masters/stores" },
      { label: "Brands", to: "/masters/brands" },
      { label: "Seasons", to: "/masters/seasons" },
      { label: "GSTINs", to: "/masters/gstins" },
      { label: "Users & Roles", to: "/masters/users", roles: RBAC_ADMIN_ROLES },
    ],
  },
  {
    key: "ledgers",
    label: "Ledgers",
    icon: BookOpenText,
    layer: "ledgers",
    items: [
      { label: "Stock Ledger", to: "/ledgers/stock" },
      { label: "Stock on Hand", to: "/ledgers/stock-on-hand" },
      { label: "Vendor Ledger", to: "/ledgers/vendor", roles: FINANCE_ROLES },
      { label: "Cash Ledger", to: "/ledgers/cash", roles: FINANCE_ROLES },
    ],
  },
  {
    key: "controls",
    label: "Controls",
    icon: ShieldCheck,
    layer: "controls",
    items: [
      { label: "Exception Inbox", to: "/controls/exceptions" },
      { label: "Reconciliations", to: "/controls/recon" },
      { label: "Approvals", to: "/approvals" },
      { label: "Audit Trail", to: "/controls/audit" },
    ],
  },
  {
    key: "intelligence",
    label: "Intelligence",
    icon: Sparkles,
    layer: "intelligence",
    items: [
      { label: "Dashboards", to: "/intel/dashboards" },
      { label: "Profitability", to: "/intel/profitability" },
      { label: "Dead Stock", to: "/intel/dead-stock" },
      { label: "Forecast", to: "/intel/forecast" },
      { label: "Report Maker", to: "/intel/reports" },
    ],
  },
  {
    key: "edges_admin",
    label: "Edges & Admin",
    icon: Plug,
    layer: "edges",
    items: [
      { label: "Integrations", to: "/edges/integrations" },
      { label: "Users & RBAC", to: "/edges/rbac", roles: RBAC_ADMIN_ROLES },
      { label: "Tally Bridge", to: "/edges/tally" },
      { label: "POS Sources", to: "/edges/pos" },
      { label: "Config", to: "/edges/config" },
    ],
  },
];
