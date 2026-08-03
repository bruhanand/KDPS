import { Combobox } from "kdps-frontend";

const BRANDS = [
  "ALLEN SOLLY", "ARROW", "BEING HUMAN", "BLACKBERRYS", "CELIO", "FLYING MACHINE",
  "JACK & JONES", "LEE", "LEVI'S", "LOUIS PHILIPPE", "MUFTI", "PEPE JEANS",
  "PETER ENGLAND", "SPYKAR", "U.S. POLO ASSN.", "VAN HEUSEN", "WRANGLER",
];

const noop = () => {};

/** Select-only searchable dropdown: the Excel data-validation field, not a text
 *  input. Only a listed value can ever be committed - free text never enters. */
export const FieldSize = () => (
  <div className="card" style={{ padding: 18, maxWidth: 420, display: "grid", gap: 14 }}>
    <div>
      <label className="eyebrow" style={{ display: "block", marginBottom: 6 }}>Brand</label>
      <Combobox value="MUFTI" options={BRANDS} onChange={noop} />
    </div>
    <div>
      <label className="eyebrow" style={{ display: "block", marginBottom: 6 }}>Brand (empty)</label>
      <Combobox value="" options={BRANDS} onChange={noop} placeholder="Select a brand…" />
    </div>
    <div>
      <label className="eyebrow" style={{ display: "block", marginBottom: 6 }}>Locked (no clear)</label>
      <Combobox value="LEVI'S" options={BRANDS} onChange={noop} allowClear={false} />
    </div>
  </div>
);

/** `size="cell"` is the in-table form, used when a whole grid column is mapped
 *  one row at a time. */
export const CellSize = () => (
  <div className="card" style={{ padding: 18, maxWidth: 480 }}>
    <p className="eyebrow" style={{ marginBottom: 10 }}>PT mapper · brand column</p>
    <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: "8px 14px", alignItems: "center", fontSize: 12.5 }}>
      <span className="mono">MFK-4471</span>
      <Combobox value="MUFTI" options={BRANDS} onChange={noop} size="cell" />
      <span className="mono">511-SLIM</span>
      <Combobox value="" options={BRANDS} onChange={noop} size="cell" placeholder="Unmapped" />
      <span className="mono">ASKPCRGFN12345</span>
      <Combobox value="ALLEN SOLLY" options={BRANDS} onChange={noop} size="cell" />
    </div>
  </div>
);
