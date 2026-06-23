# Teaching Notes — Anand

## How he wants to be taught
- **Plain language, simple, non-technical.** Short. No overexplaining. (Standing preference across the whole project.)
- **HTML deliverables only** — never markdown — for anything he keeps and revisits.
- **He is THE system architect.** Teach him to *evaluate and decide*, not just absorb. Frame every lesson around a decision he will actually make on KDPS.

## What works for him
- **Ground every term in his own KDPS workflow.** Use real examples he authored: SOR brands, EOSS, PT files, GRN, Patna head office, MBO/EBO, size×color. Abstract definitions don't land; his-workflow examples do.
- **Color-code consistently:** 🟧 amber = Business term, 🟦 blue = Technical term. Keep this in every lesson and reference.

## Starting point (session 1)
- Very strong **fashion-retail domain knowledge** — he wrote the current-workflow doc. The gap is *software-architecture vocabulary* and a few *formal business-process terms*, not the retail reality.
- So: vocabulary-first. Lead with a cheat-sheet, then the keystone concepts.

## Build phase (from session 2, 19 Jun 2026)
- Mission evolved → **shipping KDPS as a vibe coder, without fear.** See [[learning-records/0002...]].
- He directs AI; he doesn't hand-write code. So every build lesson = a way to **place, fix, or judge** what the AI produces — never "type this code."
- Baseline he stated: very basic CLI, can read some code, use a terminal. Don't assume more.
- Lessons L2+ extend the L1 colour/shape feel. L2 introduced the four-box model (🖥️ Screen / 🧠 Brain / 🗄️ Memory / 🔌 Outside World) — reuse those four boxes + colours as the spatial map in later build lessons.
- He responds to being asked "which box?" / "is the AI right here?" — keep the architect-who-decides framing into the build.
- Discuss/ask in plain chat, never multiple-choice dialogs (standing project preference).

## Style for lessons (stated 20 Jun 2026, applies to ALL future lessons)
- **Very simple English.** Anand is from India — short words, plain phrasing, no fancy vocabulary or jargon without a plain-words explanation.
- **No walls of text.** Almost never a multi-line paragraph. Prefer **lists and tables**. Keep lines to 1–2 short sentences.
- **Bifurcate everything** — split into clear pieces, side-by-side comparisons, "this vs that" tables.
- **Follow-and-connect explanations:** tell it as a sequence of what happens, step by step, each step linking to the next; and connect new ideas back to what he already knows (ledger, the four boxes, the four models, SQL verbs).
- **Good concrete examples**, ideally an everyday relatable one (e.g. restaurant) plus the KDPS version.
- Deep-dive tracks now: database (done L4–L5) → **backend/Brain track L6–L9** (L6 request→response & APIs, L7 business logic & validation, L8 auth & roles, L9 errors & background jobs). See [[0006-database-deep-dive-track]].
