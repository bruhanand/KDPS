import { ListSearchBar, StatusChip } from "kdps-frontend";

// The box plus the count of what it found. The count travels with the control,
// so "the number on screen reflects the searched set" cannot be forgotten by a
// screen. Controlled, so each cell pins one settled state.
const noop = () => {};

/** Nothing typed: the count is simply how many rows the list is showing. */
export const Unsearched = () => (
  <div className="card" style={{ padding: 18, maxWidth: 580 }}>
    <p className="eyebrow" style={{ marginBottom: 10 }}>Bookings</p>
    <ListSearchBar
      value=""
      onChange={noop}
      placeholder="Search vendor, brand or booking number"
      label="Search bookings"
      testId="booking-search"
      noun="booking"
      count={128}
      loading={false}
    />
  </div>
);

/** A term typed: the count says what it matched, quoting the term back so the
 *  person can see the list is filtered and not empty. */
export const Searched = () => (
  <div className="card" style={{ padding: 18, maxWidth: 580 }}>
    <p className="eyebrow" style={{ marginBottom: 10 }}>Bookings</p>
    <ListSearchBar
      value="MUFTI"
      onChange={noop}
      placeholder="Search vendor, brand or booking number"
      label="Search bookings"
      testId="booking-search"
      noun="booking"
      count={6}
      loading={false}
    />
  </div>
);

/** Loading hides the count entirely. A count of a list that has not arrived is
 *  a lie, not a zero — and "0 transfers" would read as "nothing here". */
export const Loading = () => (
  <div className="card" style={{ padding: 18, maxWidth: 580 }}>
    <p className="eyebrow" style={{ marginBottom: 10 }}>Transfers · loading</p>
    <ListSearchBar
      value="RAN-WH"
      onChange={noop}
      placeholder="Search transfer number, store or brand"
      label="Search transfers"
      testId="transfer-search"
      noun="transfer"
      count={0}
      loading
    />
  </div>
);

/** In place, over the rows it narrows — and the singular, because one match
 *  reads "1 transfer" and not "1 transfers". */
export const OverAList = () => (
  <div className="card" style={{ padding: 18, maxWidth: 580 }}>
    <p className="eyebrow" style={{ marginBottom: 10 }}>Transfers · Ranchi warehouse</p>
    <ListSearchBar
      value="DEO"
      onChange={noop}
      placeholder="Search transfer number, store or brand"
      label="Search transfers"
      testId="transfer-search"
      noun="transfer"
      count={3}
      loading={false}
    />
    <table style={{ width: "100%", fontSize: 13.5, borderSpacing: "0 9px" }}>
      <tbody>
        <tr>
          <td className="mono">26-27/RAN-WH/TRF/118</td>
          <td className="muted-cell">Deoghar</td>
          <td align="right"><StatusChip status="Matched" /></td>
        </tr>
        <tr>
          <td className="mono">26-27/RAN-WH/TRF/121</td>
          <td className="muted-cell">Deoghar</td>
          <td align="right"><StatusChip status="Pending" /></td>
        </tr>
        <tr>
          <td className="mono">26-27/RAN-WH/TRF/126</td>
          <td className="muted-cell">Deoghar</td>
          <td align="right"><StatusChip status="Open" /></td>
        </tr>
      </tbody>
    </table>
  </div>
);
