# Escalation

Read this when a review or QA finding looks like more than a bug.

## The test

Not how serious the finding is - a kernel breach is serious and has one known correct answer, so fixing it is exactly what an agent is for.
The test is: **is the answer already written down?**

- **Written down** - the 12 rules, a locked decision, an ADR, the issue's own acceptance criteria - then **fix it**, however serious it looks. You are applying a rule, not making one.
- **Not written down** - then **stop**. Fixing it would mean inventing policy, and invented policy has reached this codebase before.

## Fix it

- A kernel or rule breach: a ledger written from something other than a document, a posting that avoids `post_entries` or does not balance, a derived figure hand-entered, stock tracked below SKU = style x size x colour, a variation hard-coded that Rule 12 says is data.
- Access control failing open. Known class, known remedy.
- The Spec axis says you solved a different problem, and the issue is clear about which problem it wanted. Redo the work.
- A fix far larger than the issue implied: do it, and say plainly in the PR that the issue was mis-scoped. Stop only if it has genuinely become a slice rather than an issue.

Before fixing anything above, **quote the rule or decision you are applying** - the sentence, and where it lives.
A passage that nearly fits is not a quote; no quote means it is not written down, which means stop.

## Stop and ask

- **Anything about money.** Absolute - see below.
- The design corpus is silent on the question.
- Two fair readings exist and either is defensible.
- A CA ruling is pending, including the five gated money items.
- The blast radius has grown into a slice rather than an issue.
- A finding survived two honest fix attempts - evidence the answer was never as settled as you thought.

## Money always goes back to the human

Wrong valuation, wrong liability, wrong tax, a posting that would later need reversing, money rendered wrong on a screen.

**Fix it if you can, but never open a real PR on it.**
Stop, hand back, and ask - even when the corpus answers the question and you can quote it.
A confident wrong fix here reaches the alpha and corrupts a ledger that then has to be unwound by hand, which costs far more than asking.

## What stopping looks like

Stopping preserves the work so the next session starts from what you learnt:

```bash
git push -u origin HEAD
gh pr create -R bruhanand/KDPS --base main --draft \
  --title "WIP: <what was attempted> (#<n>)" --body-file <file>
gh issue edit <n> -R bruhanand/KDPS --add-label ready-for-human --remove-label ready-for-agent
```

The draft PR body says which gates passed, where it stopped, and what the finding was.
Then comment on the issue and stop - no further gates, no real PR.

## How to write the question

A human reads this, not another agent.
Write it in **simple, everyday English**, the way you would say it out loud to a shop owner in Patna.

- Talk about shirts, brands, stores, bills and customers - never models, endpoints, serialisers or migrations.
- Rupees the Indian way: `₹2,85,000`. Dates in words: `14 August`.
- One question at a time; if there are two, ask the more important one and say the other is waiting.
- Give the choices and say which you would pick, and why, in one line.
- The question must be answerable without reading code: file paths, line numbers and findings tables live in the draft PR.

Name the real-world situation, then the choice:

> While building the return-to-vendor screen I hit a case the design does not settle.
>
> A Louis Philippe shirt comes to us on SOR at ₹1,200. We sell it in an offer at ₹900. When we send the brand their share, do we owe them on ₹1,200 or on ₹900?
>
> The two give different vendor balances, so I have stopped rather than guess. I would go with ₹1,200, because the brand's rate is what we agreed at booking - but this is your call.

Not this:

> `RtvLine.unit_value` is populated from `P_RATE` but the SOR liability posting in `post_entries` uses the discounted `sale_price`, so the vendor payable diverges from the stock valuation. Which should the serialiser use?

A stopped issue with an honest question is a good outcome.
A merged PR built on a finding you talked yourself out of is what this exists to prevent.
