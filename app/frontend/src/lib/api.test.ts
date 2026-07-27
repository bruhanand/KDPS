// What a refused request actually says on screen.
//
// The server writes these sentences for the person reading them — a floor rule
// they just hit, a threshold they just broke. Losing one to a generic fallback
// is worse than showing nothing, because it tells the user to "try again" on a
// request that will be refused every time.
import { describe, expect, it } from "vitest";

import { apiErrorMessage } from "./api";

function refusal(data: unknown) {
  return { response: { data } };
}

describe("apiErrorMessage", () => {
  it("shows the sentence a view or permission refused with", () => {
    expect(apiErrorMessage(refusal({ detail: "Only Owner or IT Admin may propose changes." }))).toBe(
      "Only Owner or IT Admin may propose changes.",
    );
  });

  it("shows a serializer's field error, which is where a floor refusal arrives", () => {
    expect(
      apiErrorMessage(
        refusal({ roles: ["Floor rule: PT inwarding is limited to Accounts or Owner."] }),
      ),
    ).toBe("Floor rule: PT inwarding is limited to Accounts or Owner.");
  });

  it("reaches a message nested under a field, not just the top level", () => {
    expect(apiErrorMessage(refusal({ lines: [{ qty: ["Must be at least 1."] }] }))).toBe(
      "Must be at least 1.",
    );
  });

  it("prefers detail over a field error when both are present", () => {
    expect(apiErrorMessage(refusal({ roles: ["field"], detail: "the one for the user" }))).toBe(
      "the one for the user",
    );
  });

  it("falls back only when the response carries no sentence at all", () => {
    expect(apiErrorMessage(refusal({ roles: [] }))).toBe("Something went wrong. Please try again.");
    expect(apiErrorMessage(new Error("network"))).toBe("Something went wrong. Please try again.");
  });
});
