import { useLocation } from "react-router-dom";
import { Compass } from "lucide-react";

import { SECTIONS, itemPath } from "../shell/navConfig";

/** The honest "not built yet" page. What it promises comes from the section
 *  manifest, so the sidebar and this page can never tell different stories. */
export function ModulePage() {
  const { pathname } = useLocation();
  const normalized = pathname.toLowerCase().replace(/\/+$/, "") || "/";
  let sectionLabel = "";
  let layer = "documents";
  let title = "Coming soon";
  let intent = "";
  for (const s of SECTIONS) {
    const it = s.items.find((i) => itemPath(i) === normalized);
    if (it) {
      sectionLabel = s.label;
      layer = s.layer;
      title = it.label;
      intent = it.intent ?? "";
      break;
    }
  }
  return (
    <div className="page-pad">
      <p className="eyebrow">{sectionLabel}</p>
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
          {intent ||
            (sectionLabel
              ? `${title} will support the ${sectionLabel} workflow when this slice is enabled.`
              : "There is nothing at this address. Use the sidebar or the search box at the top.")}
        </p>
        <div style={{ marginTop: 18 }}>
          <span className="chip chip-amber">Coming soon</span>
        </div>
      </div>
    </div>
  );
}
