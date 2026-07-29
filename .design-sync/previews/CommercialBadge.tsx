import { CommercialBadge } from "kdps-frontend";

/** The commercial model a brand's goods arrived under. It drives ownership,
 *  the return window and when vendor liability posts, so it is shown wherever
 *  goods or a vendor bill are on screen. */
export const Models = () => (
  <div className="card" style={{ padding: 16, maxWidth: 460 }}>
    <p className="eyebrow">Commercial model</p>
    <div className="chip-picker" style={{ marginTop: 10 }}>
      <CommercialBadge label="Outright" />
      <CommercialBadge label="SOR" />
      <CommercialBadge label="Consignment" />
      <CommercialBadge label="Correction" />
    </div>
  </div>
);

/** Beside the brand it qualifies — the usual placement. */
export const AgainstBrands = () => (
  <div className="card" style={{ padding: 16, maxWidth: 460 }}>
    <p className="eyebrow">Brands at Ranchi warehouse</p>
    <table style={{ width: "100%", fontSize: 13.5, borderSpacing: "0 8px" }}>
      <tbody>
        <tr>
          <td><b>MUFTI</b></td>
          <td align="right"><CommercialBadge label="SOR" /></td>
        </tr>
        <tr>
          <td><b>Levi's</b></td>
          <td align="right"><CommercialBadge label="Outright" /></td>
        </tr>
        <tr>
          <td><b>Allen Solly</b></td>
          <td align="right"><CommercialBadge label="Consignment" /></td>
        </tr>
      </tbody>
    </table>
  </div>
);
