// What a scan means, decided on the device (#181, D10 §4, requirement A2).
//
// A barcode is a scan-alias, not an identity. The same tag under two buying
// cohorts is two lots at two ticket prices, and the counter has to say which one
// walked out of the shop - offline, in the time between the beep and the line
// appearing.
//
// The ladder is the requirement's, exactly:
//
//   · one live batch under the barcode - straight through, no question;
//   · several - the **oldest live** one, because that is what a store sells first;
//   · genuinely ambiguous - a one-tap "which season?", the only question this
//     screen is ever allowed to ask mid-sale, and it never blocks the bill.
//
// "Oldest" is the season master's own ordering and not the alphabet: seasons are
// named, never dated (`masters.Season` is explicit), so FW25 sorting before SS26
// is an accident of the letters. The ordering rides down in the dataset for that
// reason, and this file is the mirror of `sell.services.resolve._season_rank`.
//
// One honest difference from the server. `resolve_piece` breaks its first tie on
// the season denormalised onto the store's stock row, which the dataset does not
// send (`stock` is a barcode and a quantity, H2). It costs nothing: the till
// writes the season it picked onto the line, and the accept pipeline honours an
// exact `(barcode, season)` outright rather than re-deciding. The two only need
// to agree about what a *good* answer looks like, and they do.

import type { TillItem, TillSeason, TillStock } from "./types";

/** Everything the counter knows that bears on a scan. */
export interface ScanWorld {
  items: TillItem[];
  stock: TillStock[];
  seasons: TillSeason[];
}

export interface ScanResult {
  /** The code as it will be billed - trimmed of whatever the wedge sent. */
  barcode: string;
  /** The piece the line takes unless a person says otherwise. Null when the
   *  counter has never heard of this barcode: a sold-before-inward line (#186),
   *  which is a manual line rather than a refused customer. */
  chosen: TillItem | null;
  /** Every season this barcode is known in, the choosable one first. */
  candidates: TillItem[];
  /** What the counter's own copy says is on the shelf under this barcode. Per
   *  barcode, not per season - `StockOnHand` is one row per (store, barcode), so
   *  there is no per-season count to show. */
  stock: number;
  /** More than one season to choose from, so the line offers the one-tap ask. */
  ambiguous: boolean;
}

/**
 * Rank two season names: negative when `a` should be billed first.
 *
 * A closed season sorts behind every open one however old it is, then the
 * master's own `sort_order`, then the name - so a counter scanning the same
 * piece twice gets the same answer twice. A season the master has never heard of
 * sorts last, not first: it is far more likely a typo on a PT than the oldest
 * thing in the shop.
 */
export function olderSeasonFirst(seasons: TillSeason[], a: string, b: string): number {
  const [closedA, orderA] = rank(seasons, a);
  const [closedB, orderB] = rank(seasons, b);
  return closedA - closedB || orderA - orderB || a.localeCompare(b);
}

const UNKNOWN: [number, number] = [1, Number.MAX_SAFE_INTEGER];

function rank(seasons: TillSeason[], name: string): [number, number] {
  const known = seasons.find((s) => s.code === name || s.name === name);
  if (!known) return UNKNOWN;
  return [known.status === "closed" ? 1 : 0, known.sort_order];
}

/**
 * The pieces a typed fragment could mean - the scan box's other job.
 *
 * D10 has one box doing both: a wedge types a barcode into it, and a person
 * types a name or a design number into it for the tag that will not scan or is
 * not there at all. Which of the two happened is not a mode the cashier picks -
 * a code that resolves is a scan and anything else is a search.
 *
 * One row per (barcode, season), because that is what a line is. Ranked by where
 * the match landed - the design number a person read off a tag beats a word
 * buried in an item name - and capped, because this feeds a list somebody reads
 * standing up.
 */
export function searchPieces(items: TillItem[], query: string, limit = 8): TillItem[] {
  const q = query.trim().toLowerCase();
  if (q.length < 2) return [];
  const hits: { item: TillItem; rank: number }[] = [];
  for (const row of items) {
    const rank = matchRank(row, q);
    if (rank !== null) hits.push({ item: row, rank });
  }
  return hits
    .sort((a, b) => a.rank - b.rank || a.item.design.localeCompare(b.item.design))
    .slice(0, limit)
    .map((hit) => hit.item);
}

function matchRank(row: TillItem, q: string): number | null {
  const design = row.design.toLowerCase();
  if (design.startsWith(q)) return 0;
  if (row.barcode.toLowerCase().includes(q)) return 1;
  if (design.includes(q)) return 2;
  if (row.brand.toLowerCase().includes(q)) return 3;
  if (row.item.toLowerCase().includes(q)) return 4;
  return null;
}

/** What a scanned code resolves to, and what the counter should be told about it. */
export function resolveScan(code: string, world: ScanWorld): ScanResult {
  const barcode = code.trim();
  const candidates = world.items
    .filter((row) => row.barcode === barcode)
    .sort((a, b) => olderSeasonFirst(world.seasons, a.season, b.season));
  return {
    barcode,
    chosen: candidates[0] ?? null,
    candidates,
    stock: world.stock.find((row) => row.barcode === barcode)?.qty ?? 0,
    ambiguous: candidates.length > 1,
  };
}
