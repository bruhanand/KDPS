/**
 * Outbound RBAC helpers — mirrors the backend permission classes.
 *
 * OUTBOUND_WRITE_ROLES:  Can create, submit, dispatch, receive outbound docs.
 * OUTBOUND_ADMIN_ROLES:  Can also do V-flip and write-offs.
 * store_staff:           Read-only on all outbound surfaces.
 */

const OUTBOUND_WRITE_ROLES = new Set([
  "owner", "it_admin", "ho_ops", "accounts",
  "store_manager", "warehouse",
]);

const OUTBOUND_ADMIN_ROLES = new Set([
  "owner", "it_admin", "ho_ops", "accounts",
]);

export function canOutboundWrite(roleCode: string | undefined): boolean {
  if (!roleCode) return false;
  return OUTBOUND_WRITE_ROLES.has(roleCode);
}

export function canOutboundAdmin(roleCode: string | undefined): boolean {
  if (!roleCode) return false;
  return OUTBOUND_ADMIN_ROLES.has(roleCode);
}
