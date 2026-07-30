// The sync light (#180, D10 grill Q1).
//
// The one piece of the till layer a cashier looks at all day, so it says a word
// and a number rather than a colour alone: "Synced", "3 waiting", "Not accepted".
// Colour-blindness aside, a red dot on its own does not tell anybody what to do.
//
// It lives on the page rather than in the top bar (Anand's Phase-3 ruling): the
// shell is shared with every screen in the system, and only a Sell screen has a
// till behind it.

import { useTill } from "./TillProvider";

/** The light itself. Renders nothing when this login has no counter. */
export function SyncLight({ showReason = false }: { showReason?: boolean }) {
  const { till } = useTill();
  if (!till) return null;
  const { colour, reason } = till.status;
  return (
    <span className="sync-light" data-testid="till-sync-light" data-colour={colour}>
      <span className={`chip chip-${colour}`} title={reason}>
        {label(till.pending, colour)}
      </span>
      {showReason && (
        <span className="sync-light-reason" data-testid="till-sync-reason">
          {reason}
        </span>
      )}
    </span>
  );
}

function label(pending: number, colour: string): string {
  if (colour === "red") return "Needs attention";
  if (pending > 0) return `${pending} waiting`;
  return colour === "amber" ? "Offline" : "Synced";
}
