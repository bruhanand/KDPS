import { describe, expect, it } from "vitest";

import { INVENTORY_FOLD } from "../shell/navConfig";
import { PANELS } from "./Inventory";

describe("the Inventory page", () => {
  it("has a panel for every tab the sidebar offers, and no orphan panels", () => {
    // The manifest declares the tabs and this page draws them; they are joined
    // by a bare slug. A tab with no panel white-screens the person whose first
    // visible tab it is, and a panel with no tab is code nobody can reach.
    expect(Object.keys(PANELS).sort()).toEqual(INVENTORY_FOLD.tabs.map((t) => t.slug).sort());
  });
});
