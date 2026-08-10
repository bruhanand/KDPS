import { describe, expect, it, vi } from "vitest";

import { api } from "../lib/api";
import { loadBooksHealth } from "./Home";

vi.mock("../lib/api", () => ({
  api: { get: vi.fn() },
}));

describe("the Books Health card's fetch gate (#236)", () => {
  it("never asks finledger/health for a role without money read", () => {
    const onLoaded = vi.fn();
    const onDenied = vi.fn();

    loadBooksHealth(false, onLoaded, onDenied);

    expect(api.get).not.toHaveBeenCalled();
    expect(onLoaded).not.toHaveBeenCalled();
    expect(onDenied).not.toHaveBeenCalled();
  });

  it("still asks finledger/health for a money-capable role", () => {
    vi.mocked(api.get).mockResolvedValue({ data: { balanced: true } });
    const onLoaded = vi.fn();
    const onDenied = vi.fn();

    loadBooksHealth(true, onLoaded, onDenied);

    expect(api.get).toHaveBeenCalledWith("/finledger/health");
  });
});
