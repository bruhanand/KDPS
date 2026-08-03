import { SkuLine } from "kdps-frontend";

/** The single SKU-grain primitive. KDPS stock is Style x Size x Colour — never
 *  style-only — so any list of goods identifies its rows with this. */
export const InAList = () => (
  <div className="card" style={{ padding: 16, maxWidth: 460, display: "grid", gap: 12 }}>
    <p className="eyebrow">Bill lines</p>
    <SkuLine brand="MUFTI" style="MFK-4471" color="Indigo" size="40" />
    <SkuLine brand="Levi's" style="511-SLIM" color="Stone Wash" size="34" />
    <SkuLine brand="Allen Solly" style="ASKPCRGFN12345" color="Navy" size="L" />
    <SkuLine brand="Van Heusen" style="VHSF317R081" color="White" size="42" />
  </div>
);

/** Same style, different size and colour — four separate SKUs, four separate
 *  stock balances. This is the distinction the component exists to make visible. */
export const SameStyleDifferentSku = () => (
  <div className="card" style={{ padding: 16, maxWidth: 460, display: "grid", gap: 12 }}>
    <p className="eyebrow">One style, four SKUs</p>
    <SkuLine brand="MUFTI" style="MFK-4471" color="Indigo" size="38" />
    <SkuLine brand="MUFTI" style="MFK-4471" color="Indigo" size="40" />
    <SkuLine brand="MUFTI" style="MFK-4471" color="Black" size="38" />
    <SkuLine brand="MUFTI" style="MFK-4471" color="Black" size="40" />
  </div>
);
