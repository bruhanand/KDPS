/** What the top-bar switcher offers this person (issue #88).
 *
 *  Pure, so the rule that matters — *the client never infers scope* — can be
 *  asserted directly. Everything here reads the authenticated-user payload:
 *  which units, whether a network view exists, and whether this person picks
 *  units at all (a brand manager picks brands, because their scope cuts across
 *  every store). Nothing is derived from the role code.
 *
 *  Fail-closed by construction: no units and no network view ⇒ no options, and
 *  the switcher renders as a locked label. There is no path from an empty
 *  payload to "All stores".
 */

import type { Brand, Store, User } from "../auth/AuthContext";

export type SwitcherOption =
  | { kind: "all-units"; label: string; chip: string }
  | { kind: "unit"; label: string; chip: string; store: Store }
  | { kind: "all-brands"; label: string; chip: string }
  | { kind: "brand"; label: string; chip: string; brand: Brand };

export interface SwitcherModel {
  mode: "units" | "brands";
  /** Nothing to choose between — render a plain label, not a menu. */
  locked: boolean;
  label: string;
  chip: string;
  options: SwitcherOption[];
}

const NO_UNIT = "No unit assigned";
const NO_BRAND = "No brand assigned";

function unitOption(store: Store): SwitcherOption {
  return {
    kind: "unit",
    label: `${store.code} · ${store.name}`,
    chip: store.state_name,
    store,
  };
}

function brandOption(brand: Brand): SwitcherOption {
  return { kind: "brand", label: brand.name, chip: "Brand", brand };
}

function unitsModel(user: User, active: Store | null): SwitcherModel {
  const units = user.business_units ?? user.stores ?? [];
  // An "all" option means "no single unit" — which is what the server already
  // answers when no unit is sent, so it is exactly this person's own scope.
  // Worth offering whenever there is more than one unit to aggregate; only the
  // network-wide grant may call it the network.
  const network = Boolean(user.all_business_units);
  const aggregate = network || units.length > 1;
  const allLabel = network ? "All stores (network)" : "All my stores";
  const options: SwitcherOption[] = [
    ...(aggregate
      ? [{ kind: "all-units" as const, label: allLabel, chip: network ? "Both states" : "All mine" }]
      : []),
    ...units.map(unitOption),
  ];
  const label = active ? `${active.code} · ${active.name}` : options.length ? allLabel : NO_UNIT;
  return {
    mode: "units",
    // One option is not a choice: a store person sees their store, full stop.
    locked: options.length <= 1,
    label,
    chip: active ? active.state_name : options.length ? "Network" : "None",
    options,
  };
}

function brandsModel(user: User, active: Brand | null): SwitcherModel {
  const brands = user.assigned_brands ?? [];
  const options: SwitcherOption[] =
    brands.length > 1
      ? [
          { kind: "all-brands", label: "All my brands", chip: "Brands" },
          ...brands.map(brandOption),
        ]
      : brands.map(brandOption);
  const label = active ? active.name : brands.length ? "All my brands" : NO_BRAND;
  return {
    mode: "brands",
    locked: options.length <= 1,
    label,
    chip: brands.length ? "Brand" : "None",
    options,
  };
}

export function switcherModel(
  user: User,
  activeStore: Store | null,
  activeBrand: Brand | null,
): SwitcherModel {
  return user.business_unit_mode === "brands"
    ? brandsModel(user, activeBrand)
    : unitsModel(user, activeStore);
}

/** Chip colour class, matching the states the business actually operates in. */
export function chipClass(chip: string): string {
  if (chip === "Bihar") return "chip-amber";
  if (chip === "Jharkhand") return "chip-blue";
  return "chip-navy";
}

/** Key that changes whenever the working context changes — the shell remounts
 *  the page on it, so every screen refetches under the new unit instead of
 *  showing the previous one's numbers. */
export function contextKey(activeStore: Store | null, activeBrand: Brand | null): string {
  return `${activeStore?.code ?? "all"}|${activeBrand?.code ?? "all"}`;
}
