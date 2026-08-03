import { ApprovalPill, Money } from "kdps-frontend";

/** The four states an approval can be in. The pill is the only place the
 *  system says "Waiting" - every document that needs a second person shows it. */
export const AllStates = () => (
  <div className="card" style={{ padding: 16, maxWidth: 460 }}>
    <p className="eyebrow">Maker · checker</p>
    <div className="chip-picker" style={{ marginTop: 10 }}>
      <ApprovalPill status="pending" />
      <ApprovalPill status="approved" />
      <ApprovalPill status="rejected" />
      <ApprovalPill status="not_required" />
    </div>
  </div>
);

/** Where it actually lives: the Operations Head's approvals inbox. One row per
 *  request, the pill on the right, the value the request moves on the left. */
export const ApprovalsInbox = () => (
  <div className="card" style={{ padding: 16, maxWidth: 520 }}>
    <p className="eyebrow">Approvals inbox · Operations Head</p>
    <table style={{ width: "100%", fontSize: 13.5, borderSpacing: "0 10px" }}>
      <tbody>
        <tr>
          <td>
            <div className="mono" style={{ fontSize: 12.5 }}>26-27/RAN-WH/TRF/118</div>
            <div style={{ color: "var(--caption)", fontSize: 12 }}>
              Transfer · RAN-WH → DEO · MUFTI
            </div>
          </td>
          <td align="right" className="tabular"><Money paise={4128500} /></td>
          <td align="right"><ApprovalPill status="pending" /></td>
        </tr>
        <tr>
          <td>
            <div className="mono" style={{ fontSize: 12.5 }}>26-27/DEO/ADJ/017</div>
            <div style={{ color: "var(--caption)", fontSize: 12 }}>
              Stock adjustment · Deoghar · count variance
            </div>
          </td>
          <td align="right" className="tabular"><Money paise={-89900} /></td>
          <td align="right"><ApprovalPill status="approved" /></td>
        </tr>
        <tr>
          <td>
            <div className="mono" style={{ fontSize: 12.5 }}>26-27/JSL/WOF/004</div>
            <div style={{ color: "var(--caption)", fontSize: 12 }}>
              Write-off · JSL · water damage, Allen Solly
            </div>
          </td>
          <td align="right" className="tabular"><Money paise={1259700} /></td>
          <td align="right"><ApprovalPill status="rejected" /></td>
        </tr>
        <tr>
          <td>
            <div className="mono" style={{ fontSize: 12.5 }}>26-27/JSL/ADJ/021</div>
            <div style={{ color: "var(--caption)", fontSize: 12 }}>
              Stock adjustment · JSL · inside tolerance
            </div>
          </td>
          <td align="right" className="tabular"><Money paise={4500} /></td>
          <td align="right"><ApprovalPill status="not_required" /></td>
        </tr>
      </tbody>
    </table>
  </div>
);

/** An unknown status is printed as it came from the server rather than hidden,
 *  and falls back to the neutral grey chip. */
export const UnknownStatus = () => (
  <div className="card" style={{ padding: 16, maxWidth: 460 }}>
    <p className="eyebrow">Fallback</p>
    <div className="chip-picker" style={{ marginTop: 10 }}>
      <ApprovalPill status="withdrawn" />
      <ApprovalPill status="not_required" />
    </div>
    <p className="lead" style={{ marginTop: 10, fontSize: 13, color: "var(--muted)" }}>
      A status the front end has not been taught yet still reaches the approver
      readable - it is never swallowed.
    </p>
  </div>
);
