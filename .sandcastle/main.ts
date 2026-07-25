// Parallel Planner with Review — four-phase orchestration loop
//
// This template drives a multi-phase workflow:
//   Phase 1 (Plan):             An opus agent analyzes open issues, builds a
//                               dependency graph, and outputs a <plan> JSON
//                               listing unblocked issues with branch names.
//   Phase 2 (Execute + Review): For each issue, a sandbox is created via
//                               createSandbox(). The implementer runs first.
//                               If it produces commits, a reviewer runs in the
//                               same sandbox on the same branch. How many issue
//                               pipelines run at once is set by
//                               MAX_CONCURRENT_ISSUES in the config block.
//   Phase 3 (Publish):          A single agent verifies the gate and opens one
//                               pull request per completed branch. It never
//                               merges and never closes an issue — a human does
//                               that, the same way /deliver stops at the PR.
//
// The outer loop repeats up to MAX_ITERATIONS times. Note that because nothing
// is merged, a second cycle plans against a `main` that does not yet carry the
// first cycle's work: keep MAX_ITERATIONS at 1 and run again after merging, or
// accept that later cycles cannot build on earlier ones.
//
// Usage:
//   npx tsx .sandcastle/main.ts
// Or add to package.json:
//   "scripts": { "sandcastle": "npx tsx .sandcastle/main.ts" }

import { mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import * as sandcastle from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

// --- Models -----------------------------------------------------------------
// One entry per phase, so any phase can be flipped without touching the loop.
// Anything the Claude Code CLI accepts as --model works: a full id
// ("claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5-20251001") or an
// alias ("opus", "sonnet", "haiku").
//
// Pick one per phase — uncomment exactly one line in each block.
const MODELS = {
  // planner — dependency analysis; benefits from deeper reasoning.
  planner: "claude-sonnet-5",
  // planner: "claude-opus-4-8",
  // planner: "claude-haiku-4-5-20251001",

  // implementer — writes code, runs tests, iterates. The workhorse.
  implementer: "claude-sonnet-5",
  // implementer: "claude-opus-4-8",
  // implementer: "claude-haiku-4-5-20251001",

  // reviewer — reviews the implementer's diff on the same branch.
  reviewer: "claude-sonnet-5",
  // reviewer: "claude-opus-4-8",
  // reviewer: "claude-haiku-4-5-20251001",

  // publisher — verifies the gate and opens a PR per branch. Never merges.
  publisher: "claude-sonnet-5",
  // publisher: "claude-opus-4-8",
  // publisher: "claude-haiku-4-5-20251001",
} as const;

// --- Iteration counts -------------------------------------------------------
// `loop` is the number of plan→execute→publish cycles before stopping; the rest
// cap how many turns each agent gets inside a single cycle. The implementer is
// the only one that needs a lot: it writes code, runs tests and iterates.
const ITERATIONS = {
  loop: 1,
  planner: 1,
  implementer: 100,
  reviewer: 1,
  publisher: 1,
} as const;

// --- How the work is run ----------------------------------------------------
// Two knobs. Uncomment exactly one line in each block.
//
// MAX_CONCURRENT_ISSUES — how many issue pipelines run at the same time in the
// execute phase. A failing pipeline never cancels the others, whatever the
// setting.
const MAX_CONCURRENT_ISSUES: number = 1; // sequential — one issue start to finish, then the next
// const MAX_CONCURRENT_ISSUES: number = 3;        // limited parallel — 3 in flight, a 4th starts as one finishes
// const MAX_CONCURRENT_ISSUES: number = Infinity; // full parallel — every issue in the plan at once (stock behaviour)

// MAX_ISSUES_PER_CYCLE — how many issues a single cycle takes from the plan,
// regardless of how many the planner found unblocked. The leftovers are picked
// up by the next cycle.
const MAX_ISSUES_PER_CYCLE: number = 1; // one full plan→build→review→publish cycle per issue; always starts from fresh main
// const MAX_ISSUES_PER_CYCLE: number = 3;        // three issues, then one publish pass
// const MAX_ISSUES_PER_CYCLE: number = Infinity; // whole plan in one cycle, one publish pass at the end (stock behaviour)

// Maximum number of plan→execute→publish cycles before stopping.
// Raise this if your backlog is large; lower it for a quick smoke-test run.
const MAX_ITERATIONS = ITERATIONS.loop;

// ---------------------------------------------------------------------------
// Runs `fn` over `items` with at most `limit` in flight, settling every one.
// Results come back in `items` order, matching Promise.allSettled's shape.
// ---------------------------------------------------------------------------
async function allSettledWithLimit<T, R>(
  items: T[],
  limit: number,
  fn: (item: T) => Promise<R>,
): Promise<PromiseSettledResult<R>[]> {
  const results = new Array<PromiseSettledResult<R>>(items.length);
  let next = 0;

  const workerCount = Math.max(1, Math.min(limit, items.length));
  await Promise.all(
    Array.from({ length: workerCount }, async () => {
      while (true) {
        const index = next++;
        if (index >= items.length) return;
        try {
          results[index] = { status: "fulfilled", value: await fn(items[index]!) };
        } catch (reason) {
          results[index] = { status: "rejected", reason };
        }
      }
    }),
  );

  return results;
}

// ---------------------------------------------------------------------------
// Sandbox environment
// ---------------------------------------------------------------------------

// config/settings.py reads these with os.environ[...] — a missing one is a
// KeyError, not a default. On a dev machine they come from app/backend/.env,
// but that file is gitignored, so it does not exist in a Sandcastle worktree
// and the values have to be injected here instead.
//
// DATABASE_URL points at the throwaway cluster the Dockerfile created inside
// the image. Every sandbox gets its own, so concurrent issues never share a DB.
const SANDBOX_ENV: Record<string, string> = {
  DATABASE_URL: "postgres://kdps@localhost:5432/kdps_dev",
  DJANGO_SECRET_KEY: "sandcastle-sandbox-not-for-production",
  DJANGO_DEBUG: "1",
  DJANGO_ALLOWED_HOSTS: "*",
  SEED_DEMO: "1",
  EMERGENT_LLM_KEY: "sandcastle-placeholder",
  GEMINI_MODEL: "gemini-2.5-flash",
  // The live-API regression suites talk to the server over plain http, and a
  // Secure cookie is never sent back over http — every cookie-authed request
  // would 401. Cloud CI sets this for the same reason.
  JWT_COOKIE_SECURE: "0",
  REACT_APP_BACKEND_URL: "http://localhost:8001",
};

// Package caches, shared across every sandbox and every run. Without these each
// sandbox re-downloads the backend wheels and the frontend package tree from
// scratch — several minutes per issue. Docker fails sandbox creation if a mount
// source is missing, so create them before anything starts.
const CACHE_ROOT = join(homedir(), ".cache", "sandcastle-kdps");
const CACHES = [
  { hostPath: join(CACHE_ROOT, "uv"), sandboxPath: "/home/agent/.cache/uv" },
  { hostPath: join(CACHE_ROOT, "yarn"), sandboxPath: "/home/agent/.cache/yarn" },
];
for (const cache of CACHES) mkdirSync(cache.hostPath, { recursive: true });

const sandboxProvider = () => docker({ env: SANDBOX_ENV, mounts: CACHES });

// Hooks run inside the sandbox once it is up, before the agent starts.
//
// Two sets, because the phases need different things. The planner only reads
// GitHub issues, so making it wait on a Postgres boot and two dependency trees
// would waste minutes per cycle. Everything that compiles, tests or merges gets
// the full environment.
const planHooks = {};
const buildHooks = {
  sandbox: {
    onSandboxReady: [
      { command: "bash .sandcastle/sandbox-setup.sh", timeoutMs: 20 * 60_000 },
    ],
  },
};

// Nothing is copied from the host into the worktree. The obvious candidates are
// the two node_modules trees and app/backend/.venv, but the host is macOS/arm64
// and the sandbox is Linux: copying them in imports darwin-only binaries
// (esbuild, rollup) and a venv full of absolute host paths. The caches above
// give the same speedup without the platform mismatch.
const copyToWorktree: string[] = [];

// ---------------------------------------------------------------------------
// Main loop
// ---------------------------------------------------------------------------

for (let iteration = 1; iteration <= MAX_ITERATIONS; iteration++) {
  console.log(`\n=== Iteration ${iteration}/${MAX_ITERATIONS} ===\n`);

  // -------------------------------------------------------------------------
  // Phase 1: Plan
  //
  // The planning agent (opus, for deeper reasoning) reads the open issue list,
  // builds a dependency graph, and selects the issues that can be worked in
  // parallel right now (i.e., no blocking dependencies on other open issues).
  //
  // It outputs a <plan> JSON block — we parse that to drive Phase 2.
  // -------------------------------------------------------------------------
  const plan = await sandcastle.run({
    hooks: planHooks,
    sandbox: sandboxProvider(),
    name: "planner",
    // One iteration is enough: the planner just needs to read and reason,
    // not write code.
    maxIterations: ITERATIONS.planner,
    // Opus for planning: dependency analysis benefits from deeper reasoning.
    agent: sandcastle.claudeCode(MODELS.planner),
    promptFile: "./.sandcastle/plan-prompt.md",
  });

  // Extract the <plan>…</plan> block from the agent's stdout.
  const planMatch = plan.stdout.match(/<plan>([\s\S]*?)<\/plan>/);
  if (!planMatch) {
    throw new Error(
      "Planning agent did not produce a <plan> tag.\n\n" + plan.stdout,
    );
  }

  // The plan JSON contains an array of issues, each with id, title, branch.
  const { issues: plannedIssues } = JSON.parse(planMatch[1]!) as {
    issues: { id: string; title: string; branch: string }[];
  };

  // Honour the per-cycle cap; anything left over is picked up next cycle.
  const issues =
    MAX_ISSUES_PER_CYCLE === Infinity
      ? plannedIssues
      : plannedIssues.slice(0, MAX_ISSUES_PER_CYCLE);

  if (issues.length < plannedIssues.length) {
    console.log(
      `Plan had ${plannedIssues.length} unblocked issue(s); taking ${issues.length} this cycle (MAX_ISSUES_PER_CYCLE).`,
    );
  }

  if (issues.length === 0) {
    // No unblocked work — either everything is done or everything is blocked.
    console.log("No unblocked issues to work on. Exiting.");
    break;
  }

  console.log(
    `Planning complete. ${issues.length} issue(s) to work, ${
      MAX_CONCURRENT_ISSUES === 1
        ? "one at a time"
        : `up to ${MAX_CONCURRENT_ISSUES} at a time`
    }:`,
  );
  for (const issue of issues) {
    console.log(`  ${issue.id}: ${issue.title} → ${issue.branch}`);
  }

  // -------------------------------------------------------------------------
  // Phase 2: Execute + Review
  //
  // For each issue, create a sandbox via createSandbox() so the implementer
  // and reviewer share the same sandbox instance per branch. The implementer
  // runs first; if it produces commits, the reviewer runs in the same sandbox.
  //
  // How many pipelines run at once is MAX_CONCURRENT_ISSUES (1 by default, i.e.
  // one issue at a time). Every pipeline settles — one failure doesn't cancel
  // the others.
  // -------------------------------------------------------------------------

  const settled = await allSettledWithLimit(
    issues,
    MAX_CONCURRENT_ISSUES,
    async (issue) => {
      const sandbox = await sandcastle.createSandbox({
        branch: issue.branch,
        sandbox: sandboxProvider(),
        hooks: buildHooks,
        copyToWorktree,
      });

      try {
        // Run the implementer
        const implement = await sandbox.run({
          name: "implementer",
          maxIterations: ITERATIONS.implementer,
          agent: sandcastle.claudeCode(MODELS.implementer),
          promptFile: "./.sandcastle/implement-prompt.md",
          promptArgs: {
            TASK_ID: issue.id,
            ISSUE_TITLE: issue.title,
            BRANCH: issue.branch,
          },
        });

        // Only review if the implementer produced commits
        if (implement.commits.length > 0) {
          const review = await sandbox.run({
            name: "reviewer",
            maxIterations: ITERATIONS.reviewer,
            agent: sandcastle.claudeCode(MODELS.reviewer),
            promptFile: "./.sandcastle/review-prompt.md",
            promptArgs: {
              BRANCH: issue.branch,
            },
          });

          // Merge commits from both runs so the publish phase sees all of them.
          // Each sandbox.run() only returns commits from its own run.
          return {
            ...review,
            commits: [...implement.commits, ...review.commits],
          };
        }

        return implement;
      } finally {
        await sandbox.close();
      }
    },
  );

  // Log any agents that threw (network error, sandbox crash, etc.).
  for (const [i, outcome] of settled.entries()) {
    if (outcome.status === "rejected") {
      console.error(
        `  ✗ ${issues[i]!.id} (${issues[i]!.branch}) failed: ${outcome.reason}`,
      );
    }
  }

  // Only pass branches that actually produced commits to the publish phase.
  // An agent that ran successfully but made no commits has nothing to publish.
  const completedIssues = settled
    .map((outcome, i) => ({ outcome, issue: issues[i]! }))
    .filter(
      (entry) =>
        entry.outcome.status === "fulfilled" &&
        entry.outcome.value.commits.length > 0,
    )
    .map((entry) => entry.issue);

  const completedBranches = completedIssues.map((i) => i.branch);

  console.log(
    `\nExecution complete. ${completedBranches.length} branch(es) with commits:`,
  );
  for (const branch of completedBranches) {
    console.log(`  ${branch}`);
  }

  if (completedBranches.length === 0) {
    // All agents ran but none made commits — nothing to publish this cycle.
    console.log("No commits produced. Nothing to publish.");
    continue;
  }

  // -------------------------------------------------------------------------
  // Phase 3: Publish
  //
  // One agent verifies the gate on each completed branch and opens a pull
  // request for it. Nothing is merged and no issue is closed. A branch whose
  // issue the reviewer labelled `ready-for-human` gets a draft PR instead, so a
  // flagged design or money finding cannot ride through to main unnoticed.
  //
  // The {{BRANCHES}} and {{ISSUES}} prompt arguments are lists that the agent
  // uses to know which branches to publish and which issues they close.
  // -------------------------------------------------------------------------
  await sandcastle.run({
    hooks: buildHooks,
    sandbox: sandboxProvider(),
    name: "publisher",
    maxIterations: ITERATIONS.publisher,
    agent: sandcastle.claudeCode(MODELS.publisher),
    promptFile: "./.sandcastle/publish-prompt.md",
    promptArgs: {
      // A markdown list of branch names, one per line.
      BRANCHES: completedBranches.map((b) => `- ${b}`).join("\n"),
      // A markdown list of issue IDs and titles, one per line.
      ISSUES: completedIssues
        .map((i) => `- ${i.id}: ${i.title}`)
        .join("\n"),
    },
  });

  console.log("\nPull requests opened.");
}

console.log("\nAll done.");
