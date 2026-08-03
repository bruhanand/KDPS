// The cross-link between the two screens Promotions now covers on one sidebar
// entry — Active & Draft Offers (`/offers`) and EOSS Planning (`/offers/eoss`),
// consolidated Aug 2026 (see navConfig's `offers_price` comment). Both routes
// are unchanged and still bookmarkable; this is presentation only, in the same
// `.page-tab` language the Inventory fold already uses.
import { Link, useLocation } from "react-router-dom";

const TABS = [
  { to: "/offers", label: "Active & Draft Offers" },
  { to: "/offers/eoss", label: "EOSS Planning" },
];

export function PromotionsTabs() {
  const { pathname } = useLocation();
  return (
    <div className="page-tabs" data-testid="promotions-tabs">
      {TABS.map((t) => (
        <Link
          key={t.to}
          to={t.to}
          className={`page-tab ${pathname === t.to ? "active" : ""}`}
          aria-current={pathname === t.to ? "page" : undefined}
          data-testid={`promotions-tab-${t.to === "/offers" ? "offers" : "eoss"}`}
        >
          {t.label}
        </Link>
      ))}
    </div>
  );
}
