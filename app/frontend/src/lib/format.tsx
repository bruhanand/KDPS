import type { ReactNode } from "react";

/** Render integer paise as INR with Indian Lakh/Crore grouping. Never floats on
 *  any write path — this is display only (the value is computed once server-side). */
export function formatINR(paise: number, opts: { short?: boolean } = {}): string {
  const rupees = paise / 100;
  if (opts.short) {
    const abs = Math.abs(rupees);
    if (abs >= 1e7) return `₹${(rupees / 1e7).toFixed(2)} Cr`;
    if (abs >= 1e5) return `₹${(rupees / 1e5).toFixed(2)} L`;
  }
  // Whole rupees show no paise at all; anything with paise shows both digits.
  // Without the minimum, ₹1,222.50 renders as "₹1,222.5", which is not money.
  const fraction = rupees % 1 === 0 ? 0 : 2;
  const grouped = new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: fraction,
    maximumFractionDigits: fraction,
  }).format(rupees);
  return `₹${grouped}`;
}

export function Money({ paise, short }: { paise: number; short?: boolean }) {
  return <span className="tabular">{formatINR(paise, { short })}</span>;
}

/** Render a rupee decimal string the server already computed ("72450.00") as
 *  INR. A few read endpoints project money that way rather than as paise, and
 *  the screens reading them were printing "72450.00" at the counter.
 *
 *  Read as text, not arithmetic: `72450.29 * 100` is 7245028.999… in float, and
 *  the integer-paise rule holds on the client too. Anything unparseable comes
 *  back untouched rather than silently rendering as ₹0. */
export function formatRupeeAmount(amount: string): string {
  const parsed = /^\s*(-?)(\d+)(?:\.(\d*))?\s*$/.exec(amount);
  if (!parsed) return amount;
  const [, sign, whole, fraction = ""] = parsed;
  const paise = Number(whole) * 100 + Number((fraction + "00").slice(0, 2));
  return `${sign}${formatINR(paise)}`;
}

/** A rupee amount as typed, in exact integer paise - or `null` when what was
 *  typed is not an amount.
 *
 *  Digit arithmetic on purpose: `25.51 * 100` is `2551.0000000000005` in binary
 *  floating point, and the server's money column refuses a non-integer rather
 *  than rounding it (ADR-0004), so the rounding must not happen here either. The
 *  mirror of `core.money.rupees_to_paise`, held to the same rule - only what a
 *  person would write as money, never a guess at what they meant. */
export function rupeesToPaise(text: string): number | null {
  // Commas are how an amount is *read back* (₹25,00,000), so someone editing one
  // is allowed to type them straight back in; spaces likewise.
  const typed = text.replace(/[,\s]/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(typed)) return null;
  const [whole, fraction = ""] = typed.split(".");
  return Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
}

/** Integer paise as a plain rupee amount for an *input box* - no grouping, no ₹,
 *  and the paise shown only when there are any (`250000000` -> `"2500000"`).
 *
 *  `formatINR` is for reading; this is for editing, and the difference matters
 *  because whatever it returns is what `rupeesToPaise` gets handed back on save.
 *  So it is the exact inverse of that function, by the same digit arithmetic: the
 *  obvious `String(paise / 100)` is a float divide sitting on a write path, which
 *  is what ADR-0004 exists to keep off one. */
export function paiseToRupees(paise: number): string {
  const whole = Math.trunc(paise);
  const sign = whole < 0 ? "-" : "";
  const abs = Math.abs(whole);
  const sub = abs % 100;
  // `abs - sub` divides by 100 exactly, so this quotient is never a float
  // approximation of an integer the way `abs / 100` can be.
  const rupees = (abs - sub) / 100;
  return sub === 0 ? `${sign}${rupees}` : `${sign}${rupees}.${String(sub).padStart(2, "0")}`;
}

/** The single SKU-grain primitive: Brand · Style · Colour · Size — never style-only. */
export function SkuLine({
  brand,
  style,
  color,
  size,
}: {
  brand: string;
  style: string;
  color: string;
  size: string;
}) {
  return (
    <span className="sku-line">
      <b>{brand}</b>
      <span className="sku-sep">·</span>
      {style}
      <span className="sku-chip">{color}</span>
      <span className="sku-chip">{size}</span>
    </span>
  );
}

const STATUS_TONE: Record<string, string> = {
  open: "green",
  eoss: "amber",
  closed: "navy",
  ok: "green",
  matched: "green",
  pending: "amber",
  blocked: "red",
  overdue: "red",
  ai: "purple",
};

export function StatusChip({ status, tone }: { status: string; tone?: string }) {
  const t = tone ?? STATUS_TONE[status.toLowerCase()] ?? "navy";
  return <span className={`chip chip-${t}`}>{status}</span>;
}

export function CommercialBadge({ label }: { label: string }) {
  const tone =
    label === "Outright"
      ? "navy"
      : label === "Correction"
        ? "blue"
        : label === "SOR"
          ? "amber"
          : "purple";
  return <span className={`chip chip-${tone}`}>{label}</span>;
}

export function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 12.5, color: "var(--muted)", fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, marginTop: 2 }} className="tabular">
        {value}
      </div>
    </div>
  );
}
