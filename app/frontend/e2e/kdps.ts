import { expect, test as base, type Locator, type Page } from "@playwright/test";

// The live-QA toolkit. Import `test` and `expect` from here, never from
// `@playwright/test` directly - the extended `test` carries the guards below,
// and a spec that bypasses them is a spec that can pass over a console full of
// React errors.
//
// Three failure modes this repo has actually shipped, and what catches each:
//
//   the button that calls nothing   -> the network guard, plus an explicit
//                                      `expectCall()` around the click
//   money rendered as raw paise     -> `expectMoney()`
//   read scope failing open         -> `loginAs()` per role + a negative flow,
//                                      which is cheap only because a Playwright
//                                      context starts with no cookies at all
//
// Dialogs need no handling here: Playwright auto-dismisses `alert`/`confirm`,
// so the trap that freezes a browser-driving agent until a human clicks does
// not exist in this harness. `window.print()` is the exception - see below.

/** The seeded logins, from `memory/test_credentials.md`. Keep them in step. */
export const ROLES = {
  superadmin: { username: "superadmin", password: "Super@123" },
  admin: { username: "admin", password: "Admin@123" },
  owner: { username: "owner", password: "Owner@123" },
  ops: { username: "ops1", password: "Ops@123" },
  promo: { username: "promo1", password: "Promo@123" },
  accounts: { username: "accounts1", password: "Acct@123" },
  brandManager: { username: "brand1", password: "Brand@123" },
  warehouse: { username: "wh.patna", password: "Wh@123" },
  warehouseRanchi: { username: "wh.ranchi", password: "Wh@123" },
  steward: { username: "steward", password: "Steward@123" },
  deoManager: { username: "deo.manager", password: "Store@123" },
  deoCashier: { username: "deo.cashier", password: "Store@123" },
  bkrManager: { username: "bkr.manager", password: "Store@123" },
  bkrCashier: { username: "bkr.cashier", password: "Store@123" },
  hzbManager: { username: "hzb.manager", password: "Store@123" },
  dumManager: { username: "dum.manager", password: "Store@123" },
  bankaManager: { username: "banka.manager", password: "Store@123" },
  bankaCashier: { username: "banka.cashier", password: "Store@123" },
} as const;

export type RoleKey = keyof typeof ROLES;

/**
 * Indian money, as a store user reads it: `₹2,85,000` - last group of three,
 * every group before it a pair. A raw-paise render (`28500000`) has no grouping
 * and fails this, which is the point.
 */
export const INDIAN_MONEY = /-?₹\s?(\d{1,2}(,\d{2})*,\d{3}|\d{1,3})(\.\d{2})?/;

interface Guard {
  /** Console lines this flow is expected to produce. Give a reason. */
  allowConsole(pattern: RegExp, reason: string): void;
  /** Responses this flow is expected to fail. A 403 in a scope-negative flow is the flow working. */
  allowResponse(pattern: RegExp, reason: string): void;
  /** Every request the page has made, for asserting a click actually called something. */
  requests(): { method: string; url: string; status: number }[];
}

export const test = base.extend<{ guard: Guard }>({
  guard: [
    async ({ page }, use, testInfo) => {
      const consoleErrors: string[] = [];
      const badResponses: string[] = [];
      const seen: { method: string; url: string; status: number }[] = [];
      const allowedConsole: RegExp[] = [];
      const allowedResponses: RegExp[] = [];

      // Chrome's print preview is browser chrome: no click or key Playwright
      // sends reaches it, and the run hangs. The Billing screen prints through a
      // hidden `<iframe title="Receipt">`, so intercept that frame's window
      // before anything can call it. Product code is untouched, and
      // `receiptsPrinted(page)` becomes the evidence that the receipt was built
      // and what it said.
      await page.addInitScript(() => {
        const orig = Object.getOwnPropertyDescriptor(
          HTMLIFrameElement.prototype,
          "contentWindow",
        )!.get!;
        (window as unknown as { __printed: string[] }).__printed = [];
        Object.defineProperty(HTMLIFrameElement.prototype, "contentWindow", {
          configurable: true,
          get(this: HTMLIFrameElement) {
            const real = orig.call(this) as Window;
            if (this.title !== "Receipt") return real;
            return {
              focus() {},
              print() {
                (window as unknown as { __printed: string[] }).__printed.push(
                  real.document.documentElement.innerText,
                );
              },
            };
          },
        });
        // Anything that reaches for the top-level print dialog by another route.
        window.print = () => {
          (window as unknown as { __printed: string[] }).__printed.push("[window.print]");
        };
      });

      page.on("console", (msg) => {
        if (msg.type() !== "error" && msg.type() !== "warning") return;
        const text = msg.text();
        // Chrome mirrors every failed request into the console as "Failed to
        // load resource", with no URL. The network guard below owns that class
        // of failure and names the endpoint; leaving it here too would mean
        // declaring one expected 403 in two places, in one of which you cannot
        // say which 403 you meant.
        if (/^Failed to load resource/.test(text)) return;
        // React key and prop-type warnings are findings here, not noise.
        if (msg.type() === "warning" && !/react|key|prop/i.test(text)) return;
        consoleErrors.push(`${msg.type()}: ${text}`);
      });
      page.on("pageerror", (err) => consoleErrors.push(`pageerror: ${err.message}`));

      // Loading any page while signed out fires the session probe - `GET
      // /api/auth/me` 401, then `POST /api/auth/refresh` 400 - and every spec
      // starts signed out, so those are the app working, not a finding. They
      // are forgiven only until a login succeeds: the same 401 *after* someone
      // has signed in means the session was dropped, which is a real defect and
      // stays a failure.
      let signedIn = false;

      page.on("response", (res) => {
        const method = res.request().method();
        const url = res.url();
        const status = res.status();
        seen.push({ method, url, status });

        if (method === "POST" && /\/api\/auth\/login/.test(url) && status < 400) signedIn = true;
        if (status < 400) return;
        if (!signedIn && /\/api\/auth\/(me|refresh)$/.test(url)) return;

        badResponses.push(`${status} ${method} ${url}`);
      });

      await use({
        allowConsole: (pattern, reason) => {
          expect(reason, "an allowed console line needs a reason").toBeTruthy();
          allowedConsole.push(pattern);
        },
        allowResponse: (pattern, reason) => {
          expect(reason, "an allowed failing response needs a reason").toBeTruthy();
          allowedResponses.push(pattern);
        },
        requests: () => seen,
      });

      // Teardown asserts. A test that passed its own assertions and left the
      // console red has not passed - that is the shape of half the defects
      // per-issue QA has caught in this codebase.
      if (testInfo.status !== testInfo.expectedStatus) return; // already failing; do not pile on

      const leakedConsole = consoleErrors.filter((l) => !allowedConsole.some((p) => p.test(l)));
      const leakedResponses = badResponses.filter((l) => !allowedResponses.some((p) => p.test(l)));

      expect(leakedConsole, "console errors during this flow").toEqual([]);
      expect(leakedResponses, "failed requests during this flow").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

/**
 * Log in through the real form, as the real user. A Playwright context starts
 * with no cookies, so this is a fresh session by construction - `superadmin`
 * bypasses the RBAC matrix and proves nothing about what a store user sees, so
 * reach for it only when the flow genuinely is break-glass.
 */
export async function loginAs(page: Page, role: RoleKey): Promise<void> {
  const { username, password } = ROLES[role];
  await page.goto("/");
  await page.getByTestId("login-username").fill(username);
  await page.getByTestId("login-password").fill(password);
  await page.getByTestId("login-submit").click();
  await expect(
    page.getByTestId("login-form"),
    `login failed for ${username} - check the seed has run`,
  ).toBeHidden();
}

/** Assert a locator renders money the Indian way, never raw paise. */
export async function expectMoney(locator: Locator): Promise<void> {
  const text = (await locator.innerText()).trim();
  expect(text, `"${text}" is not Indian-format money`).toMatch(INDIAN_MONEY);
}

/**
 * Run an action and assert it actually called the API. A button wired to
 * nothing is the most common silent failure on these screens, and it looks
 * identical to a working button in a screenshot.
 */
export async function expectCall(
  page: Page,
  urlPattern: RegExp,
  action: () => Promise<void>,
): Promise<number> {
  const waiting = page.waitForResponse((r) => urlPattern.test(r.url()));
  await action();
  const res = await waiting;
  return res.status();
}

/** What the receipt iframe was asked to print, thanks to the init script above. */
export async function receiptsPrinted(page: Page): Promise<string[]> {
  return page.evaluate(() => (window as unknown as { __printed: string[] }).__printed ?? []);
}

/**
 * Screenshot the end state of a flow and attach it to the report. Attach, never
 * paste: a screenshot in an agent's transcript is the most expensive thing this
 * phase can do to its context, and the report holds it just as well.
 */
export async function evidence(page: Page, name: string): Promise<void> {
  await test.info().attach(name, {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });
}
