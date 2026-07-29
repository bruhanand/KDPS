import { ReceiptExceptions } from "kdps-frontend";

const SHORT = {
  id: 1,
  kind: "short" as const,
  kind_label: "Short",
  sku_code: "MF-JEAN-IND-40",
  design: "MFK-4471",
  color: "Indigo",
  size: "40",
  brand: "MUFTI",
  qty: 3,
  unit_cost_paise: 112500,
  note: "Carton 2 opened at Deoghar",
};

const EXTRA = {
  id: 2,
  kind: "extra" as const,
  kind_label: "Extra",
  sku_code: "LV-511-STN-34",
  design: "511-SLIM",
  color: "Stone Wash",
  size: "34",
  brand: "Levi's",
  qty: 1,
  unit_cost_paise: 189500,
  note: "Not on the transfer PT",
};

const DAMAGED = {
  id: 3,
  kind: "damaged" as const,
  kind_label: "Damaged",
  sku_code: "VH-SHRT-WHT-42",
  design: "VHSF317R081",
  color: "White",
  size: "42",
  brand: "Van Heusen",
  qty: 2,
  unit_cost_paise: 154900,
  note: "Water stain on collar",
};

/** The three outcomes a receiving store can record against a transfer: pieces
 *  missing, pieces that were never on the PT, and pieces that arrived spoiled. */
export const AllThreeOutcomes = () => (
  <div className="card" style={{ padding: 16, maxWidth: 720 }}>
    <p className="eyebrow">Receipt · 26-27/RAN-WH/TRF/118</p>
    <div style={{ marginTop: 12 }}>
      <ReceiptExceptions rows={[SHORT, EXTRA, DAMAGED]} />
    </div>
  </div>
);

/** Short is the only one that opens a gap — those pieces stay in the in-transit
 *  bucket and the source store is answerable for them until it is closed. */
export const ShortOnly = () => (
  <div className="card" style={{ padding: 16, maxWidth: 720 }}>
    <p className="eyebrow">What opened the gap</p>
    <div style={{ marginTop: 12 }}>
      <ReceiptExceptions
        rows={[
          SHORT,
          {
            ...SHORT,
            id: 4,
            sku_code: "MF-JEAN-BLK-38",
            color: "Black",
            size: "38",
            qty: 2,
            note: "Same carton, 2 short",
          },
        ]}
      />
    </div>
  </div>
);

/** How it actually sits on the transfer page: under the receipt header, with
 *  who received it, when, and what they wrote in the shortfall note. */
export const InTheReceiptCard = () => (
  <div className="card" style={{ padding: 16, maxWidth: 720 }}>
    <p className="eyebrow">Receipt</p>
    <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
      <span className="chip chip-amber">Received with exceptions</span>
      <span className="lead">14 Jul 2026</span>
      <span className="lead">
        by <b>Sunita Kumari</b> · Deoghar
      </span>
    </div>
    <p className="lead" style={{ marginTop: 10 }}>
      “Carton 2 was already open when the vehicle reached us. Counted twice with the
      driver present.”
    </p>
    <div style={{ marginTop: 14 }}>
      <ReceiptExceptions rows={[SHORT, DAMAGED]} />
    </div>
  </div>
);
