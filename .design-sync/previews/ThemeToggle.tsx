import { ThemeToggle } from "kdps-frontend";

/** The whole-app theme control: Light, Dark or follow the device. It reads and
 *  writes the real preference, so whichever segment is lit is the live setting. */
export const FullWidth = () => (
  <div className="card" style={{ padding: 16, maxWidth: 400 }}>
    <p className="eyebrow">Appearance</p>
    <div style={{ marginTop: 12 }}>
      <ThemeToggle />
    </div>
    <p className="lead" style={{ marginTop: 12, fontSize: 13 }}>
      System follows the phone or laptop — the setting a store PC is usually left on.
    </p>
  </div>
);

/** `compact` drops the labels and keeps the icons, for the header rail where the
 *  toggle sits beside the store picker and there is no room for words. */
export const Compact = () => (
  <div className="card" style={{ padding: 16, maxWidth: 400 }}>
    <p className="eyebrow">Compact — icons only</p>
    <div style={{ marginTop: 12 }}>
      <ThemeToggle compact />
    </div>
    <p className="lead" style={{ marginTop: 12, fontSize: 13 }}>
      Same three choices, same state — only the labels are dropped.
    </p>
  </div>
);

/** In place: the top rail of the app shell, where it lives next to the store the
 *  user is signed in against. */
export const InTheHeaderRail = () => (
  <div className="card" style={{ padding: 16, maxWidth: 460 }}>
    <p className="eyebrow">Header rail</p>
    <div
      style={{
        marginTop: 12,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 16,
        paddingTop: 12,
        borderTop: "1px solid var(--hairline)",
      }}
    >
      <div>
        <div style={{ fontWeight: 700, fontSize: 14 }}>Deoghar · DEO</div>
        <div style={{ color: "var(--caption)", fontSize: 12.5 }}>Sunita Kumari · Store Manager</div>
      </div>
      <ThemeToggle compact />
    </div>
  </div>
);
