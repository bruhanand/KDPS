import {
  BookOpenText,
  Boxes,
  FileText,
  LayoutDashboard,
  Plug,
  ShieldCheck,
  ShoppingCart,
  Sparkles,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface NavItem {
  label: string;
  to: string;
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
    items: [{ label: "Dashboard", to: "/" }],
  },
  {
    key: "store_ops",
    label: "Store Ops",
    icon: ShoppingCart,
    layer: "store",
    items: [
      { label: "Sell", to: "/store/sell" },
      { label: "Receive", to: "/store/receive" },
      { label: "Count", to: "/store/count" },
      { label: "Transfer", to: "/store/transfer" },
    ],
  },
  {
    key: "documents",
    label: "Documents",
    icon: FileText,
    layer: "documents",
    items: [
      { label: "Bookings", to: "/documents/bookings" },
      { label: "Inbound (GRN / PT)", to: "/documents/inbound" },
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
      { label: "Users & Roles", to: "/masters/users" },
    ],
  },
  {
    key: "ledgers",
    label: "Ledgers",
    icon: BookOpenText,
    layer: "ledgers",
    items: [
      { label: "Stock Ledger", to: "/ledgers/stock" },
      { label: "Vendor Ledger", to: "/ledgers/vendor" },
      { label: "Cash Ledger", to: "/ledgers/cash" },
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
      { label: "Approvals", to: "/controls/approvals" },
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
      { label: "Users & RBAC", to: "/edges/rbac" },
      { label: "Tally Bridge", to: "/edges/tally" },
      { label: "POS Sources", to: "/edges/pos" },
      { label: "Config", to: "/edges/config" },
    ],
  },
];
