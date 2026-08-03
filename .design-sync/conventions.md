# Building with the KDPS operating system

This is the design system of the live KDPS retail ERP - a browser PWA used by
staff in 50+ stores and warehouses across Bihar and Jharkhand. Dense, calm,
paper-warm; it is a working tool, not a marketing surface.

## Setup

No provider or theme wrapper is needed. Load `styles.css` (it `@import`s the
whole system) and render components from the library directly.

Light and dark are one token set. Dark mode is a single override block on
`html[data-theme="dark"]`, so **every colour must be a token**. A hardcoded hex
looks right in light mode and breaks in dark - there is no second dark
stylesheet to fix it in.

## The styling idiom

CSS custom properties plus a small global class vocabulary. There are **no
utility classes** (this is not Tailwind) and **no style props**. Use a class
when one exists; use inline `style` only for layout glue - grid, gap, widths.

### Tokens

| Group | Names |
|---|---|
| Surfaces | `--paper` (app background), `--surface` (card/panel), `--sidebar`, `--inner` (inner wash), `--hairline` (borders/dividers) |
| Brand | `--navy`, `--navy2`, `--rust`, `--rust-soft`, `--brand-red` |
| Text | `--ink`, `--muted`, `--caption` |
| Status (x6, each a triple) | `--green` / `--green-bg` / `--green-bd`, and the same for `--amber`, `--blue`, `--purple`, `--red`, `--grey` |
| Shape | `--radius` (16px), `--radius-inner` (11px), `--shadow-rest`, `--shadow-hover` |
| Type | system fonts; `--mono` for IDs, voucher numbers and money |
| Layout | `--sidebar-w`, `--topbar-h` |

Two traps. `--navy` is a **text** colour - for navy as a solid fill under white
text use `--navy-fill` / `--navy-fill-hover`. And `--brand-red` is reserved:
the wordmark, the login screen, and at most **one** key call to action per
screen.

For translucent washes use the rgb triples: `rgba(var(--navy-rgb), .09)`,
`--rust-rgb`, `--green-rgb`.

### Class vocabulary

- **Structure** `card`, `section-card`, `panel`, `panel-head`, `page-pad`, `table-wrap`, `card-grid`
- **Type** `h1` `h2` `h2-rust` `h3`, `lead`, `eyebrow` (small rust uppercase label above a heading - the system's signature), `mono`, `tabular`, `muted-cell`, `num`
- **Actions** `btn`, `btn-primary` (navy), `btn-cta` (brand red - one per screen), `btn-lg`, `btn-sm`, `btn-block`, `icon-btn`, `quick-btn`
- **Status** `chip` plus `chip-green` `chip-amber` `chip-blue` `chip-purple` `chip-red` `chip-navy`; `status-pill`; `chip-picker` / `chip-pick` for a selectable row
- **Forms** `input`, `field`, `select`, `form-grid`, `form-row`, `filter-bar`, `toolbar`, `seg` / `seg-btn`, `toggle-chip`, `qty-stepper`, `dropzone`
- **Data** `table.data`, `stat-grid` / `stat-card` / `stat-label` / `stat-value`, `kpi` / `kpi-row` / `kpi-label` / `kpi-value`, `pager` / `pager-page` / `pager-info`, `link-cell`
- **Dialogs** `modal`, `modal-backdrop`, `modal-head`
- **Inline notes** `ok-note`, `warn-note`, `ai-note`, `hint`
- **Scanning** the `scan-screen` family (`scan-head`, `scan-lines`, `scan-line`, `scan-tallies`, `scan-foot`) - the wedge-scanner screen used by receiving, transfers and stock counts

One trap: **`kdps-table` is not a general table class.** It is the PT-mapper's
wide grid and carries `min-width: 1500px`. For an ordinary table use
`table.data` inside a `table-wrap`.

## Domain rules the UI must respect

- Stock is **SKU-grain**: Brand x Style x Colour x Size. Identify goods with `SkuLine`, never style alone.
- Money is **integer paise**, rendered by `Money`, in INR with Lakh/Crore grouping. Never format currency by hand.
- Voucher numbers, SKU codes and GSTINs are monospaced (`mono`).

## Where the truth lives

`styles.css` and the files it imports are authoritative - read them before
styling anything. Each component ships its own `<Name>.d.ts` (the API) and
`<Name>.prompt.md` (how to use it).

## A build in the idiom

```jsx
<div className="section-card card">
  <p className="eyebrow">Deoghar - today</p>
  <h3 className="h3">Bills raised</h3>
  <div className="stat-grid" style={{ marginTop: 12 }}>
    <Stat label="Bills" value="412" />
    <Stat label="Net sales" value={<Money paise={18560000} short />} />
  </div>
  <table className="data" style={{ marginTop: 14 }}>
    <tbody>
      <tr>
        <td><SkuLine brand="MUFTI" style="MFK-4471" color="Indigo" size="40" /></td>
        <td align="right"><Money paise={249900} /></td>
        <td align="right"><StatusChip status="Matched" /></td>
      </tr>
    </tbody>
  </table>
  <button className="btn btn-cta" style={{ marginTop: 14 }}>Close the day</button>
</div>
```
