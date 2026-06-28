import { useLocation } from "react-router-dom";
import { Compass } from "lucide-react";

import { NAV } from "../shell/navConfig";

const PAGE_INTENT: Record<string, string> = {
  "/store/sell": "This page will handle store billing, returns, exchanges, and POS handoff for daily selling.",
  "/store/count": "This page will guide store teams through cycle counts, bin checks, and stock variance review.",
  "/store/transfer": "This page will create and track store-to-store or warehouse transfer documents.",
  "/documents/sales": "This page will show sales documents, POS imports, exceptions, and day-close review.",
  "/documents/transfers": "This page will track transfer notes, dispatches, receipts, and in-transit stock.",
  "/documents/returns": "This page will manage customer returns, brand returns, and approval-backed adjustments.",
  "/documents/payments": "This page will record payment documents and connect vendor settlement decisions to ledgers.",
  "/controls/exceptions": "This page will collect mismatches, failed imports, approval holds, and items needing action.",
  "/controls/recon": "This page will reconcile stock, cash, bank, vendor, and document totals before close.",
  "/controls/approvals": "This page will route sensitive actions to the right approver with a clear decision trail.",
  "/controls/audit": "This page will expose who changed what, when it happened, and which document or ledger was affected.",
  "/intel/dashboards": "This page will provide configurable business dashboards for sales, stock, margin, and operations.",
  "/intel/profitability": "This page will compare profitability by brand, store, season, and commercial model.",
  "/intel/dead-stock": "This page will identify slow-moving and ageing stock that needs action.",
  "/intel/forecast": "This page will support demand forecasts and replenishment suggestions for human review.",
  "/intel/reports": "This page will let users assemble saved reports from approved operational metrics.",
  "/edges/integrations": "This page will monitor connected systems, import status, and adapter health.",
  "/edges/tally": "This page will prepare and review the statutory Tally export bridge.",
  "/edges/pos": "This page will configure POS data sources, import schedules, and dead-letter queues.",
  "/edges/config": "This page will manage safe system settings for administrators.",
};

export function ModulePage() {
  const { pathname } = useLocation();
  let groupLabel = "";
  let layer = "documents";
  let title = "Coming soon";
  for (const g of NAV) {
    const it = g.items.find((i) => i.to === pathname);
    if (it) {
      groupLabel = g.label;
      layer = g.layer;
      title = it.label;
      break;
    }
  }
  return (
    <div className="page-pad">
      <p className="eyebrow">{groupLabel}</p>
      <h1 className="h1" style={{ marginBottom: 20 }}>{title}</h1>
      <div
        className="card"
        style={{ padding: "44px 38px", borderTop: `3px solid var(--layer-${layer})` }}
        data-testid="module-placeholder"
      >
        <div
          style={{
            width: 56,
            height: 56,
            borderRadius: 14,
            background: "var(--inner)",
            border: "1px solid var(--hairline)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: `var(--layer-${layer})`,
            marginBottom: 18,
          }}
        >
          <Compass size={26} />
        </div>
        <h3 className="h3" style={{ marginBottom: 8 }}>Coming soon</h3>
        <p className="lead" style={{ maxWidth: 560, lineHeight: 1.65 }}>
          {PAGE_INTENT[pathname] ?? `${title} will support the ${groupLabel} workflow when this slice is enabled.`}
        </p>
        <div style={{ marginTop: 18 }}>
          <span className="chip chip-amber">Coming soon</span>
        </div>
      </div>
    </div>
  );
}
