import { useLocation } from "react-router-dom";
import { Compass } from "lucide-react";

import { NAV } from "../shell/navConfig";

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
        <h3 className="h3" style={{ marginBottom: 8 }}>This screen is mapped, not yet built.</h3>
        <p className="lead" style={{ maxWidth: 560, lineHeight: 1.65 }}>
          <b>{title}</b> is part of the {groupLabel} layer in the KDPS application plan
          (191 pages across 14 modules). The foundation — shell, login, roles and the
          masters spine — is live now; this page arrives with its vertical slice, built
          one verified slice at a time.
        </p>
        <div style={{ marginTop: 18 }}>
          <span className="chip chip-amber">Planned</span>
        </div>
      </div>
    </div>
  );
}
