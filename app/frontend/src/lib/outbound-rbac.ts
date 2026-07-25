/**
 * Outbound write gates on the client — the same section + rung the server uses.
 *
 * These used to be two role lists mirroring two role frozensets in the backend,
 * and both drifted from the RBAC matrix in both directions (#94): Accounts got
 * write buttons on stock it may only view, and a cashier was shown a read-only
 * transfer screen the matrix says is their daily work. There is now one gate,
 * so this reads the capability the server sent rather than restating who holds
 * it — see `outbound/permissions.py` for the same table on the other side.
 *
 * Hiding a button is never the security boundary; the API refusing is. This
 * exists so a screen does not offer an action the server will reject.
 */

import type { User } from "../auth/AuthContext";
import { userCan } from "../shell/navConfig";

/** Create, submit, dispatch or receive a store transfer. */
export function canWriteTransfer(user: User | null | undefined): boolean {
  return userCan(user, "transfer", "operate");
}

/** Mark damage, and create or submit a return to brand. */
export function canWriteReturnToBrand(user: User | null | undefined): boolean {
  return userCan(user, "return_to_brand", "operate");
}

/** Create or submit a stock adjustment or a write-off. */
export function canWriteStockCount(user: User | null | undefined): boolean {
  return userCan(user, "stock_count", "operate");
}

/** Convert ownership — a V-flip relabels stock that never moves. */
export function canFlipOwnership(user: User | null | undefined): boolean {
  return userCan(user, "stock", "manage");
}
