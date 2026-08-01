# TASK

Act on the findings for branch {{BRANCH}}, issue {{TASK_ID}}. Mode: {{MODE}},
round {{ROUND}}.

- Mode `review`: the findings are `{{ART_DIR}}/findings-standards.md`,
  `findings-spec.md` and `findings-correctness.md`. A file saying "No
  findings" is done — skip it.
- Mode `qa`: the finding is `{{ART_DIR}}/qa-report.md` — the failed flows
  only. After you fix, a fresh QA agent re-drives them; you do not.

Read them all first. Then decide, per finding, using the escalation test.

# THE TEST

**Read `.agents/skills/implement/ESCALATION.md` before touching anything** —
it is the whole rulebook and it binds every decision here. The short form:

- The test is never how serious the finding is — it is **whether the answer is
  already written down** (the 12 rules, a locked decision, an ADR, the issue's
  own acceptance criteria). Written down → fix it, and quote the sentence and
  its file path in the commit body. A passage that nearly fits is not a quote;
  no quote means stop.
- **Anything about money: hand back, always** — wrong valuation, liability,
  tax, a posting that would need reversing, money rendered wrong. Even when
  the corpus answers it and the fix is obvious. A confident wrong fix reaches
  the alpha and corrupts a ledger somebody unwinds by hand.
- The corpus is silent, two fair readings exist, a CA ruling is pending, or
  the blast radius has grown into a feature → hand back.
- **Round 2 or later:** a finding that survived your previous fix is telling
  you something about the design. Hand it back rather than force a second fix.

What to fix, per axis (the /implement rules):

- **Spec:** fix every finding, or record a deliberate deviation and its reason
  in `{{ART_DIR}}/deviations.md` — it survives with the branch's artifacts
  for the human who reviews the merged work.
- **Correctness & Safety:** fix every critical.
- **Standards:** fix every hard violation; judgement-call smells you
  consciously leave get named in `{{ART_DIR}}/deviations.md`.

# FIXING

Check only what you touched — the test file, `uv run mypy core config`,
`yarn typecheck`. **Never run `npm run ci`**: a dedicated ci-check phase
runs `npm run ci:fast` after QA, and the host runs it again on merged main.

Commit in the repo's `scope: subject` style, quoting the rule you applied in
the body.

# HANDING BACK

Follow "What stopping looks like" in ESCALATION.md. Comment the question on
the issue in plain, everyday English — shirts, brands, stores and bills, never
models or endpoints; rupees the Indian way (`₹2,85,000`); dates in words; one
question, the choices given, and which you would pick. Never ask them to read
code. Then:

```bash
gh issue edit {{TASK_ID}} -R bruhanand/KDPS --add-label ready-for-human --remove-label ready-for-agent
```

The branch is kept unmerged for the human — your comment is what they see
first.

# VERDICT

Output exactly one:

<verdict>CLEAN</verdict>       — nothing actionable was left to do
<verdict>FIXED</verdict>       — findings fixed, and/or consciously left and recorded
<verdict>HANDED_BACK</verdict> — at least one finding went to a human
