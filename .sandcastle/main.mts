// Sequential Reviewer — implement-then-review loop
//
// This template drives a two-phase workflow per issue:
//   Phase 1 (Implement): A sonnet agent picks an open issue, works on it
//                        on a dedicated branch, commits the changes, and signals
//                        completion.
//   Phase 2 (Review):    A second sonnet agent reviews the branch diff and either
//                        approves it or makes corrections directly on the branch.
//
// Both phases share a single sandbox created via createSandbox(), so the
// implementer and reviewer work on the same explicit branch.
//
// The outer loop repeats up to MAX_ITERATIONS times, processing one issue per
// iteration and stopping early once the backlog is exhausted (an implement
// phase that produces no commits). This is a middle-complexity option between
// the simple-loop (no review gate) and the parallel-planner (concurrent
// execution with a planning phase).
//
// Usage:
//   npx tsx .sandcastle/main.mts
// Or add to package.json:
//   "scripts": { "sandcastle": "npx tsx .sandcastle/main.mts" }

import { execSync } from "node:child_process";

import * as sandcastle from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

// One slice per run: build a single issue, then STOP on its branch for your
// review. This is the gating node — Sandcastle never reaches `main`. Raise only
// if you deliberately want to drain several issues unattended (never on money).
const MAX_ITERATIONS = 1;

// A model per stage, hoisted so a slice tunes in one edit. Use the 4-8 ids.
// Default implementer = sonnet (free lane: K9 seed/components, screens, reports).
// Bump MODEL_IMPL to "claude-opus-4-8" per-run on money slices (ledgers/GST/RBAC).
// Reviewer stays on opus — cheap insurance before YOUR Chat B review.
// K1 is a SUPERVISED money slice — implementer bumped to opus per the manual.
const MODEL_IMPL = "claude-opus-4-8";
const MODEL_REVIEW = "claude-opus-4-8";

// Hooks run inside the sandbox before the agent starts each iteration.
// `npm run setup` = uv sync (app/backend) + npm install (app/frontend), run from
// the repo root. A bare `uv sync` here fails — there is no root pyproject.toml.
// DB is external: the sandbox still needs DATABASE_URL pointing at a reachable
// Postgres service (see README / docker-compose) — wired in the pre-K9 pass.
const hooks = {
  sandbox: { onSandboxReady: [{ command: "npm run setup" }] },
};

// Copy node_modules from the host into the worktree before each sandbox
// starts. Avoids a full npm install from scratch; the hook above handles
// platform-specific binaries and any packages added since the last copy.
const copyToWorktree = ["node_modules"];

// The branch this run was launched from — i.e. THIS Conductor worktree's branch.
// Sandcastle builds the slice on an isolated temp branch (so the worktree stays
// clean while the agent works), then we fast-forward it back into this branch at
// the end. That puts the finished diff right here in the worktree for human
// review. We NEVER touch main — merging this branch to main is the human gate.
const launchBranch = execSync("git rev-parse --abbrev-ref HEAD").toString().trim();

// ---------------------------------------------------------------------------
// Main loop
// ---------------------------------------------------------------------------

for (let iteration = 1; iteration <= MAX_ITERATIONS; iteration++) {
  console.log(`\n=== Iteration ${iteration}/${MAX_ITERATIONS} ===\n`);

  // Generate a unique branch name for this iteration.
  const branch = `sandcastle/sequential-reviewer/${Date.now()}`;

  // Create a single sandbox that both the implementer and reviewer share.
  // This gives both agents a real, named branch that persists across phases.
  const sandbox = await sandcastle.createSandbox({
    branch,
    sandbox: docker(),
    hooks,
    copyToWorktree,
  });

  try {
    // -----------------------------------------------------------------------
    // Phase 1: Implement
    //
    // A sonnet agent picks the next open issue, writes the
    // implementation (using RGR: Red → Green → Repeat → Refactor), and
    // commits the result.
    //
    // The agent signals completion via <promise>COMPLETE</promise> when done.
    // -----------------------------------------------------------------------
    // One iteration so each outer pass implements a single issue on its own
    // branch, then hands it to the reviewer. A higher value lets the agent
    // drain the whole backlog onto this one branch in a single pass, which
    // defeats the per-issue review.
    const implement = await sandbox.run({
      name: "implementer",
      maxIterations: 1,
      agent: sandcastle.claudeCode(MODEL_IMPL),
      promptFile: "./.sandcastle/implement-prompt.md",
    });

    if (!implement.commits.length) {
      // No commits means the backlog is empty or every remaining issue is
      // blocked — there is nothing left to implement or review, so stop.
      console.log("Implementation agent made no commits. Stopping.");
      break;
    }

    console.log(`\nImplementation complete on branch: ${branch}`);
    console.log(`Commits: ${implement.commits.length}`);

    // -----------------------------------------------------------------------
    // Phase 2: Review
    //
    // A second sonnet agent reviews the diff of the branch produced by
    // Phase 1. It uses the {{BRANCH}} prompt argument to inspect the right
    // branch, and either approves or makes corrections directly on the branch.
    // -----------------------------------------------------------------------
    await sandbox.run({
      name: "reviewer",
      maxIterations: 1,
      agent: sandcastle.claudeCode(MODEL_REVIEW),
      promptFile: "./.sandcastle/review-prompt.md",
      // BRANCH is the slice's temp branch. TARGET_BRANCH is a Sandcastle built-in
      // (the branch the sandbox forked from = launchBranch) and MUST NOT be passed
      // here — overriding it throws PromptError and the reviewer never runs. The
      // review prompt's {{TARGET_BRANCH}}...{{BRANCH}} diff resolves it on its own.
      promptArgs: {
        BRANCH: branch,
      },
    });

    console.log("\nReview complete.");

    // Land the finished, reviewed slice back into this worktree's branch via a
    // fast-forward, so the diff is visible right here in Conductor for the human
    // read. The temp branch is then redundant (its commits now live on
    // launchBranch), so drop it. Still nothing reaches main — that's the human
    // merge gate.
    execSync(`git merge --ff-only ${branch}`, { stdio: "inherit" });
    execSync(`git branch -D ${branch}`, { stdio: "inherit" });
    console.log(
      `\nLanded ${branch} into ${launchBranch}. Review the diff in this workspace, then merge to main.`,
    );
  } finally {
    await sandbox.close();
  }
}

console.log("\nAll done.");
