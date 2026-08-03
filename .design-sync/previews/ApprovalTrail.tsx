import { ApprovalTrail } from "kdps-frontend";

// The shape mirrors ApprovalReadSerializer - the trail needs the whole object,
// not just the status, because it prints who asked, who decided and when.
type Approval = Parameters<typeof ApprovalTrail>[0]["approval"];

const base = {
  id: 4411,
  kind: "transfer",
  kind_label: "Transfer",
  title: "26-27/RAN-WH/TRF/118 · Ranchi warehouse → Deoghar",
  object_id: 118,
  store: 3,
  store_code: "RAN-WH",
  store_name: "Ranchi warehouse",
  value_paise: 4128500,
  made_by: 21,
  made_by_name: "Rakesh Kumar",
  requested_by: 21,
  requested_by_name: "Rakesh Kumar",
  requested_at: "2026-07-27T09:20:00Z",
  decided_by: null,
  decided_by_name: "",
  decided_at: null,
  reason: "",
};

/** The everyday case: the store person raised it, nobody has looked yet. The
 *  document cannot post until the Operations Head clears it. */
export const WaitingForApproval = () => (
  <div style={{ maxWidth: 520 }}>
    <ApprovalTrail
      createdByName="Rakesh Kumar"
      createdAt="2026-07-27T09:18:00Z"
      approval={{ ...base, status: "pending" } as Approval}
    />
  </div>
);

/** Cleared. The decision line carries the decider and the moment, so the record
 *  answers "who let this move" without opening another screen. */
export const ApprovedByOpsHead = () => (
  <div style={{ maxWidth: 520 }}>
    <ApprovalTrail
      createdByName="Rakesh Kumar"
      createdAt="2026-07-27T09:18:00Z"
      approval={
        {
          ...base,
          status: "approved",
          decided_by: 4,
          decided_by_name: "Sunita Agarwal (Operations Head)",
          decided_at: "2026-07-27T11:42:00Z",
          reason: "MUFTI stock needed at Deoghar for the weekend",
        } as Approval
      }
    />
  </div>
);

/** Refused, with the reason on the record. A refused draft can never post, so
 *  "Ask again" is the only way out - it raises a fresh request. */
export const RejectedWithReason = () => (
  <div style={{ maxWidth: 520 }}>
    <ApprovalTrail
      createdByName="Priya Sharma"
      createdAt="2026-07-26T15:05:00Z"
      approval={
        {
          ...base,
          id: 4390,
          kind: "writeoff",
          kind_label: "Write-off",
          title: "26-27/JSL/WOF/004 · Allen Solly, water damage",
          object_id: 4,
          store: 5,
          store_code: "JSL",
          store_name: "Jamshedpur",
          value_paise: 1259700,
          made_by: 33,
          made_by_name: "Priya Sharma",
          requested_by: 33,
          requested_by_name: "Priya Sharma",
          requested_at: "2026-07-26T15:06:00Z",
          status: "rejected",
          decided_by: 4,
          decided_by_name: "Sunita Agarwal (Operations Head)",
          decided_at: "2026-07-26T18:30:00Z",
          reason: "Send the pieces back to the brand instead - Allen Solly is on SOR",
        } as Approval
      }
      askAgainPath="/api/writeoffs/4/ask-again"
    />
  </div>
);

/** Asked again after a refusal, by a different colleague. The refusal stays
 *  below under "Earlier" - the trail never loses a decision. */
export const AskedAgainAfterRejection = () => (
  <div style={{ maxWidth: 520 }}>
    <ApprovalTrail
      createdByName="Priya Sharma"
      createdAt="2026-07-26T15:05:00Z"
      approval={
        {
          ...base,
          id: 4402,
          kind: "writeoff",
          kind_label: "Write-off",
          title: "26-27/JSL/WOF/004 · Allen Solly, water damage",
          object_id: 4,
          store: 5,
          store_code: "JSL",
          store_name: "Jamshedpur",
          value_paise: 1259700,
          made_by: 33,
          made_by_name: "Priya Sharma",
          requested_by: 12,
          requested_by_name: "Manoj Verma (Store Manager, JSL)",
          requested_at: "2026-07-28T10:15:00Z",
          status: "pending",
        } as Approval
      }
      history={[
        {
          ...base,
          id: 4390,
          status: "rejected",
          decided_by: 4,
          decided_by_name: "Sunita Agarwal (Operations Head)",
          decided_at: "2026-07-26T18:30:00Z",
          reason: "Send the pieces back to the brand instead - Allen Solly is on SOR",
        },
      ] as never}
    />
  </div>
);
