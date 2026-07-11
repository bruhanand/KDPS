# Teaching Notes — Anand (fresh track, started 8 Jul 2026)

## Workspace facts
- This directory (`docs/learning/`) is the teaching workspace. The old one (`.agents/skills/teach/`) is **retired** — carry its style preferences, never its lessons.
- The curriculum spine is `stack-learning-roadmap.html` (P0–P10). Each phase gets a course page (`pN-course.html`) + numbered lessons in `lessons/`.
- Lesson numbering is global and sequential across phases: `0001-…`, `0002-…`.

## How he wants to be taught (carried over + confirmed 8 Jul 2026)
- **Very simple English** — short words, plain phrasing; explain any jargon in plain words first.
- **No walls of text.** Lists and tables. 1–2 short sentences per line.
- **Bifurcate everything** — this-vs-that tables, side-by-side comparisons.
- **Follow-and-connect**: teach as a step-by-step sequence; connect each new idea to something he already has.
- **One everyday analogy + the KDPS version** for each big concept (restaurant analogy worked well before).
- Colour code: 🟧 amber = business term, 🟦 blue = technical term.
- **HTML lessons, dark house style** (same palette as the roadmap), quizzes with instant in-page feedback.
- Discuss in plain chat; no multiple-choice dialog boxes.
- He asks for "top tier" teaching: goals stated first, lessons chained (each opens by using the previous one), quiz in every lesson, exit checklist.

## Baseline (see learning-records/0001)
- Strong fashion-retail domain knowledge; he authored the KDPS design.
- Front-end background (built UIs before); knows basic Python; **cannot yet read Django/TypeScript syntax fluently**.
- Old track gave him concept-level: four-box model, git-as-undo, SQL reading, request→response, auth roles. Don't re-teach concepts — teach **reading the real code**.

## Difference from the old track (important)
- Old goal: ship without fear, concepts only, "never type code".
- New goal: **read code in and out, judge architecture, review AI**. Lessons must be code-level: real files open, real lines quoted, hands-on terminal tasks.
