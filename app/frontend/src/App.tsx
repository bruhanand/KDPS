import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { Home } from "./pages/Home";
import { Login } from "./pages/Login";
import { ModulePage } from "./pages/ModulePage";
import { BrandsPage, GstinsPage, SeasonsPage, StoresPage, UsersRolesPage } from "./pages/MasterPages";
import { BookingDetailPage, BookingNewPage, BookingsPage } from "./pages/Bookings";
import { GrnDetailPage, InboundNewPage, InboundPage } from "./pages/Inbound";
import { PtFileDetailPage, PtMapperPage, ReviewQueuePage } from "./pages/PtMapper";
import { PtProposalsPage } from "./pages/PtProposals";
import { TransferListPage, TransferNewPage, TransferDetailPage } from "./pages/OutboundTransfers";
import { RTVListPage, RTVNewPage, RTVDetailPage } from "./pages/OutboundRTV";
import { AdjustmentListPage, AdjustmentNewPage, AdjustmentDetailPage } from "./pages/OutboundAdjustments";
import { WriteOffListPage, WriteOffNewPage, WriteOffDetailPage } from "./pages/OutboundWriteoffs";
import { VFlipListPage, VFlipNewPage, VFlipDetailPage } from "./pages/OutboundVflips";
import { ApprovalsPage } from "./pages/Approvals";
import StockLedger from "./pages/StockLedger";
import StockOnHand from "./pages/StockOnHand";
import VendorLedger from "./pages/VendorLedger";
import CashLedger from "./pages/CashLedger";

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/" element={<Home />} />
            <Route path="/documents/bookings" element={<BookingsPage />} />
            <Route path="/documents/bookings/new" element={<BookingNewPage />} />
            <Route path="/documents/bookings/:id" element={<BookingDetailPage />} />
            <Route path="/documents/inbound" element={<InboundPage />} />
            <Route path="/documents/inbound/new" element={<InboundNewPage />} />
            <Route path="/documents/inbound/:id" element={<GrnDetailPage />} />
            <Route path="/inbound" element={<InboundPage />} />
            <Route path="/inbound/new" element={<InboundNewPage />} />
            <Route path="/inbound/:id" element={<GrnDetailPage />} />
            {/* Outbound */}
            <Route path="/outbound/transfers" element={<TransferListPage />} />
            <Route path="/outbound/transfers/new" element={<TransferNewPage />} />
            <Route path="/outbound/transfers/:id" element={<TransferDetailPage />} />
            <Route path="/outbound/rtvs" element={<RTVListPage />} />
            <Route path="/outbound/rtvs/new" element={<RTVNewPage />} />
            <Route path="/outbound/rtvs/:id" element={<RTVDetailPage />} />
            <Route path="/outbound/adjustments" element={<AdjustmentListPage />} />
            <Route path="/outbound/adjustments/new" element={<AdjustmentNewPage />} />
            <Route path="/outbound/adjustments/:id" element={<AdjustmentDetailPage />} />
            <Route path="/outbound/writeoffs" element={<WriteOffListPage />} />
            <Route path="/outbound/writeoffs/new" element={<WriteOffNewPage />} />
            <Route path="/outbound/writeoffs/:id" element={<WriteOffDetailPage />} />
            <Route path="/outbound/vflips" element={<VFlipListPage />} />
            <Route path="/outbound/vflips/new" element={<VFlipNewPage />} />
            <Route path="/outbound/vflips/:id" element={<VFlipDetailPage />} />
            {/* One approvals inbox for the whole system — reachable everywhere (#70) */}
            <Route path="/approvals" element={<ApprovalsPage />} />
            <Route path="/documents/pt-mapper" element={<PtMapperPage />} />
            <Route path="/documents/pt-mapper/review" element={<ReviewQueuePage />} />
            <Route path="/documents/pt-mapper/proposals" element={<PtProposalsPage />} />
            <Route path="/documents/pt-mapper/:id" element={<PtFileDetailPage />} />
            <Route path="/ledgers/stock" element={<StockLedger />} />
            <Route path="/ledgers/stock-on-hand" element={<StockOnHand />} />
            <Route path="/ledgers/vendor" element={<VendorLedger />} />
            <Route path="/ledgers/cash" element={<CashLedger />} />
            <Route path="/store/receive" element={<InboundPage />} />
            <Route path="/masters/stores" element={<StoresPage />} />
            <Route path="/masters/brands" element={<BrandsPage />} />
            <Route path="/masters/seasons" element={<SeasonsPage />} />
            <Route path="/masters/gstins" element={<GstinsPage />} />
            <Route path="/masters/users" element={<UsersRolesPage />} />
            <Route path="/edges/rbac" element={<UsersRolesPage />} />
            <Route path="*" element={<ModulePage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
