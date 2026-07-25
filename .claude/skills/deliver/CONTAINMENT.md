# Containment

An issue is **contained** when an agent can finish it without asking a question that changes the answer.

This is a refusal rubric.
Its job is to catch the issue that looks small and is not, *before* a branch exists.

## The seven checks

Every one must pass.
Answer each in one line in your verdict; do not skip any.

### 1. One outcome

The issue names a single user-visible outcome.
If the title contains "and", or the body lists two features, it is two issues.

Refactors that enable a feature count as one outcome only when the refactor is named as prefactoring in the same issue.

### 2. Testable acceptance

There is at least one statement that is either true or false once the work is done.
"Improve the transfer screen" is not testable.
"The transfer screen shows the destination store's name, not its code" is.

If acceptance criteria are absent, you may write them yourself **only** when they follow unambiguously from the issue body plus the design corpus.
Post them as a comment and proceed.
If writing them requires a choice, that is NEEDS-INFO.

### 3. Named actor, where one is needed

Anything that creates, approves, reverses or values a document needs a named actor: who may do this.
The design corpus is silent on actors in several places, and inventing one is a design decision, not an implementation detail.

If the issue touches permissions and names no actor, that is NEEDS-INFO.

### 4. Design-conformant

The issue does not contradict `CONTEXT.md`: the 12 rules, the kernel contracts, or a locked or CA-gated decision.

Specifically refuse when the issue would:

- write a ledger from anything but a document
- post money outside `post_entries`, or unbalanced
- hand-enter a figure that the design derives (cost, margin, profitability)
- treat stock at style level rather than SKU = style x size x colour
- hard-code a variation that Rule 12 says is data
- touch one of the five CA-gated money items before the ruling

A contradiction is TOO-BIG or NEEDS-INFO even when the code change is three lines.
Rules change consciously, on the architecture page, first.

### 5. Bounded blast radius

You can name, before starting, the files and layers the change touches.
If you cannot, the issue needs exploring before it needs implementing.

Rough ceiling: one Django app plus its screens, or one screen plus the endpoints it calls.
A change that spans the kernel *and* three business apps is a slice, not an issue.

### 6. Blockers closed

If the issue declares blockers, every one is closed and merged to `main`.
An open blocker means it is not ready, whatever the label says.

### 7. No collision

No open PR is changing the same files for the same reason, and no other session is assigned to it.

## Verdicts

- **CONTAINED** - all seven pass.
- **NEEDS-INFO** - a check fails on a question a human can answer in a sentence.
  Ask the questions. Short, scannable, no file paths or line numbers - Anand reads plain language and makes the decision.
  Never widen the fix into a redesign while you are there.
- **TOO-BIG** - the issue is several outcomes, or its blast radius is a slice.
  Propose the split as a list of tracer-bullet slices, each independently shippable, and hand it back.

## Before asking

Read the design corpus first.
Silence in the corpus is itself an answer worth reporting: say "the design does not cover this" rather than inventing a rule and shipping it.
Most NEEDS-INFO verdicts that turn out to be wrong are ones where the answer was already written down.
