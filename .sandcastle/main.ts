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
//                          ci-check — runs `npm run ci:fast` (mypy, the
//                                    migration/DB-drift checks, import-
//                                    linter, both test suites — everything
//                                    in `npm run ci` except ruff) inside the
//                                    same sandbox, as the branch's pre-merge
//                                    filter.
//   Phase 3 (Merge):     Plain git on the host, no agent: every issue that
//                        came out "ready" gets `git merge --no-ff` onto the
//                        host's checked-out `main`, sequentially — then the
//                        REAL gate runs: `npm run ci:fast` once more on the
//                        merged main (individually-green branches have
//                        broken main before — the #146 hotfix). Green →
//                        issues close and branches delete, so the next
//                        iteration's planner sees the progress. Red → main
//                        resets to the pre-wave SHA and the run stops.
//                        Nothing is pushed and no PR is opened — a human
//                        reviews `git log` and pushes by hand when ready.
//
// Agents talk through /artifacts (a host mount, ~/.cache/sandcastle-kdps/
// artifacts), never through each other's transcripts. Control flow reads one
// tag from stdout per run: <gate>, <findings>, <verdict>, <qa>.
//
// Usage:  npx tsx .sandcastle/main.ts   (or: npm run sandcastle)

import { appendFileSync, existsSync, mkdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
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
  ciCheck: "claude-sonnet-5", // runs `npm run ci` in-sandbox, reports pass/fail
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
// `loop` is plan→pipeline→merge cycles; the rest cap how many turns each
// agent gets. The builder is the only one that needs a lot.
//
// A cap is a SAFETY NET, not a schedule — every phase below also carries a
// completion signal (see SIGNALS), so it stops the moment it emits its verdict
// tag. Before signals were wired, each phase burned its whole cap re-doing
// finished work: on the #229 run the slicer ran its 4th iteration, found the
// plan file it had written itself on iteration 1, failed to recognise it, and
// spent minutes re-verifying it. That alone was ~20 of the run's 83 minutes.
const ITERATIONS = {
  loop: 6,
  planner: 1,
  // The slicer gates the issue AND reads the corpus. Two is the net: one to do
  // the work, one to recover from a tool failure mid-way. A missing <gate>
  // defaults to GO, so a cap must never be what decides an issue is workable —
  // the signal is.
  slicer: 2,
  builder: 100,
  reviewer: 1,
  fixer: 3,
  qa: 2,
  ciCheck: 2,
} as const;

// --- Completion signals ------------------------------------------------------
// Sandcastle stops a run's iteration loop as soon as the agent's output
// contains one of these substrings (default: "<promise>COMPLETE</promise>",
// which only the builder prompt emits). Every other phase already
// ends by printing a verdict tag that control flow reads — so the verdict tag
// IS the completion signal. No prompt change, and no way to forget one.
//
// Matched with `includes`, so an agent that narrates the literal tag mid-work
// would stop early. The prompts all say "output exactly one", and the caps
// above remain the backstop.
const SIGNALS = {
  planner: ["</plan>"],
  slicer: ["<gate>GO</gate>", "<gate>STOP"],
  reviewer: ["<findings>FOUND</findings>", "<findings>NONE</findings>"],
  fixer: [
    "<verdict>CLEAN</verdict>",
    "<verdict>FIXED</verdict>",
    "<verdict>HANDED_BACK</verdict>",
  ],
  qa: ["<qa>PASS</qa>", "<qa>FAIL</qa>"],
  ciCheck: ["<ci>PASS</ci>", "<ci>FAIL"],
};

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
// const MAX_CONCURRENT_ISSUES: number = 1;        // sequential
const MAX_CONCURRENT_ISSUES: number = 3; //         limited parallel
// const MAX_CONCURRENT_ISSUES: number = Infinity; // whole wave at once

// MAX_ISSUES_PER_CYCLE — how many wave-1 issues one cycle takes, regardless of
// how many the planner found. Leftovers surface in the next run's plan.
// const MAX_ISSUES_PER_CYCLE: number = 1;
const MAX_ISSUES_PER_CYCLE: number = Infinity; // all of wave 1, throttled by
// MAX_CONCURRENT_ISSUES above rather than deferred to a later cycle.

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
// other (slice plan, findings, QA report, screenshots), and where screenshots
// survive for the human after the run.
const CACHE_ROOT = join(homedir(), ".cache", "sandcastle-kdps");
const CACHES = [
  { hostPath: join(CACHE_ROOT, "uv"), sandboxPath: "/home/agent/.cache/uv" },
  { hostPath: join(CACHE_ROOT, "yarn"), sandboxPath: "/home/agent/.cache/yarn" },
  { hostPath: join(CACHE_ROOT, "artifacts"), sandboxPath: "/artifacts" },
];
for (const cache of CACHES) mkdirSync(cache.hostPath, { recursive: true });

const sandboxProvider = () => docker({ env: SANDBOX_ENV, mounts: CACHES });

// The planner only needs git + gh, so it skips the 20-minute dependency boot.
// Everything that compiles or tests gets the full setup.
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
// Logging — one folder per invocation, one per loop iteration inside it, one
// subfolder per issue inside that.
// ---------------------------------------------------------------------------

const REPO_ROOT = process.cwd();

// Timestamped per-invocation root, so re-running the script never appends a
// second run's summary into a previous run's main.log.
const LOGS_ROOT = join(
  REPO_ROOT,
  ".sandcastle",
  "logs",
  new Date().toISOString().replace(/[:]/g, "-").slice(0, 19),
);

/** `.sandcastle/logs/<stamp>/run-<iteration>/`, created on first use. */
function runLogDir(iteration: number): string {
  const dir = join(LOGS_ROOT, `run-${iteration}`);
  mkdirSync(dir, { recursive: true });
  return dir;
}

/** `.sandcastle/logs/run-<iteration>/issue-<id>/`, created on first use. */
function issueLogDir(runDir: string, issueId: string): string {
  const dir = join(runDir, `issue-${issueId}`);
  mkdirSync(dir, { recursive: true });
  return dir;
}

/** Prints to stdout AND appends to `<runDir>/main.log` — the one file that
 * carries the top-level plan/pipeline/merge summary a flat `console.log`
 * would otherwise only ever put on the terminal. */
function mainLog(runDir: string, message: string): void {
  console.log(message);
  appendFileSync(join(runDir, "main.log"), message + "\n");
}

// ---------------------------------------------------------------------------
// Host git/gh plumbing
// ---------------------------------------------------------------------------

/** Run git in the host repo via execFile — no shell, so an LLM-authored
 * branch name or issue title can never be interpreted as shell syntax. */
function git(...args: string[]): string {
  return execFileSync("git", args, {
    cwd: REPO_ROOT,
    encoding: "utf8",
  }).trim();
}

/** gh bookkeeping (labels, closing issues) from the host. Logged, never
 * fatal — a gh hiccup must not kill a run that already did the work, but a
 * silent failure here would make the next iteration re-plan a finished
 * issue, so every failure lands in main.log. */
function gh(runDir: string, ...args: string[]): void {
  try {
    execFileSync("gh", [...args, "-R", "bruhanand/KDPS"], {
      cwd: REPO_ROOT,
      encoding: "utf8",
    });
  } catch (error) {
    mainLog(runDir, `  (gh ${args.join(" ")} failed: ${error})`);
  }
}

/** The host's checked-out branch must be `main` and clean — merges land
 * straight on it. Called before the loop AND at the top of every iteration:
 * checking once at startup is not enough, because anything that leaves the
 * tree dirty mid-run (an interrupted merge, a stray edit) would otherwise
 * poison every later wave silently. */
function assertCleanMain(): void {
  const currentBranch = git("rev-parse", "--abbrev-ref", "HEAD");
  if (currentBranch !== "main") {
    throw new Error(
      `Host repo is on branch "${currentBranch}", not "main". Local merges ` +
        `land on whatever is checked out here — switch to main first.`,
    );
  }
  const dirty = git("status", "--porcelain");
  if (dirty.length > 0) {
    throw new Error(
      "Host repo has uncommitted changes — commit or stash them, since " +
        `every merge lands directly on this checked-out main:\n${dirty}`,
    );
  }
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Issue = { id: string; title: string; branch: string };

type PipelineState =
  | "ready" //        built, reviewed, QA passed, local `npm run ci:fast`
  //                  green — mergeable
  | "handed-back" //  a human must rule — branch kept, not merged
  | "spec-stopped" // failed the spec gate — no branch, no commits
  | "no-commits"; //  builder produced nothing

type PipelineResult = {
  issue: Issue;
  state: PipelineState;
  note: string;
  commits: unknown[];
};

// ---------------------------------------------------------------------------
// The per-issue pipeline
// ---------------------------------------------------------------------------

async function runPipeline(
  issue: Issue,
  runDir: string,
): Promise<PipelineResult> {
  const artDir = `/artifacts/issue-${issue.id}`;
  const promptArgs = {
    TASK_ID: issue.id,
    ISSUE_TITLE: issue.title,
    BRANCH: issue.branch,
    ART_DIR: artDir,
  };
  const logDir = issueLogDir(runDir, issue.id);
  const logPath = (name: string) => join(logDir, `${name}.log`);

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
      completionSignal: SIGNALS.slicer,
      agent: sandcastle.claudeCode(MODELS.slicer),
      promptFile: "./.sandcastle/slice-prompt.md",
      promptArgs,
      logging: { type: "file", path: logPath("slice") },
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
      logging: { type: "file", path: logPath("build") },
    });
    // "No new commits" is only a failure when the branch holds nothing at all.
    // A branch resumed from an earlier run (the work built, reviewed and
    // synced to the host then) legitimately gives the builder nothing to do —
    // measure the branch against main, not this run's commit count, or a
    // finished branch spins as "no-commits" forever and its wave never merges
    // (issue #240 on the second launch).
    const branchAhead = Number(
      git("rev-list", "--count", `main..${issue.branch}`),
    );
    if (build.commits.length === 0 && branchAhead === 0) {
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
    //
    // The loop runs one round MORE than it fixes. Rounds 1..REVIEW_ROUNDS may
    // review and then fix; the last round only reviews. Without it the final
    // fix shipped unread: on the #229 run round 2 found something, the fixer
    // changed code, and nothing looked at that change before QA. A finding that
    // survives every fix round is a design signal, so it hands back rather than
    // buying a third fix.
    let handedBack = false;
    let note = "";
    for (let round = 1; round <= REVIEW_ROUNDS + 1; round++) {
      let anyFindings = false;
      for (const axis of ["standards", "spec", "correctness"] as const) {
        const review = await sandbox.run({
          name: `review-${axis}-r${round}`,
          maxIterations: ITERATIONS.reviewer,
          completionSignal: SIGNALS.reviewer,
          agent: sandcastle.claudeCode(REVIEW_MODELS[axis]),
          promptFile: `./.sandcastle/review-${axis}-prompt.md`,
          promptArgs: { ...promptArgs, ROUND: String(round) },
          logging: { type: "file", path: logPath(`review-${axis}-r${round}`) },
        });
        if (tag(review.stdout, "findings") === "FOUND") anyFindings = true;
      }
      if (!anyFindings) break;

      if (round > REVIEW_ROUNDS) {
        handedBack = true;
        note = `findings still open after ${REVIEW_ROUNDS} fix rounds`;
        break;
      }

      const fix = await sandbox.run({
        name: `fix-r${round}`,
        maxIterations: ITERATIONS.fixer,
        completionSignal: SIGNALS.fixer,
        agent: sandcastle.claudeCode(MODELS.fixer),
        promptFile: "./.sandcastle/fix-prompt.md",
        promptArgs: { ...promptArgs, MODE: "review", ROUND: String(round) },
        logging: { type: "file", path: logPath(`fix-review-r${round}`) },
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
        const qaName = attempt === 0 ? "qa" : `qa-redrive-${attempt}`;
        const qa = await sandbox.run({
          name: qaName,
          maxIterations: ITERATIONS.qa,
          completionSignal: SIGNALS.qa,
          agent: sandcastle.claudeCode(MODELS.qa),
          promptFile: "./.sandcastle/qa-prompt.md",
          promptArgs: {
            ...promptArgs,
            MODE: attempt === 0 ? "full" : "re-drive",
          },
          logging: { type: "file", path: logPath(qaName) },
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
          completionSignal: SIGNALS.fixer,
          agent: sandcastle.claudeCode(MODELS.fixer),
          promptFile: "./.sandcastle/fix-prompt.md",
          promptArgs: { ...promptArgs, MODE: "qa", ROUND: String(attempt + 1) },
          logging: { type: "file", path: logPath(`qa-fix-${attempt + 1}`) },
        });
        commits.push(...fix.commits);
        if (tag(fix.stdout, "verdict") === "HANDED_BACK") {
          handedBack = true;
          note = "QA finding handed back to a human";
          break;
        }
      }
    }

    // --- Local CI gate (replaces cloud CI — nothing is pushed to GitHub) ---
    // `npm run ci:fast` is `npm run ci` minus ruff (formatting is the
    // Standards review axis's job): mypy on the money kernel, the
    // migration/DB-drift checks, import-linter, and both test suites. This
    // in-sandbox run is the branch's pre-merge filter; the host re-runs the
    // same command on MERGED main before anything counts as landed, so a
    // hallucinated PASS here cannot land broken code.
    if (!handedBack) {
      const ci = await sandbox.run({
        name: "ci-check",
        maxIterations: ITERATIONS.ciCheck,
        completionSignal: SIGNALS.ciCheck,
        agent: sandcastle.claudeCode(MODELS.ciCheck),
        promptFile: "./.sandcastle/ci-check-prompt.md",
        promptArgs,
        logging: { type: "file", path: logPath("ci-check") },
      });
      if (tag(ci.stdout, "ci") !== "PASS") {
        handedBack = true;
        note = "local `npm run ci:fast` failed — see ci-check.log";
      }
    }

    return {
      issue,
      state: handedBack ? "handed-back" : "ready",
      note: handedBack ? note : "built, reviewed, QA passed, ci:fast green",
      commits,
    };
  } finally {
    await sandbox.close();
  }
}

// ---------------------------------------------------------------------------
// Main loop
// ---------------------------------------------------------------------------

assertCleanMain();

for (let iteration = 1; iteration <= MAX_ITERATIONS; iteration++) {
  const runDir = runLogDir(iteration);
  mainLog(runDir, `\n=== Iteration ${iteration}/${MAX_ITERATIONS} ===\n`);

  // Re-checked every iteration — a dirty or mid-merge main means nothing
  // this wave builds could land, so stopping now is cheaper than finding
  // out after three sandboxes ran for an hour.
  assertCleanMain();

  // --- Phase 1: Plan --------------------------------------------------------
  const plan = await sandcastle.run({
    hooks: planHooks,
    sandbox: sandboxProvider(),
    name: "planner",
    maxIterations: ITERATIONS.planner,
    completionSignal: SIGNALS.planner,
    agent: sandcastle.claudeCode(MODELS.planner),
    promptFile: "./.sandcastle/plan-prompt.md",
    logging: { type: "file", path: join(runDir, "planner.log") },
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
    mainLog(
      runDir,
      `Wave 1 has ${waveOne.length} issue(s); taking ${issues.length} this cycle (MAX_ISSUES_PER_CYCLE).`,
    );
  }
  const deferred = waves.slice(1).flat();
  if (deferred.length > 0) {
    mainLog(
      runDir,
      `Deferred to a later run (blocked by wave 1, which must merge first):`,
    );
    for (const issue of deferred) mainLog(runDir, `  ${issue.id}: ${issue.title}`);
  }

  if (issues.length === 0) {
    mainLog(runDir, "No workable issues. Exiting.");
    break;
  }

  mainLog(
    runDir,
    `Planning complete. ${issues.length} issue(s) this cycle, ${
      MAX_CONCURRENT_ISSUES === 1
        ? "one at a time"
        : `up to ${MAX_CONCURRENT_ISSUES} at a time`
    }:`,
  );
  for (const issue of issues) {
    mainLog(runDir, `  ${issue.id}: ${issue.title} → ${issue.branch}`);
  }

  // --- Phase 2: Pipelines ---------------------------------------------------
  const settled = await allSettledWithLimit(issues, MAX_CONCURRENT_ISSUES, (issue) =>
    runPipeline(issue, runDir),
  );

  const results: PipelineResult[] = [];
  for (const [i, outcome] of settled.entries()) {
    if (outcome.status === "fulfilled") {
      results.push(outcome.value);
      mainLog(
        runDir,
        `  ${outcome.value.state === "ready" ? "✓" : "•"} ${outcome.value.issue.id} — ${outcome.value.state}: ${outcome.value.note}`,
      );
    } else {
      mainLog(
        runDir,
        `  ✗ ${issues[i]!.id} (${issues[i]!.branch}) crashed: ${outcome.reason}`,
      );
      // A crashed pipeline is a failed run. Settling every pipeline keeps one
      // failure from cancelling the others, but the process must not then exit
      // 0 — unattended, that reads to a wrapper as a clean run that simply had
      // nothing to do.
      process.exitCode = 1;
    }
  }

  // --- Phase 3: Merge — local only, nothing pushed, no PR opened ------------
  // Merging is plain git on the host, done sequentially because there is
  // exactly one `main` working tree to land on even though up to
  // MAX_CONCURRENT_ISSUES pipelines just finished at once. The real gate is
  // below: `npm run ci:fast` re-run on the MERGED main.
  // "ready" is the whole test: the pipeline only returns it after review, QA
  // and ci:fast all passed on whatever the branch holds. Requiring this run's
  // commit count on top of that excluded branches resumed from an earlier
  // run, where the work predates this process. The no-commits guard upstream
  // already rejects branches with nothing on them at all.
  const mergeable = results.filter((r) => r.state === "ready");
  const handedBack = results.filter((r) => r.state === "handed-back");

  // Relabel every hand-back from the host. The fixer only relabels on its
  // own HANDED_BACK verdict — findings-exhausted, QA-exhausted and ci-check
  // failures are decided here in main.ts, and without this the issue would
  // keep `ready-for-agent`, get silently re-planned next iteration, and
  // could merge unreviewed on the retry while a human was owed a ruling.
  if (handedBack.length > 0) {
    mainLog(runDir, "\nHanded back — branch kept, not merged, needs a human:");
    for (const r of handedBack) {
      mainLog(runDir, `  ${r.issue.branch} — issue #${r.issue.id}: ${r.note}`);
      gh(
        runDir,
        "issue",
        "edit",
        r.issue.id,
        "--add-label",
        "ready-for-human",
        "--remove-label",
        "ready-for-agent",
      );
      // The label alone leaves the human staring at an unexplained hand-back
      // (issue #242 on the first run sat with no reason on it). Say why, and
      // where the evidence lives.
      gh(
        runDir,
        "issue",
        "comment",
        r.issue.id,
        "--body",
        `Sandcastle handed this back: ${r.note}.\n\n` +
          `Branch \`${r.issue.branch}\` holds the work, unmerged. ` +
          `Findings, QA report and deviations are in this run's artifacts ` +
          `(\`.sandcastle/worktrees/\` + the run's log folder). ` +
          `Rule on it, fold the ruling into the issue BODY (not just a comment), ` +
          `and relabel \`ready-for-agent\` to re-queue.`,
      );
    }
  }

  if (mergeable.length === 0) {
    mainLog(runDir, "\nNothing to merge this cycle.");
    continue;
  }

  const preWaveSha = git("rev-parse", "HEAD");
  const merged: PipelineResult[] = [];

  mainLog(runDir, `\nMerging ${mergeable.length} branch(es) into local main:`);
  for (const r of mergeable) {
    try {
      git(
        "merge",
        "--no-ff",
        r.issue.branch,
        "-m",
        `Merge ${r.issue.branch} (issue #${r.issue.id}: ${r.issue.title})`,
      );
      merged.push(r);
      mainLog(runDir, `  ✓ ${r.issue.branch} (issue #${r.issue.id})`);
    } catch (error) {
      // git names the conflicted files on STDOUT — keep both streams, or the
      // log records "merge failed" without the one detail a human needs.
      const e = error as { stdout?: string; stderr?: string };
      mainLog(
        runDir,
        `  ✗ ${r.issue.branch} (issue #${r.issue.id}) — merge failed:\n` +
          `${e.stdout ?? ""}${e.stderr ?? ""}`,
      );
      // Abort immediately: a half-done merge leaves unmerged files that make
      // every later merge fail and would poison the rest of the run. And a
      // conflict means overlapping work, so the issue goes to a human rather
      // than being rebuilt on a stale branch next iteration.
      try {
        git("merge", "--abort");
      } catch {
        // no merge in progress — nothing to abort
      }
      gh(
        runDir,
        "issue",
        "edit",
        r.issue.id,
        "--add-label",
        "ready-for-human",
        "--remove-label",
        "ready-for-agent",
      );
      gh(
        runDir,
        "issue",
        "comment",
        r.issue.id,
        "--body",
        `Sandcastle built this on branch ${r.issue.branch}, but it conflicts ` +
          `with work that merged before it. The branch is kept locally — a ` +
          `human needs to resolve the merge.`,
      );
      process.exitCode = 1;
    }
  }

  if (merged.length === 0) {
    mainLog(runDir, "\nNo branch survived the merge this cycle.");
    continue;
  }

  // --- The real gate: ci:fast on MERGED main, on the host -------------------
  // Each branch was green in its own sandbox against main-as-of-wave-start.
  // That proves nothing about their combination — two individually green
  // branches have broken main at the contract tests before (the #146
  // hotfix), and two backend branches can each add a migration with the same
  // parent, leaving merged main with two leaves that `migrate` refuses. One
  // deterministic run here catches all of that, and is also the check on the
  // in-sandbox ci agent's self-reported PASS.
  // Apply the wave's migrations to the host DB first: check_db_drift asks
  // "is the database what the migrations say?", so any merged branch that
  // adds a migration fails the gate until `migrate` runs — launch 1 and
  // launch 5 both died exactly here (alerts.0003 / sell.0014). A migration
  // that itself fails to apply is a genuine gate failure and lands in the
  // same catch as everything else.
  mainLog(runDir, "\nApplying merged migrations to the host DB:");
  try {
    execFileSync("uv", ["run", "python", "manage.py", "migrate", "--no-input"], {
      cwd: join(REPO_ROOT, "app", "backend"),
      encoding: "utf8",
      maxBuffer: 32 * 1024 * 1024,
    });
    mainLog(runDir, "  ✓ host DB migrated");
  } catch (error) {
    const e = error as { stdout?: string; stderr?: string };
    const tail = ((e.stdout ?? "") + (e.stderr ?? ""))
      .split("\n")
      .slice(-40)
      .join("\n");
    mainLog(runDir, `  ✗ migrate FAILED on merged main. Last lines:\n${tail}`);
    git("reset", "--hard", preWaveSha);
    mainLog(
      runDir,
      `\nmain reset to ${preWaveSha}. This wave's branches are kept ` +
        "unmerged for a human, and the run stops here — later waves would " +
        "build on a main this gate cannot certify.",
    );
    process.exitCode = 1;
    break;
  }

  mainLog(runDir, "\nRunning `npm run ci:fast` on merged main (host):");
  try {
    execFileSync("npm", ["run", "ci:fast"], {
      cwd: REPO_ROOT,
      encoding: "utf8",
      maxBuffer: 32 * 1024 * 1024,
    });
    mainLog(runDir, "  ✓ merged main is green");
  } catch (error) {
    const e = error as { stdout?: string; stderr?: string };
    const tail = ((e.stdout ?? "") + (e.stderr ?? ""))
      .split("\n")
      .slice(-60)
      .join("\n");
    mainLog(runDir, `  ✗ ci:fast FAILED on merged main. Last lines:\n${tail}`);
    git("reset", "--hard", preWaveSha);
    mainLog(
      runDir,
      `\nmain reset to ${preWaveSha}. This wave's branches are kept ` +
        "unmerged for a human, and the run stops here — later waves would " +
        "build on a main this gate cannot certify.",
    );
    process.exitCode = 1;
    break;
  }

  // Bookkeeping only AFTER the gate: a closed issue is the signal the next
  // iteration's planner (issue list) and slicer (blocker check) read, so it
  // must only ever mean "this work is actually on main". Deleting the merged
  // branch stops a later iteration from resurrecting a stale worktree on it.
  for (const r of merged) {
    gh(
      runDir,
      "issue",
      "close",
      r.issue.id,
      "--comment",
      `Merged to local main by sandcastle (branch ${r.issue.branch}; ` +
        "`npm run ci:fast` green on merged main). Not yet pushed to GitHub.",
    );
    try {
      // The library parks each branch in .sandcastle/worktrees/<branch with
      // slashes dashed>; git refuses to delete a branch a worktree holds, so
      // the worktree goes first (this failed live on #240's merge).
      const worktreePath = `.sandcastle/worktrees/${r.issue.branch.replace(/\//g, "-")}`;
      if (existsSync(worktreePath)) {
        git("worktree", "remove", "--force", worktreePath);
      }
      // -D, not -d: a branch that was pushed (draft PR) has an upstream git
      // considers unmerged even when main holds every commit. This runs only
      // after the merge gate certified the branch is in main, so force is safe.
      git("branch", "-D", r.issue.branch);
    } catch (error) {
      mainLog(runDir, `  (branch cleanup for ${r.issue.branch} failed: ${error})`);
    }
  }

  mainLog(
    runDir,
    "\nMerged locally onto main, gate green, issues closed. Nothing was " +
      "pushed to GitHub — review `git log` and push when ready.",
  );
}

console.log("\nAll done.");
