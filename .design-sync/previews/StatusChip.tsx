import { StatusChip } from "kdps-frontend";

/** Known statuses pick their own tone from the shared status map, so the same
 *  word is always the same colour everywhere in the system. */
export const KnownStatuses = () => (
  <div className="card" style={{ padding: 16, maxWidth: 460 }}>
    <p className="eyebrow">Tone comes from the status</p>
    <div className="chip-picker" style={{ marginTop: 10 }}>
      <StatusChip status="Open" />
      <StatusChip status="Matched" />
      <StatusChip status="OK" />
      <StatusChip status="Pending" />
      <StatusChip status="EOSS" />
      <StatusChip status="Blocked" />
      <StatusChip status="Overdue" />
      <StatusChip status="Closed" />
      <StatusChip status="AI" />
    </div>
  </div>
);

/** An unknown status falls back to navy; pass `tone` to force one of the six
 *  semantic colours. */
export const ExplicitTone = () => (
  <div className="card" style={{ padding: 16, maxWidth: 460 }}>
    <p className="eyebrow">Forced tone</p>
    <div className="chip-picker" style={{ marginTop: 10 }}>
      <StatusChip status="Draft" />
      <StatusChip status="Submitted" tone="blue" />
      <StatusChip status="Approved" tone="green" />
      <StatusChip status="Awaiting PT" tone="amber" />
      <StatusChip status="Cancelled" tone="red" />
      <StatusChip status="Suggested" tone="purple" />
    </div>
  </div>
);

/** How it reads in the place it actually lives — a document list. */
export const InAList = () => (
  <div className="card" style={{ padding: 16, maxWidth: 460 }}>
    <p className="eyebrow">Transfers</p>
    <table style={{ width: "100%", fontSize: 13.5, borderSpacing: "0 8px" }}>
      <tbody>
        <tr>
          <td className="mono">26-27/RAN-WH/TRF/118</td>
          <td align="right"><StatusChip status="Matched" /></td>
        </tr>
        <tr>
          <td className="mono">26-27/RAN-WH/TRF/119</td>
          <td align="right"><StatusChip status="Pending" /></td>
        </tr>
        <tr>
          <td className="mono">26-27/DEO/TRF/042</td>
          <td align="right"><StatusChip status="Blocked" /></td>
        </tr>
      </tbody>
    </table>
  </div>
);
