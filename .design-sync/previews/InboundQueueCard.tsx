import { InboundQueueCard } from "kdps-frontend";

const queue = {
  awaiting_pt: [
    {
      id: 311,
      number: "26-27/RAN-WH/GRN/311",
      vendor_name: "Credo Brands Marketing",
      store_code: "RAN-WH",
      invoice_number: "CBM/26-27/4417",
      received_total: 248,
      created_at: "2026-07-27T09:20:00Z",
    },
    {
      id: 312,
      number: "26-27/RAN-WH/GRN/312",
      vendor_name: "",
      store_code: "RAN-WH",
      invoice_number: "",
      received_total: 62,
      created_at: "2026-07-28T14:05:00Z",
    },
  ],
  pt_in_progress: [
    {
      id: 88,
      original_filename: "MUFTI_PT_JUL26.xlsx",
      grn_number: "26-27/RAN-WH/GRN/309",
      stage: "sent",
      stage_label: "Sent to Patna",
      blank_cell_count: 0,
    },
    {
      id: 89,
      original_filename: "LEVIS_PT_JUL26.xlsx",
      grn_number: "26-27/RAN-WH/GRN/310",
      stage: "review",
      stage_label: "In review",
      blank_cell_count: 14,
    },
  ],
  counts: { awaiting_pt: 2, pt_in_progress: 2 },
};

/** The warehouse work queue: arrivals still without a PT file, and the PTs
 *  already being made. Goods are sellable only once the PT posts at Patna. */
export const WorkQueue = () => (
  <div style={{ maxWidth: 760 }}>
    <InboundQueueCard queue={queue} />
  </div>
);

/** Everything has a PT started - the heading changes, the arrivals grid drops. */
export const AllStarted = () => (
  <div style={{ maxWidth: 760 }}>
    <InboundQueueCard
      queue={{ ...queue, awaiting_pt: [], counts: { awaiting_pt: 0, pt_in_progress: 2 } }}
    />
  </div>
);
