# Commercial models: now FOUR, not two (SOR vs Outright is stale)

Lesson 1 originally taught the ownership spine as **SOR vs Outright** (with "Hybrid" as a passing third). KDPS's D1 Vendor Management design changed this (changelog: "13 Jun 2026 — commercial models 3 → 4"). The current, authoritative set is **four**:

- **Buy & Sell (Outright)** — KDPS owns, no returns, earns margin.
- **Correction (25-18-10)** — KDPS owns, *but* a capped return allowance (≈10%, stretchable), manual returns within window + budget; earns margin.
- **SOR** — Brand owns, all unsold returns (no cap), fresh booking to reorder; earns commission.
- **Consignment** — Brand owns, all unsold returns, brand keeps topping up (no fresh booking); earns commission.

The teaching frame survives: it's **still one question — who owns the stock? — but each answer now has two flavours.** KDPS-owned pay the vendor at inward; brand-owned pay as each piece sells. "Hybrid" is gone.

**Implication:** On 19 Jun 2026, Lesson 1 (`0001-the-two-spines.html`) and the reference (`kdps-term-field-guide.html`) were both updated to the four models. Never teach "SOR vs Outright" as the binary again. Source of truth: `my-understanding/system-design/01-vendor-management/Vendor-Management-Module.html` §3 + §8. Supersedes the model wording captured around [[0001-baseline-strong-domain-weak-software-vocab]].
