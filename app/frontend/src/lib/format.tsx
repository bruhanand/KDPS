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
  const grouped = new Intl.NumberFormat("en-IN", {
    maximumFractionDigits: rupees % 1 === 0 ? 0 : 2,
  }).format(rupees);
  return `₹${grouped}`;
}

export function Money({ paise, short }: { paise: number; short?: boolean }) {
  return <span className="tabular">{formatINR(paise, { short })}</span>;
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
