import { useLocation } from "react-router-dom";
import { Compass } from "lucide-react";

import { NAV_ITEMS, SECTIONS, itemPath, normalizePath } from "../shell/navConfig";

/** The honest "not built yet" page. What it promises comes from the section
 *  manifest, so the sidebar and this page can never tell different stories. */
export function ModulePage() {
  const { pathname } = useLocation();
  // Exact match, not longest-prefix: this page also serves the 404 corner, and
  // an address nobody built should say so rather than borrow its parent's
  // promise. A deep link owns no URL, so it never answers for one.
  const target = normalizePath(pathname);
  const screen = NAV_ITEMS.find((i) => !i.deepLink && itemPath(i) === target);
  const section = screen ? SECTIONS.find((s) => s.code === screen.section) : undefined;
  const sectionLabel = section?.label ?? "";
  const layer = section?.layer ?? "documents";
  const title = screen?.label ?? "Coming soon";
  const intent = screen?.intent ?? "";
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
