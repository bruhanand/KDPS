import { defineConfig, devices } from "@playwright/test";

// Live QA runs here. `docs/agents/phases/live-qa.md` is the method; this file is
// only the wiring.
//
// PORTS ARE PER WORKSPACE. Every Conductor workspace owns its own Postgres, API
// and PWA on its own ports (scripts/workspace-env.sh), so a hard-coded 3000 QAs
// whichever workspace happens to be up - which is how you spend an afternoon
// debugging a branch you are not on. `scripts/e2e.sh` sources workspace-env.sh
// and exports KDPS_WEB_PORT before calling us; the fallbacks below match that
// script's own fallbacks so a plain `npx playwright test` still works on a
// non-Conductor checkout.
const webPort =
  process.env.KDPS_WEB_PORT ??
  (process.env.CONDUCTOR_PORT ? String(Number(process.env.CONDUCTOR_PORT)) : "3000");

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./e2e-results/artifacts",

  // ONE WORKER, DELIBERATELY. Every spec drives the one seeded dev database this
  // workspace owns. Two workers billing against the same till, or approving the
  // same document, fail in ways that look like product bugs and are not.
  workers: 1,
  fullyParallel: false,

  // NO RETRIES, DELIBERATELY. A retry turns a real intermittent defect into a
  // green run. The POS till is offline-first, queue-backed and race-prone - the
  // flake IS the finding. If a spec is genuinely non-deterministic, fix the spec.
  retries: 0,

  // `test.only` left in a spec silently skips everything else. Refuse it outside
  // an interactive run.
  forbidOnly: !!process.env.CI,

  timeout: 60_000,
  expect: { timeout: 10_000 },

  reporter: process.env.CI
    ? [["list"], ["html", { outputFolder: "e2e-results/report", open: "never" }]]
    : [["list"], ["html", { outputFolder: "e2e-results/report", open: "never" }]],

  use: {
    baseURL: process.env.PW_BASE_URL ?? `http://localhost:${webPort}`,

    // Evidence, only when something failed. A trace is a full DOM + network +
    // console recording opened with `npx playwright show-trace` - it is what an
    // agent reports a path to instead of pasting a screenshot into its context.
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",

    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // AFTER the spread, not in the block above: a project's `use` beats the
        // top-level one, so a viewport set up there is silently replaced by
        // Desktop Chrome's 1280x720 and every screenshot lies about the size the
        // screen was judged at. Stores run this on a counter machine, not a
        // phone - QA at the size the people who will use it have.
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
});
