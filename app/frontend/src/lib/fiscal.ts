// The Indian financial year (Apr–Mar), client side (#171).
//
// The mirror of `core/fiscal.py`. It exists because a screen has to draw the
// year's twelve columns before it has any rows to draw them from — an FY grid
// with a month missing because nobody set a target for it is not a grid.
//
// Every month here is a *label plus an ISO first-of-month string*, and nothing in
// this module ever constructs a `Date` from one. `new Date("2026-04-01")` is
// parsed as UTC midnight, so west of Greenwich it renders as 31 March: the store
// grid would show a column called "Mar 2026" that the server calls April. Strings
// in, strings out, no timezone anywhere.

/** April — the month an Indian financial year opens on. */
export const FY_START_MONTH = 4;

const MONTH_NAMES = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/** One month of a financial year: what the server calls it, and what a person does. */
export interface FiscalMonth {
  /** The month's first day, ISO — the server's key for it (`2026-04-01`). */
  iso: string;
  /** The column heading (`Apr 2026`). */
  label: string;
}

const FY_LABEL = /^(\d{2})-(\d{2})$/;

/** `YY-YY` for the Apr–Mar financial year containing `on` (today by default). */
export function financialYear(on: Date = new Date()): string {
  const month = on.getMonth() + 1;
  const start = month >= FY_START_MONTH ? on.getFullYear() : on.getFullYear() - 1;
  return `${String(start % 100).padStart(2, "0")}-${String((start + 1) % 100).padStart(2, "0")}`;
}

/** The twelve months of financial year `fy`, April first.
 *
 *  Returns an empty list for anything that is not an `YY-YY` label whose halves
 *  are consecutive years — the same rule the server applies, so a screen cannot
 *  render a year the API would refuse. */
export function financialYearMonths(fy: string): FiscalMonth[] {
  const matched = FY_LABEL.exec(fy.trim());
  if (!matched) return [];
  const [first, second] = [Number(matched[1]), Number(matched[2])];
  if (second !== (first + 1) % 100) return [];
  const start = 2000 + first;
  const order = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3];
  return order.map((month) => {
    const year = month >= FY_START_MONTH ? start : start + 1;
    return {
      iso: `${year}-${String(month).padStart(2, "0")}-01`,
      label: `${MONTH_NAMES[month - 1]} ${year}`,
    };
  });
}

/** A short list of financial years to choose between, newest first — last year,
 *  this one, and the next, which is every year a target is ever set for: one
 *  being planned, one being sold, one being looked back at. */
export function financialYearChoices(on: Date = new Date()): string[] {
  const thisYear = financialYear(on);
  const start = 2000 + Number(thisYear.slice(0, 2));
  return [start + 1, start, start - 1].map(
    (year) => `${String(year % 100).padStart(2, "0")}-${String((year + 1) % 100).padStart(2, "0")}`,
  );
}
