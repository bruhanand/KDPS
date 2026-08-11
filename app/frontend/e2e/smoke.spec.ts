import { evidence, expect, loginAs, test } from "./kdps";

// The harness's own smoke test. It proves the four things every other spec
// leans on: the stack under test is up, a real UI login works, a Playwright
// context really does start signed out, and the console and network guards are
// armed. If this fails, no other spec's verdict means anything.
//
// It asserts nothing about any feature, deliberately - so it survives every
// feature change and stays a true check of the harness.

test("a store manager can sign in and lands on the shell", async ({ page }) => {
  await loginAs(page, "deoManager");

  await expect(page.getByTestId("app-sidebar")).toBeVisible();
  await expect(page.getByTestId("sidebar-nav")).toBeVisible();

  await evidence(page, "store-manager-landing");
});

test("a fresh context is signed out", async ({ page }) => {
  // Contexts do not share cookies, so "log out first" is structural here rather
  // than a step someone has to remember. A pass that ran as whoever happened to
  // be signed in proves nothing, and this is what makes that impossible.
  await page.goto("/");
  await expect(page.getByTestId("login-form")).toBeVisible();
});

test("a wrong password is refused", async ({ page, guard }) => {
  guard.allowResponse(/\/api\/auth\/login/, "the 401 is the flow working");

  await page.goto("/");
  await page.getByTestId("login-username").fill("deo.manager");
  await page.getByTestId("login-password").fill("definitely-not-the-password");
  await page.getByTestId("login-submit").click();

  await expect(page.getByTestId("login-error")).toBeVisible();
  await expect(page.getByTestId("login-form")).toBeVisible();
});
