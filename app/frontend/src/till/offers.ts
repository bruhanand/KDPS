// The offer engine at the counter (#183, D5, grill Q9).
//
// This file is a port of `app/backend/offers/resolution.py`, function for
// function, and the two are held together by `app/backend/offers/vectors/*.json`
// - the same golden carts, run through both engines, compared to the paisa
// (`offers.vectors.test.ts`). That pairing is the whole point of the slice: the
// same cart is priced twice, once here on a counter machine that may not have
// seen head office for a day, and again on the server when the bill syncs. If
// the two ever disagree the receipt and the books disagree, and the receipt is
// already in a bag on a bus to Deoghar.
//
// So: **no changes here without the same change there, and a vector that proves
// it.** The comments are deliberately thinner than the Python's - that module is
// where the reasoning lives, and two copies of an explanation drift apart faster
// than two copies of an algorithm.
//
// Integer paise everywhere (ADR-0004). Percentages are two-decimal strings and
// become hundredths of a percent; half-up is written as integer arithmetic so
// the two languages round the same way rather than the same way usually.

import type { NoOffer, OfferCredit, OfferEvidence, StackedCredit, TillOffer } from "./types";

export const LAYER_BRAND = "brand";
/** Layer 1 claims a line; these two stack onto what it left, in this order. */
export const ADD_ON_LAYERS = ["storewide", "bank"] as const;

const TRIGGER_NONE = "none";
const TRIGGER_SPEND = "spend";
const TRIGGER_QTY = "qty";
const TRIGGER_GROUP = "group";

const REWARD_PCT_OFF = "pct_off";
const REWARD_AMT_OFF = "amt_off";
const REWARD_ITEM_FREE = "item_free";
const REWARD_FIXED_PRICE = "fixed_price";
const REWARD_GIFT = "gift";

/** What an add-on may do to a price a brand offer has already reduced. */
const ADD_ON_REWARDS = new Set([REWARD_PCT_OFF, REWARD_AMT_OFF]);
const FALLBACK_REWARDS = new Set([REWARD_PCT_OFF, REWARD_AMT_OFF, REWARD_FIXED_PRICE]);

/** One row of the bill, as the rulebook needs to see it. */
export interface OfferCartLine {
  line_no: number;
  brand: string;
  item: string;
  design: string;
  barcode: string;
  season: string;
  qty: number;
  mrp_paise: number;
  no_discount: boolean;
}

export interface OfferCart {
  lines: OfferCartLine[];
  /** The till's own clock, `YYYY-MM-DD`. Every rule's dates are judged against
   *  this and nothing else, so an offline counter stops a dead offer on time. */
  day: string;
  /** Gift offers the counter could not honour, by id (D5 Q11). */
  declinedGifts?: number[];
}

// The evidence shapes live in `./types`, with the rest of what travels to the
// server: they are written here but read there, months later, by the daily
// applied-versus-rulebook check.
export type { NoOffer, OfferCredit, OfferEvidence, StackedCredit };

export interface Entitlement {
  offer_id: number;
  offer_name: string;
  barcode: string;
  token_price_paise: number;
}

export interface LineOutcome {
  line_no: number;
  discount_paise: number;
  /** The brand-layer winner - the one the sale line's `offer_id` records. */
  offer_id: number | null;
  /** `{}` when nothing applied, matching what the server writes. */
  evidence: OfferEvidence | NoOffer;
}

export interface Resolution {
  lines: LineOutcome[];
  entitlements: Entitlement[];
  total_discount_paise: number;
}

// --- integer arithmetic, mirrored from Python ------------------------------

/** `"7.50"` → 750. Off the digits, never through a float (ADR-0004). */
export function hundredths(value: unknown): number {
  const text = String(value ?? "").trim();
  if (!text) return 0;
  const sign = text.startsWith("-") ? -1 : 1;
  const [whole = "", frac = ""] = text.replace(/^[+-]/, "").split(".");
  const w = whole || "0";
  const f = (frac + "00").slice(0, 2);
  if (!/^\d+$/.test(w) || !/^\d+$/.test(f)) throw new Error(`'${text}' is not a percentage`);
  return sign * (Number(w) * 100 + Number(f));
}

/** `amount x percent`, half-up, in integers only. */
export function percentOf(amountPaise: number, percentHundredths: number): number {
  if (amountPaise <= 0 || percentHundredths <= 0) return 0;
  return Math.floor((2 * amountPaise * percentHundredths + 10_000) / 20_000);
}

/** A brand or category name reduced to what two spellings of it share. */
function normalise(text: unknown): string {
  return String(text ?? "")
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "");
}

function names(scope: Record<string, unknown>, key: string): Set<string> {
  const raw = scope[key];
  if (!raw) return new Set();
  const list = Array.isArray(raw) ? raw : [raw];
  return new Set(list.map(normalise).filter(Boolean));
}

// --- scope -----------------------------------------------------------------

function facets(line: OfferCartLine): [string, string][] {
  return [
    ["brands", line.brand],
    ["categories", line.item],
    ["styles", line.design],
    ["barcodes", line.barcode],
    ["seasons", line.season],
  ];
}

export function covers(rule: TillOffer, line: OfferCartLine, day: string): boolean {
  if (day < rule.starts_on) return false;
  if (rule.ends_on !== null && day > rule.ends_on) return false;
  // The AMM/NOD flag beats every rule there is, storewide included (D5 Q3).
  if (line.no_discount) return false;
  if (line.qty <= 0 || line.mrp_paise <= 0) return false;
  if (rule.brand && normalise(rule.brand) !== normalise(line.brand)) return false;

  const scope = rule.item_scope ?? {};
  for (const [key, value] of facets(line)) {
    const wanted = names(scope, key);
    if (wanted.size && !wanted.has(normalise(value))) return false;
  }
  const floor = scope.mrp_min_paise;
  if (floor != null && line.mrp_paise < Number(floor)) return false;
  const ceiling = scope.mrp_max_paise;
  if (ceiling != null && line.mrp_paise > Number(ceiling)) return false;

  const exclude = (scope.exclude ?? {}) as Record<string, unknown>;
  return !facets(line).some(([key, value]) => names(exclude, key).has(normalise(value)));
}

// --- proposals -------------------------------------------------------------

interface Proposal {
  rule: TillOffer;
  shares: Map<number, number>;
  total: number;
}

type Dials = Record<string, unknown>;

function slabsOf(rule: TillOffer): Dials[] {
  const raw = (rule.trigger_config ?? {}).slabs;
  return Array.isArray(raw) ? (raw as Dials[]) : [];
}

/** The step of a ladder this cart has reached; `null` means none of them. */
function reachedSlab(rule: TillOffer, spendPaise: number, units: number): Dials | null {
  if (rule.trigger_type === TRIGGER_NONE || rule.trigger_type === TRIGGER_GROUP) return {};
  let key: string;
  let reached: number;
  if (rule.trigger_type === TRIGGER_SPEND) {
    key = "min_paise";
    reached = spendPaise;
  } else if (rule.trigger_type === TRIGGER_QTY) {
    key = "min_qty";
    reached = units;
  } else {
    return null;
  }
  const qualifying = slabsOf(rule)
    .filter((slab) => reached >= Number(slab[key] ?? 0))
    .sort((a, b) => Number(a[key] ?? 0) - Number(b[key] ?? 0));
  return qualifying.length ? qualifying[qualifying.length - 1] : null;
}

/** The reward's dials, with the reached step's own values on top. */
function rewardParams(rule: TillOffer, slab: Dials): Dials {
  const params: Dials = { ...(rule.reward_config ?? {}) };
  for (const [key, value] of Object.entries(slab)) {
    if (!key.startsWith("min_")) params[key] = value;
  }
  return params;
}

/**
 * Share a lump sum across lines in proportion to what they are worth.
 *
 * Largest-remainder, so the parts sum to exactly the lump. The spare paisa goes
 * to the dearest line first, then the earliest - arbitrary, but it has to be
 * decided or the two engines disagree by a paisa on a three-line bill.
 */
function spread(amountPaise: number, weights: [number, number][]): Map<number, number> {
  const totalWeight = weights.reduce((n, [, w]) => n + w, 0);
  const shares = new Map<number, number>();
  if (amountPaise <= 0 || totalWeight <= 0) return shares;
  const remainders: [number, number, number][] = [];
  for (const [lineNo, weight] of weights) {
    const numerator = amountPaise * weight;
    shares.set(lineNo, Math.floor(numerator / totalWeight));
    remainders.push([numerator % totalWeight, weight, lineNo]);
  }
  let spare = amountPaise - [...shares.values()].reduce((n, v) => n + v, 0);
  remainders.sort((a, b) => b[0] - a[0] || b[1] - a[1] || a[2] - b[2]);
  for (const [, , lineNo] of remainders) {
    if (spare <= 0) break;
    shares.set(lineNo, (shares.get(lineNo) ?? 0) + 1);
    spare -= 1;
  }
  return shares;
}

/** Buy X get Y: dearest first, the cheapest of each group free. */
function freeUnits(
  lines: OfferCartLine[],
  base: Map<number, number>,
  config: Record<string, unknown>,
): Map<number, number> {
  const buy = Math.max(Number(config.buy ?? 0), 0);
  const get = Math.max(Number(config.get ?? 0), 0);
  const shares = new Map<number, number>();
  if (buy <= 0 || get <= 0) return shares;
  const repeat = config.repeat === undefined ? true : Boolean(config.repeat);

  const units: [number, number][] = [];
  for (const line of lines) {
    const remaining = base.get(line.line_no) ?? 0;
    if (remaining <= 0) continue;
    const unitPrice = Math.floor(remaining / line.qty);
    for (let i = 0; i < line.qty; i += 1) units.push([unitPrice, line.line_no]);
  }
  units.sort((a, b) => b[0] - a[0] || a[1] - b[1]);

  const group = buy + get;
  let taken = 0;
  while (units.length - taken >= group) {
    for (const [price, lineNo] of units.slice(taken + buy, taken + group)) {
      shares.set(lineNo, (shares.get(lineNo) ?? 0) + price);
    }
    taken += group;
    if (!repeat) break;
  }
  return shares;
}

function sharesFor(
  rewardType: string,
  rule: TillOffer,
  covered: OfferCartLine[],
  base: Map<number, number>,
  params: Dials,
): Map<number, number> {
  const shares = new Map<number, number>();
  if (rewardType === REWARD_PCT_OFF) {
    const percent = hundredths(params.percent ?? "0");
    for (const line of covered) {
      shares.set(line.line_no, percentOf(base.get(line.line_no) ?? 0, percent));
    }
    return shares;
  }
  if (rewardType === REWARD_AMT_OFF) {
    return spread(
      Number(params.amount_paise ?? 0),
      covered.map((line) => [line.line_no, base.get(line.line_no) ?? 0]),
    );
  }
  if (rewardType === REWARD_FIXED_PRICE) {
    const price = Number(params.price_paise ?? 0);
    for (const line of covered) {
      const perUnit = Math.max(Math.floor((base.get(line.line_no) ?? 0) / line.qty) - price, 0);
      shares.set(line.line_no, perUnit * line.qty);
    }
    return shares;
  }
  if (rewardType === REWARD_ITEM_FREE) {
    return freeUnits(covered, base, rule.trigger_config ?? {});
  }
  return shares;
}

function propose(
  rule: TillOffer,
  lines: OfferCartLine[],
  base: Map<number, number>,
  day: string,
): Proposal | null {
  const covered = lines.filter((line) => covers(rule, line, day) && (base.get(line.line_no) ?? 0) > 0);
  if (!covered.length) return null;
  const slab = reachedSlab(
    rule,
    covered.reduce((n, l) => n + l.mrp_paise * l.qty, 0),
    covered.reduce((n, l) => n + l.qty, 0),
  );
  if (slab === null) return null;

  const raw = sharesFor(rule.reward_type, rule, covered, base, rewardParams(rule, slab));
  const shares = new Map<number, number>();
  for (const [lineNo, paise] of raw) {
    // No rule may give away more of a line than the line still costs.
    if (paise > 0) shares.set(lineNo, Math.min(paise, base.get(lineNo) ?? 0));
  }
  if (!shares.size) return null;
  return { rule, shares, total: [...shares.values()].reduce((n, v) => n + v, 0) };
}

// --- gifts, which are earned rather than deducted --------------------------

function splitGifts(
  rules: TillOffer[],
  cart: OfferCart,
): { keep: TillOffer[]; earned: Entitlement[] } {
  const declined = new Set(cart.declinedGifts ?? []);
  const keep: TillOffer[] = [];
  const earned: Entitlement[] = [];
  for (const rule of rules) {
    if (rule.reward_type !== REWARD_GIFT) {
      keep.push(rule);
      continue;
    }
    const covered = cart.lines.filter((line) => covers(rule, line, cart.day));
    if (!covered.length) continue;
    const slab = reachedSlab(
      rule,
      covered.reduce((n, l) => n + l.mrp_paise * l.qty, 0),
      covered.reduce((n, l) => n + l.qty, 0),
    );
    if (slab === null) continue;
    const params = rewardParams(rule, slab);
    if (!declined.has(rule.id)) {
      earned.push({
        offer_id: rule.id,
        offer_name: rule.name,
        barcode: String(params.gift_barcode ?? ""),
        token_price_paise: Number(params.token_price_paise ?? 0),
      });
      continue;
    }
    const fallback = (params.fallback ?? {}) as Dials;
    const rewardType = String(fallback.reward_type ?? "");
    if (!FALLBACK_REWARDS.has(rewardType)) continue;
    keep.push({
      ...rule,
      reward_type: rewardType,
      reward_config: (fallback.reward_config ?? {}) as Record<string, unknown>,
    });
  }
  return { keep, earned };
}

// --- the greedy loop -------------------------------------------------------

interface Awards {
  discount: Map<number, number>;
  winner: Map<number, Proposal>;
  stack: Map<number, [Proposal, number][]>;
  beat: Map<number, [Proposal, number][]>;
}

function push<T>(into: Map<number, T[]>, key: number, value: T): void {
  const found = into.get(key);
  if (found) found.push(value);
  else into.set(key, [value]);
}

/** One layer, resolved to a fixed point. See the Python for why it loops. */
function runLayer(
  rules: TillOffer[],
  cart: OfferCart,
  awards: Awards,
  exclusive: boolean,
): void {
  const claimed = new Set<number>();
  let remaining = [...rules];
  let firstRound = true;

  while (remaining.length) {
    const openLines = cart.lines.filter((line) => !claimed.has(line.line_no));
    if (!openLines.length) break;
    const base = new Map(
      openLines.map((line) => [
        line.line_no,
        line.mrp_paise * line.qty - (awards.discount.get(line.line_no) ?? 0),
      ]),
    );
    const proposals = remaining
      .map((rule) => propose(rule, openLines, base, cart.day))
      .filter((p): p is Proposal => p !== null)
      .sort(
        (a, b) => b.total - a.total || a.rule.priority - b.rule.priority || a.rule.id - b.rule.id,
      );
    if (!proposals.length) break;
    const best = proposals[0];

    if (firstRound && exclusive) {
      for (const other of proposals.slice(1)) {
        for (const [lineNo, paise] of [...other.shares].sort((a, b) => a[0] - b[0])) {
          push(awards.beat, lineNo, [other, paise]);
        }
      }
      firstRound = false;
    }

    for (const [lineNo, paise] of best.shares) {
      awards.discount.set(lineNo, (awards.discount.get(lineNo) ?? 0) + paise);
      if (exclusive) awards.winner.set(lineNo, best);
      else push(awards.stack, lineNo, [best, paise]);
      claimed.add(lineNo);
    }
    remaining = remaining.filter((rule) => rule.id !== best.rule.id);
  }
}

function evidenceFor(line: OfferCartLine, awards: Awards): OfferEvidence | NoOffer {
  const saved = awards.discount.get(line.line_no) ?? 0;
  if (saved <= 0) return {};
  const winner = awards.winner.get(line.line_no);
  return {
    offer_id: winner ? winner.rule.id : null,
    offer_name: winner ? winner.rule.name : "",
    layer: winner ? winner.rule.layer : "",
    saved_paise: saved,
    beat: (awards.beat.get(line.line_no) ?? [])
      .filter(([p]) => !winner || p.rule.id !== winner.rule.id)
      .map(([p, paise]) => ({
        offer_id: p.rule.id,
        offer_name: p.rule.name,
        saved_paise: paise,
      })),
    stack: (awards.stack.get(line.line_no) ?? []).map(([p, paise]) => ({
      offer_id: p.rule.id,
      offer_name: p.rule.name,
      layer: p.rule.layer,
      saved_paise: paise,
    })),
  };
}

/** Price a cart against the rulebook. The one entry point. */
export function resolveOffers(cart: OfferCart, rules: TillOffer[]): Resolution {
  const awards: Awards = {
    discount: new Map(),
    winner: new Map(),
    stack: new Map(),
    beat: new Map(),
  };

  const { keep, earned } = splitGifts(
    rules.filter((rule) => rule.layer === LAYER_BRAND),
    cart,
  );
  runLayer(keep, cart, awards, true);

  for (const layer of ADD_ON_LAYERS) {
    runLayer(
      rules.filter(
        (rule) => rule.layer === layer && rule.combinable && ADD_ON_REWARDS.has(rule.reward_type),
      ),
      cart,
      awards,
      false,
    );
  }

  const lines = cart.lines.map((line) => ({
    line_no: line.line_no,
    discount_paise: awards.discount.get(line.line_no) ?? 0,
    offer_id: awards.winner.get(line.line_no)?.rule.id ?? null,
    evidence: evidenceFor(line, awards),
  }));
  return {
    lines,
    entitlements: earned.sort((a, b) => a.offer_id - b.offer_id),
    total_discount_paise: lines.reduce((n, l) => n + l.discount_paise, 0),
  };
}
