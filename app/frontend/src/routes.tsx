// The route table, as data (issue #87).
//
// One canonical URL per screen, named by the section that owns it. Kept as an
// array rather than inline JSX so the ranking that decides which screen a URL
// opens — `/receive/new` is the new-GRN form, `/receive/12` is GRN 12 — is
// something a test can assert rather than something we hope React Router got
// right. `id` is that assertion's handle; it never reaches the user.
import type { RouteObject } from "react-router-dom";

import { PlannedPage } from "./pages/PlannedPage";
import { NAV_ITEMS, itemPath } from "./shell/navConfig";
import { Home } from "./pages/Home";
import { BrandsPage, GstinsPage, SeasonsPage, StoresPage, UsersRolesPage } from "./pages/MasterPages";
import { BookingDetailPage, BookingNewPage, BookingsPage } from "./pages/Bookings";
import { GrnDetailPage, InboundNewPage, InboundPage } from "./pages/Inbound";
import { PtFileDetailPage, PtMapperPage, ReviewQueuePage } from "./pages/PtMapper";
import { PtProposalsPage } from "./pages/PtProposals";
import { TransferListPage, TransferNewPage, TransferDetailPage } from "./pages/OutboundTransfers";
import { InTransitPage } from "./pages/OutboundInTransit";
import { RTVListPage, RTVNewPage, RTVDetailPage } from "./pages/OutboundRTV";
import { AdjustmentListPage, AdjustmentDetailPage } from "./pages/OutboundAdjustments";
import { StockCountListPage, StockCountDetailPage } from "./pages/StockCount";
import { WriteOffListPage, WriteOffNewPage, WriteOffDetailPage } from "./pages/OutboundWriteoffs";
import { VFlipListPage, VFlipNewPage, VFlipDetailPage } from "./pages/OutboundVflips";
import { ApprovalsPage } from "./pages/Approvals";
import StockLedger from "./pages/StockLedger";
import StockOnHand from "./pages/StockOnHand";
import VendorLedger from "./pages/VendorLedger";
import CashLedger from "./pages/CashLedger";

type Screen = RouteObject & { id: string; path: string };

/** Screens that are built. Behaviour is unchanged from before the re-housing —
 *  only the address moved. */
const BUILT: Screen[] = [
  // Home
  { id: "home", path: "/", element: <Home /> },
  // One approvals inbox for the whole system, listed once (#70, #87)
  { id: "approvals", path: "/approvals", element: <ApprovalsPage /> },
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
  // Before /transfer/:id, or "in-transit" would be read as a transfer id (#71).
  { id: "transfer-in-transit", path: "/transfer/in-transit", element: <InTransitPage /> },
  { id: "transfer-detail", path: "/transfer/:id", element: <TransferDetailPage /> },
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
  // Stock — V-flip is an action inside this section, not a menu item
  { id: "stock-on-hand", path: "/stock", element: <StockOnHand /> },
  { id: "stock-history", path: "/stock/history", element: <StockLedger /> },
  { id: "vflip-list", path: "/stock/vflips", element: <VFlipListPage /> },
  { id: "vflip-new", path: "/stock/vflips/new", element: <VFlipNewPage /> },
  { id: "vflip-detail", path: "/stock/vflips/:id", element: <VFlipDetailPage /> },
  // Money
  { id: "vendor-ledger", path: "/money/vendor", element: <VendorLedger /> },
  { id: "cash-ledger", path: "/money/cash", element: <CashLedger /> },
  // Setup
  { id: "setup-stores", path: "/setup/stores", element: <StoresPage /> },
  { id: "setup-brands", path: "/setup/brands", element: <BrandsPage /> },
  { id: "setup-seasons", path: "/setup/seasons", element: <SeasonsPage /> },
  { id: "setup-gstins", path: "/setup/gstins", element: <GstinsPage /> },
  { id: "setup-users", path: "/setup/users", element: <UsersRolesPage /> },
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

export const PROTECTED_ROUTES: Screen[] = [...BUILT, ...PLANNED];
