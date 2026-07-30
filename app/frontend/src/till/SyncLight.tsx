// The sync light (#180, D10 grill Q1).
//
// The one piece of the till layer a cashier looks at all day, so it says a word
// and a number rather than a colour alone: "Synced", "3 waiting", "Bill refused".
// Colour-blindness aside, a red dot on its own does not tell anybody what to do.
//
// Both the word and the sentence behind it come from `deriveStatus`, so this
// renders the light and decides nothing about it.
//
// It lives on the page rather than in the top bar (Anand's Phase-3 ruling): the
// shell is shared with every screen in the system, and only a Sell screen has a
// till behind it.

import { useTill } from "./TillProvider";

/** The light itself. Renders nothing when this login has no counter. */
export function SyncLight() {
  const { till } = useTill();
  if (!till) return null;
  const { colour, label, reason } = till.status;
  return (
    <span className="sync-light" data-testid="till-sync-light" data-colour={colour}>
      <span className={`chip chip-${colour}`} title={reason}>
        {label}
      </span>
    </span>
  );
}
