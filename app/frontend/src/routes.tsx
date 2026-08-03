// The route table, as data (issue #87).
//
// One canonical URL per screen, named by the section that owns it. Kept as an
// array rather than inline JSX so the ranking that decides which screen a URL
// opens — `/receive/new` is the new-GRN form, `/receive/12` is GRN 12 — is
// something a test can assert rather than something we hope React Router got
// right. `id` is that assertion's handle; it never reaches the user.
import type { ReactNode } from "react";
import { matchRoutes } from "react-router-dom";
import type { RouteObject } from "react-router-dom";

import { PlannedPage } from "./pages/PlannedPage";
import { LegacyRedirect } from "./shell/LegacyRedirect";
import { LEGACY_PATHS, NAV_ITEMS, itemPath } from "./shell/navConfig";
import { Home } from "./pages/Home";
import { BrandsPage, GstinsPage, SeasonsPage, StoreTargetsPage, StoresPage, UsersRolesPage, VendorsPage } from "./pages/MasterPages";
import { AccessMatrixPage } from "./pages/AccessMatrix";
import { SellPolicySettingsPage } from "./pages/SellPolicySettings";
import { BookingDetailPage, BookingNewPage, BookingsPage } from "./pages/Bookings";
import { GrnDetailPage, InboundNewPage, InboundPage } from "./pages/Inbound";
import { PtFileDetailPage, PtMapperPage, ReviewQueuePage } from "./pages/PtMapper";
import { PtProposalsPage } from "./pages/PtProposals";
import { TransferListPage, TransferNewPage, TransferDetailPage, TransferPtPage } from "./pages/OutboundTransfers";
import { StockRequestListPage, StockRequestNewPage, StockRequestDetailPage } from "./pages/OutboundStockRequests";
import { InTransitPage } from "./pages/OutboundInTransit";
import { RTVListPage, RTVNewPage, RTVDetailPage } from "./pages/OutboundRTV";
import { AdjustmentListPage, AdjustmentDetailPage } from "./pages/OutboundAdjustments";
import { StockCountListPage, StockCountDetailPage } from "./pages/StockCount";
import { WriteOffListPage, WriteOffNewPage, WriteOffDetailPage } from "./pages/OutboundWriteoffs";
import { VFlipListPage, VFlipNewPage, VFlipDetailPage } from "./pages/OutboundVflips";
import { ApprovalsPage } from "./pages/Approvals";
import { AlertsPage } from "./pages/Alerts";
import { MailPage } from "./pages/Mail";
import { OffersPage } from "./pages/Offers";
import { OffersEossPage } from "./pages/OffersEoss";
import { InventoryPage } from "./pages/Inventory";
import StockLedger from "./pages/StockLedger";
import StockOnHand from "./pages/StockOnHand";
import CrossStoreSearch from "./pages/CrossStoreSearch";
import VendorLedger from "./pages/VendorLedger";
import CashLedger from "./pages/CashLedger";
import DaySummary from "./pages/DaySummary";
import IrnQueue from "./pages/IrnQueue";
import BillingPage from "./pages/sell/Billing";
import CustomerSearchPage from "./pages/sell/CustomerSearch";
import TillPage from "./pages/sell/Till";
import { TillProvider } from "./till/TillProvider";

export type Room = "counter";
type Screen = RouteObject & { id: string; path: string; room?: Room };

/** A Sell screen, with the counter behind it. */
function withTill(screen: ReactNode) {
  return <TillProvider>{screen}</TillProvider>;
}

/** Screens that are built. Behaviour is unchanged from before the re-housing —
 *  only the address moved. */
const BUILT: Screen[] = [
  // Home
  { id: "home", path: "/", element: <Home /> },
  // One approvals inbox for the whole system, listed once (#70, #87)
  { id: "approvals", path: "/approvals", element: <ApprovalsPage /> },
  // Home's Alerts surface — in-transit aging + return-window 30/15/7 (#77)
  { id: "alerts", path: "/alerts", element: <AlertsPage /> },
  // The person's own mailbox, reached from the top bar rather than the sidebar:
  // mail belongs to a person, not to a section, so it has no menu entry and no
  // RBAC cell — every logged-in person has exactly one, and it is theirs.
  { id: "mail", path: "/mail", element: <MailPage /> },
  // Offers & Price - the store's read-only view of the rulebook (#183). The
  // three authoring screens beside it in the nav are still planned.
  { id: "offers", path: "/offers", element: <OffersPage /> },
  { id: "offers-eoss", path: "/offers/eoss", element: <OffersEossPage /> },
  // Booking
  { id: "booking-list", path: "/booking", element: <BookingsPage /> },
  { id: "booking-new", path: "/booking/new", element: <BookingNewPage /> },
  { id: "booking-detail", path: "/booking/:id", element: <BookingDetailPage /> },
  // Receive Goods
  { id: "grn-list", path: "/receive", element: <InboundPage /> },
  { id: "grn-new", path: "/receive/new", element: <InboundNewPage /> },
  { id: "grn-detail", path: "/receive/:id", element: <GrnDetailPage /> },
  { id: "pt-list", path: "/receive/pt", element: <PtMapperPage /> },
  { id: "pt-review", path: "/receive/pt/review", element: <ReviewQueuePage /> },
  { id: "pt-proposals", path: "/receive/pt/proposals", element: <PtProposalsPage /> },
  { id: "pt-detail", path: "/receive/pt/:id", element: <PtFileDetailPage /> },
  // Transfer
  { id: "transfer-list", path: "/transfer", element: <TransferListPage /> },
  { id: "transfer-new", path: "/transfer/new", element: <TransferNewPage /> },
  // Before /transfer/:id, or "in-transit"/"requests" would be read as a transfer id (#71).
  { id: "transfer-in-transit", path: "/transfer/in-transit", element: <InTransitPage /> },
  { id: "stock-request-list", path: "/transfer/requests", element: <StockRequestListPage /> },
  { id: "stock-request-new", path: "/transfer/requests/new", element: <StockRequestNewPage /> },
  { id: "stock-request-detail", path: "/transfer/requests/:id", element: <StockRequestDetailPage /> },
  { id: "transfer-detail", path: "/transfer/:id", element: <TransferDetailPage /> },
  // The printable PT the carton travels with (#72).
  { id: "transfer-pt", path: "/transfer/:id/pt", element: <TransferPtPage /> },
  // Stock Count — the counting sessions, and the corrections they produce
  { id: "count-list", path: "/stock-count", element: <StockCountListPage /> },
  { id: "adjustment-list", path: "/stock-count/adjustments", element: <AdjustmentListPage /> },
  { id: "adjustment-detail", path: "/stock-count/adjustments/:id", element: <AdjustmentDetailPage /> },
  { id: "writeoff-list", path: "/stock-count/writeoffs", element: <WriteOffListPage /> },
  { id: "writeoff-new", path: "/stock-count/writeoffs/new", element: <WriteOffNewPage /> },
  { id: "writeoff-detail", path: "/stock-count/writeoffs/:id", element: <WriteOffDetailPage /> },
  // Last in the section: a count id must never shadow "adjustments"/"writeoffs".
  { id: "count-detail", path: "/stock-count/:id", element: <StockCountDetailPage /> },
  // Return to Brand
  { id: "rtv-list", path: "/return-to-brand", element: <RTVListPage /> },
  { id: "rtv-new", path: "/return-to-brand/new", element: <RTVNewPage /> },
  { id: "rtv-detail", path: "/return-to-brand/:id", element: <RTVDetailPage /> },
  // Inventory - Stock, Stock Count and Return to Brand folded onto one page
  // (#170). It belongs to no section: it is the store persona's arrangement of
  // three of them, and its tabs carry those sections' own gates.
  { id: "inventory", path: "/inventory", element: <InventoryPage /> },
  // Sell - the counter (#181) and the till layer's own surface (#180).
  //
  // `TillProvider` wraps each screen rather than the app: opening a counter's
  // local database means holding one store's price list, credit notes and
  // manager PIN hashes, which a warehouse or head-office login has no business
  // carrying.
  //
  // Billing declares the counter room instead of wrapping itself here:
  // ProtectedRoute lifts its provider above AppShell so the live sync light can
  // occupy the top bar. The other Sell screens remain route-local providers.
  { id: "sell-billing", path: "/sell", room: "counter", element: <BillingPage /> },
  { id: "sell-till", path: "/sell/till", element: withTill(<TillPage />) },
  // Find a bill and print it again (#185). No `withTill`, and that is the whole
  // shape of the screen: it reads the *server's* bills, because the counter's
  // local copy holds only what it has not yet synced - last month's bill, or one
  // from the machine that was replaced, is only ever at head office. It also
  // means somebody who may read bills but not bill (an owner, an accountant) can
  // open it without a counter's price list being opened on their laptop.
  { id: "sell-customers", path: "/sell/customers", element: <CustomerSearchPage /> },
  // Stock — V-flip is an action inside this section, not a menu item
  { id: "stock-on-hand", path: "/stock", element: <StockOnHand /> },
  { id: "stock-search", path: "/stock/search", element: <CrossStoreSearch /> },
  { id: "stock-history", path: "/stock/history", element: <StockLedger /> },
  { id: "vflip-list", path: "/stock/vflips", element: <VFlipListPage /> },
  { id: "vflip-new", path: "/stock/vflips/new", element: <VFlipNewPage /> },
  { id: "vflip-detail", path: "/stock/vflips/:id", element: <VFlipDetailPage /> },
  // Money
  { id: "day-summary", path: "/money/day-summary", element: <DaySummary /> },
  { id: "store-targets", path: "/money/store-targets", element: <StoreTargetsPage /> },
  { id: "vendor-ledger", path: "/money/vendor", element: <VendorLedger /> },
  { id: "cash-ledger", path: "/money/cash", element: <CashLedger /> },
  { id: "irn-queue", path: "/money/irn-queue", element: <IrnQueue /> },
  // Setup
  { id: "setup-stores", path: "/setup/stores", element: <StoresPage /> },
  { id: "setup-brands", path: "/setup/brands", element: <BrandsPage /> },
  { id: "setup-vendors", path: "/setup/vendors", element: <VendorsPage /> },
  { id: "setup-seasons", path: "/setup/seasons", element: <SeasonsPage /> },
  { id: "setup-gstins", path: "/setup/gstins", element: <GstinsPage /> },
  { id: "setup-users", path: "/setup/users", element: <UsersRolesPage /> },
  { id: "setup-access", path: "/setup/access", element: <AccessMatrixPage /> },
  { id: "setup-settings", path: "/setup/settings", element: <SellPolicySettingsPage /> },
];

// Sections whose subsections aren't built yet still appear in the sidebar — so
// every one of them needs a page that honestly says what is planned there (#89).
// Generated from the manifest, so a new planned item can never 404, and the copy
// comes from pages/plannedPages, keyed by the same path.
const PLANNED: Screen[] = NAV_ITEMS.filter((i) => i.planned && !i.deepLink).map((i) => ({
  id: `planned:${itemPath(i)}`,
  path: itemPath(i),
  element: <PlannedPage />,
}));

// Old addresses are redirected by App's catch-all — every one that falls through
// the table. `/receive/upload-bill` (the stub #228 deleted) does not fall
// through: it sits exactly where `/receive/:id` looks for a document number, so
// it would open "GRN number upload-bill" and the catch-all would never see it.
//
// So: any legacy path a built or planned route would claim gets a redirect route
// of its own, derived rather than listed, so the next one is caught without
// anybody remembering this file. A static segment outranks a dynamic one, so
// these win over `/receive/:id` whatever the order here.
const CLAIMABLE: Screen[] = [...BUILT, ...PLANNED];
const LEGACY: Screen[] = LEGACY_PATHS.filter((path) => matchRoutes(CLAIMABLE, path)).map((path) => ({
  id: `legacy:${path}`,
  path,
  element: <LegacyRedirect />,
}));

export const PROTECTED_ROUTES: Screen[] = [...CLAIMABLE, ...LEGACY];

/** Resolve from the canonical table so shell chrome cannot drift into a second
 *  pathname list with subtly different prefix rules. */
export function roomAt(pathname: string): Room | undefined {
  const matched = matchRoutes(PROTECTED_ROUTES, pathname);
  return (matched?.[matched.length - 1]?.route as Screen | undefined)?.room;
}
