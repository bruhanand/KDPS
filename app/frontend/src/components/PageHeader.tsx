import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

import { SECTIONS, itemOwning, itemPath, normalizePath } from "../shell/navConfig";

// One header for every screen, captioned the way the sidebar addresses it (#87).
//
// Screens used to hand-write their own kicker, and eleven of them still said
// "Documents", "Store Ops", "Ledgers", "Outbound" or "Master data" — the five
// layer groups the navigation redesign dissolved. A person clicked
// "Receive Goods → PT Files" and landed on a page captioned "Documents ·
// Warehouse (Ranchi) → Patna HO". The caption is now derived from the same
// manifest the menu is built from, so the two cannot tell different stories,
// and `pageVocabulary.test.ts` fails the build if a page types one back.

/** The section that owns `pathname`, and the screen inside it. */
export function pageContext(pathname: string) {
  const item = itemOwning(pathname);
  const section = item ? SECTIONS.find((s) => s.code === item.section) : undefined;
  return { item, section };
}

export function PageHeader({
  title,
  lead,
  actions,
  titleTestId,
}: {
  /** Defaults to the screen's own name in the navigation manifest. */
  title?: string;
  lead?: ReactNode;
  /** Buttons, pushed to the right of the header row. */
  actions?: ReactNode;
  titleTestId?: string;
}) {
  const { pathname } = useLocation();
  const { item, section } = pageContext(pathname);
  const heading = title ?? item?.label ?? "";
  // The screen's own line is worth showing only when the title is something
  // else — a document number, or a page whose name differs from its menu entry.
  // On the list screen itself "Booking · Bookings" would just say it twice.
  const showScreen = !!item && item.label !== heading && itemPath(item) !== normalizePath(pathname);

  return (
    <div className="toolbar">
      <div>
        <p className="eyebrow" data-testid="page-crumb">
          {section?.label}
          {showScreen && (
            <>
              {" · "}
              <Link className="crumb-link" to={item.to} data-testid="page-crumb-screen">
                {item.label}
              </Link>
            </>
          )}
        </p>
        <h1 className="h1 h2-rust" data-testid={titleTestId ?? "page-title"}>
          {heading}
        </h1>
        {lead && <p className="lead">{lead}</p>}
      </div>
      <div className="spacer" />
      {actions}
    </div>
  );
}
