// Pipeline orchestrator — the /implement dev process, run unattended.
//
// The shape mirrors the interactive skills (.agents/skills/implement,
// .agents/skills/code-review): many small fresh-context agents handing each
// other files, instead of one 100-turn context doing everything. Each box
// reads a small artifact, does one job, writes a small artifact.
//
//   Phase 1 (Plan):      One agent reads the ready-for-agent issues and groups
//                        them into WAVES: wave 1 builds in parallel from
//                        today's main; later waves are blocked by wave 1 and
//                        are only reported (build them in a later run, after
//                        wave 1's PRs merge — nothing merges here).
//   Phase 2 (Pipeline):  Per wave-1 issue, one sandbox, one branch, and a
//                        chain of fresh contexts:
//                          slicer  — gates the issue (/implement's spec-and-
//                                    currency checks), reads the design
//                                    corpus, writes slice-plan.md. The ONLY
//                                    agent that reads the corpus.
//                          builder — reads slice-plan.md, TDD, touched tests
//                                    only. Never runs the full gate.
//                          review  — three axes in fresh contexts (Standards /
//                                    Spec / Correctness & Money), each writing
//                                    a findings file, like /code-review.
//                          fixer   — reads the findings files, applies
//                                    ESCALATION.md: quote-the-rule or hand
//                                    back; money always hands back. Two
//                                    review→fix rounds, then escalate.
//                          QA      — boots the stack in the sandbox and drives
//                                    the acceptance criteria in headless
//                                    Chromium (Playwright MCP). Fail → fix →
//                                    re-drive failed flows, twice at most.
//   Phase 3 (Publish):   One agent pushes each branch and opens one PR
//                        (draft if handed back). THE PUSH IS THE CI: cloud CI
//                        runs the 16-minute gate on GitHub. `npm run ci` is
//                        never run in a sandbox — that is deliberate.
//
// Agents talk through /artifacts (a host mount, ~/.cache/sandcastle-kdps/
// artifacts), never through each other's transcripts. Control flow reads one
// tag from stdout per run: <gate>, <findings>, <verdict>, <qa>.
//
// Usage:  npx tsx .sandcastle/main.ts   (or: npm run sandcastle)

import { mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import * as sandcastle from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

// --- Models -----------------------------------------------------------------
// One entry per role. Anything the Claude Code CLI accepts as --model works:
// a full id ("claude-opus-4-8", "claude-sonnet-5") or an alias ("opus",
// "sonnet", "haiku"). QA is Sonnet by policy (/implement sends a Sonnet).
const MODELS = {
  planner: "claude-sonnet-5", // reads issues, emits waves
  slicer: "claude-opus-5", //    gates the issue + reads the corpus → slice plan
  builder: "claude-sonnet-5", // writes code from the slice plan. The workhorse.
  fixer: "claude-sonnet-5", //   applies ESCALATION.md to the findings
  qa: "claude-sonnet-5", //      drives the browser, <300-word report
  publisher: "claude-sonnet-5", // pushes + opens PRs. Never merges.
} as const;

// One model per review axis, not one for "the reviewer". Standards and Spec are
// checklist work against a written rule; Correctness & Money is the axis that
// has to reason about ledgers and postings, so it gets the deeper model.
const REVIEW_MODELS = {
  standards: "claude-sonnet-5",
  spec: "claude-sonnet-5",
  correctness: "claude-opus-5",
} as const;

// --- Iteration caps ---------------------------------------------------------
// `loop` is plan→pipeline→publish cycles; the rest cap how many turns each
// agent gets. The builder is the only one that needs a lot.
const ITERATIONS = {
  loop: 1,
  planner: 1,
  // The slicer gates the issue AND reads the corpus. On the first real run it
  // finished on its second and last iteration, and a missing <gate> defaults to
  // GO — so a harder issue would be waved through on a cap, not on a judgement.
  slicer: 4,
  builder: 100,
  reviewer: 1,
  fixer: 3,
  qa: 2,
  publisher: 2,
} as const;

// How many review→fix rounds before the fixer must hand back (mirrors
// /implement: "Two rounds, then ESCALATION.md").
const REVIEW_ROUNDS = 2;
// How many QA re-drives after the first full drive (mirrors /implement:
// "Two re-drives at most, then ESCALATION.md").
const QA_REDRIVES = 2;

// --- How the work is run ----------------------------------------------------
// MAX_CONCURRENT_ISSUES — how many wave-1 pipelines run at the same time. Each
// has its own sandbox, its own Postgres and its own branch, so they never
// share state. A failing pipeline never cancels the others.
const MAX_CONCURRENT_ISSUES: number = 1; // sequential
// const MAX_CONCURRENT_ISSUES: number = 3;        // limited parallel
// const MAX_CONCURRENT_ISSUES: number = Infinity; // whole wave at once

// MAX_ISSUES_PER_CYCLE — how many wave-1 issues one cycle takes, regardless of
// how many the planner found. Leftovers surface in the next run's plan.
const MAX_ISSUES_PER_CYCLE: number = 1;
// const MAX_ISSUES_PER_CYCLE: number = Infinity;

const MAX_ITERATIONS = ITERATIONS.loop;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Extract `<name>…</name>` from an agent's stdout, trimmed, or undefined. */
function tag(stdout: string, name: string): string | undefined {
  return stdout
    .match(new RegExp(`<${name}>([\\s\\S]*?)</${name}>`))?.[1]
    ?.trim();
}

// Runs `fn` over `items` with at most `limit` in flight, settling every one.
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
// KeyError, not a default. app/backend/.env is gitignored, so a Sandcastle
// worktree never has it; the values are injected here instead.
const SANDBOX_ENV: Record<string, string> = {
  DATABASE_URL: "postgres://kdps@localhost:5432/kdps_dev",
  DJANGO_SECRET_KEY: "sandcastle-sandbox-not-for-production",
  DJANGO_DEBUG: "1",
  DJANGO_ALLOWED_HOSTS: "*",
  SEED_DEMO: "1",
  EMERGENT_LLM_KEY: "sandcastle-placeholder",
  GEMINI_MODEL: "gemini-2.5-flash",
  // Cookie-authed requests over plain http would 401 with a Secure cookie.
  JWT_COOKIE_SECURE: "0",
  // The QA phase runs vite on 3000 against the API on 8001, cross-origin,
  // exactly like scripts/dev.sh does on a dev machine.
  REACT_APP_BACKEND_URL: "http://localhost:8001",
  VITE_LOCAL_DEV: "1",
};

// Package caches plus the /artifacts channel, shared across every sandbox and
// every run. /artifacts is how the pipeline's fresh contexts talk to each
// other (slice plan, findings, QA report, screenshots) and how the publisher —
// which runs in its own sandbox — reads what the pipelines produced. It is
// also where screenshots survive for the human after the run.
const CACHE_ROOT = join(homedir(), ".cache", "sandcastle-kdps");
const CACHES = [
  { hostPath: join(CACHE_ROOT, "uv"), sandboxPath: "/home/agent/.cache/uv" },
  { hostPath: join(CACHE_ROOT, "yarn"), sandboxPath: "/home/agent/.cache/yarn" },
  { hostPath: join(CACHE_ROOT, "artifacts"), sandboxPath: "/artifacts" },
];
for (const cache of CACHES) mkdirSync(cache.hostPath, { recursive: true });

const sandboxProvider = () => docker({ env: SANDBOX_ENV, mounts: CACHES });

// The planner and publisher only need git + gh, so they skip the 20-minute
// dependency boot. Everything that compiles or tests gets the full setup.
const planHooks = {};
const buildHooks = {
  sandbox: {
    onSandboxReady: [
      { command: "bash .sandcastle/sandbox-setup.sh", timeoutMs: 20 * 60_000 },
    ],
  },
};

// Nothing is copied from the host into the worktree — the host is macOS/arm64
// and the sandbox is Linux; the caches above give the speedup without the
// platform mismatch.
const copyToWorktree: string[] = [];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Issue = { id: string; title: string; branch: string };

type PipelineState =
  | "ready" //        built, reviewed, QA passed — real PR
  | "handed-back" //  a human must rule — draft PR, ready-for-human
  | "spec-stopped" // failed the spec gate — no branch, no PR
  | "no-commits"; //  builder produced nothing — no PR

type PipelineResult = {
  issue: Issue;
  state: PipelineState;
  note: string;
  commits: unknown[];
};

// ---------------------------------------------------------------------------
// The per-issue pipeline
// ---------------------------------------------------------------------------

async function runPipeline(issue: Issue): Promise<PipelineResult> {
  const artDir = `/artifacts/issue-${issue.id}`;
  const promptArgs = {
    TASK_ID: issue.id,
    ISSUE_TITLE: issue.title,
    BRANCH: issue.branch,
    ART_DIR: artDir,
  };

  const sandbox = await sandcastle.createSandbox({
    branch: issue.branch,
    sandbox: sandboxProvider(),
    hooks: buildHooks,
    copyToWorktree,
  });

  try {
    // --- Slicer: gate the issue, read the corpus, write the slice plan -----
    const slice = await sandbox.run({
      name: `slice-${issue.id}`,
      maxIterations: ITERATIONS.slicer,
      agent: sandcastle.claudeCode(MODELS.slicer),
      promptFile: "./.sandcastle/slice-prompt.md",
      promptArgs,
    });
    const gate = tag(slice.stdout, "gate") ?? "GO";
    if (gate.startsWith("STOP")) {
      return { issue, state: "spec-stopped", note: gate, commits: [] };
    }

    // --- Builder: fresh context, sees only the slice plan ------------------
    const build = await sandbox.run({
      name: `build-${issue.id}`,
      maxIterations: ITERATIONS.builder,
      agent: sandcastle.claudeCode(MODELS.builder),
      promptFile: "./.sandcastle/build-prompt.md",
      promptArgs,
    });
    if (build.commits.length === 0) {
      return {
        issue,
        state: "no-commits",
        note: "builder produced no commits",
        commits: [],
      };
    }
    const commits: unknown[] = [...build.commits];

    // --- Review → fix rounds (like /implement: two rounds, then escalate) --
    // The three axes run sequentially — they share the sandbox's working tree
    // and the claude CLI's home state, so concurrency inside one sandbox is
    // not worth the race. Each is a fresh context; cost is the same either way.
    let handedBack = false;
    let note = "";
    for (let round = 1; round <= REVIEW_ROUNDS; round++) {
      let anyFindings = false;
      for (const axis of ["standards", "spec", "correctness"] as const) {
        const review = await sandbox.run({
          name: `review-${axis}-r${round}`,
          maxIterations: ITERATIONS.reviewer,
          agent: sandcastle.claudeCode(REVIEW_MODELS[axis]),
          promptFile: `./.sandcastle/review-${axis}-prompt.md`,
          promptArgs: { ...promptArgs, ROUND: String(round) },
        });
        if (tag(review.stdout, "findings") === "FOUND") anyFindings = true;
      }
      if (!anyFindings) break;

      const fix = await sandbox.run({
        name: `fix-r${round}`,
        maxIterations: ITERATIONS.fixer,
        agent: sandcastle.claudeCode(MODELS.fixer),
        promptFile: "./.sandcastle/fix-prompt.md",
        promptArgs: { ...promptArgs, MODE: "review", ROUND: String(round) },
      });
      commits.push(...fix.commits);
      if (tag(fix.stdout, "verdict") === "HANDED_BACK") {
        handedBack = true;
        note = `review round ${round} handed back to a human`;
        break;
      }
    }

    // --- Browser QA (skipped once handed back — a human is already owed) ---
    if (!handedBack) {
      for (let attempt = 0; attempt <= QA_REDRIVES; attempt++) {
        const qa = await sandbox.run({
          name: attempt === 0 ? "qa" : `qa-redrive-${attempt}`,
          maxIterations: ITERATIONS.qa,
          agent: sandcastle.claudeCode(MODELS.qa),
          promptFile: "./.sandcastle/qa-prompt.md",
          promptArgs: {
            ...promptArgs,
            MODE: attempt === 0 ? "full" : "re-drive",
          },
        });
        if (tag(qa.stdout, "qa") === "PASS") break;

        if (attempt === QA_REDRIVES) {
          handedBack = true;
          note = `QA still failing after ${QA_REDRIVES} re-drives`;
          break;
        }
        const fix = await sandbox.run({
          name: `qa-fix-${attempt + 1}`,
          maxIterations: ITERATIONS.fixer,
          agent: sandcastle.claudeCode(MODELS.fixer),
          promptFile: "./.sandcastle/fix-prompt.md",
          promptArgs: { ...promptArgs, MODE: "qa", ROUND: String(attempt + 1) },
        });
        commits.push(...fix.commits);
        if (tag(fix.stdout, "verdict") === "HANDED_BACK") {
          handedBack = true;
          note = "QA finding handed back to a human";
          break;
        }
      }
    }

    return {
      issue,
      state: handedBack ? "handed-back" : "ready",
      note: handedBack ? note : "built, reviewed, QA passed",
      commits,
    };
  } finally {
    await sandbox.close();
  }
}

// ---------------------------------------------------------------------------
// Main loop
// ---------------------------------------------------------------------------

for (let iteration = 1; iteration <= MAX_ITERATIONS; iteration++) {
  console.log(`\n=== Iteration ${iteration}/${MAX_ITERATIONS} ===\n`);

  // --- Phase 1: Plan --------------------------------------------------------
  const plan = await sandcastle.run({
    hooks: planHooks,
    sandbox: sandboxProvider(),
    name: "planner",
    maxIterations: ITERATIONS.planner,
    agent: sandcastle.claudeCode(MODELS.planner),
    promptFile: "./.sandcastle/plan-prompt.md",
  });

  const planJson = tag(plan.stdout, "plan");
  if (!planJson) {
    throw new Error("Planning agent did not produce a <plan> tag.\n\n" + plan.stdout);
  }
  const { waves } = JSON.parse(planJson) as { waves: Issue[][] };

  const waveOne = waves[0] ?? [];
  const issues =
    MAX_ISSUES_PER_CYCLE === Infinity
      ? waveOne
      : waveOne.slice(0, MAX_ISSUES_PER_CYCLE);

  if (issues.length < waveOne.length) {
    console.log(
      `Wave 1 has ${waveOne.length} issue(s); taking ${issues.length} this cycle (MAX_ISSUES_PER_CYCLE).`,
    );
  }
  const deferred = waves.slice(1).flat();
  if (deferred.length > 0) {
    console.log(
      `Deferred to a later run (blocked by wave 1, which must merge first):`,
    );
    for (const issue of deferred) console.log(`  ${issue.id}: ${issue.title}`);
  }

  if (issues.length === 0) {
    console.log("No workable issues. Exiting.");
    break;
  }

  console.log(
    `Planning complete. ${issues.length} issue(s) this cycle, ${
      MAX_CONCURRENT_ISSUES === 1
        ? "one at a time"
        : `up to ${MAX_CONCURRENT_ISSUES} at a time`
    }:`,
  );
  for (const issue of issues) {
    console.log(`  ${issue.id}: ${issue.title} → ${issue.branch}`);
  }

  // --- Phase 2: Pipelines ---------------------------------------------------
  const settled = await allSettledWithLimit(
    issues,
    MAX_CONCURRENT_ISSUES,
    runPipeline,
  );

  const results: PipelineResult[] = [];
  for (const [i, outcome] of settled.entries()) {
    if (outcome.status === "fulfilled") {
      results.push(outcome.value);
      console.log(
        `  ${outcome.value.state === "ready" ? "✓" : "•"} ${outcome.value.issue.id} — ${outcome.value.state}: ${outcome.value.note}`,
      );
    } else {
      console.error(
        `  ✗ ${issues[i]!.id} (${issues[i]!.branch}) crashed: ${outcome.reason}`,
      );
      // A crashed pipeline is a failed run. Settling every pipeline keeps one
      // failure from cancelling the others, but the process must not then exit
      // 0 — unattended, that reads to a wrapper as a clean run that simply had
      // nothing to do.
      process.exitCode = 1;
    }
  }

  // Only branches with commits reach the publisher. Handed-back branches go
  // too — as draft PRs, so the work and the open question are both preserved.
  const publishable = results.filter(
    (r) =>
      (r.state === "ready" || r.state === "handed-back") && r.commits.length > 0,
  );

  if (publishable.length === 0) {
    console.log("\nNothing to publish this cycle.");
    continue;
  }

  // --- Phase 3: Publish -----------------------------------------------------
  // Runs with planHooks: pushing and opening PRs needs git + gh, not a
  // 20-minute dependency boot. THE PUSH IS THE CI — cloud CI runs the full
  // gate on GitHub for every branch pushed here.
  await sandcastle.run({
    hooks: planHooks,
    sandbox: sandboxProvider(),
    name: "publisher",
    maxIterations: ITERATIONS.publisher,
    agent: sandcastle.claudeCode(MODELS.publisher),
    promptFile: "./.sandcastle/publish-prompt.md",
    promptArgs: {
      BRANCHES: publishable
        .map(
          (r) =>
            `- ${r.issue.branch} — issue #${r.issue.id} — state: ${r.state}` +
            ` (${r.note}) — artifacts: /artifacts/issue-${r.issue.id}`,
        )
        .join("\n"),
      ISSUES: publishable
        .map((r) => `- ${r.issue.id}: ${r.issue.title}`)
        .join("\n"),
    },
  });

  console.log("\nPull requests opened. Cloud CI is running on each push.");
}

console.log("\nAll done.");
