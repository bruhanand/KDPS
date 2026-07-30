// The manager's PIN, checked with the line down (#182, D10 §4, grill Q1).
//
// A cashier keys in a discount past the cap, or offers a credit note this
// counter has never heard of. Both need a manager's OK, and the counter is
// offline - so the OK is verified here, on the device, against the hash that
// came down in the dataset (`managers[].till_pin_hash`).
//
// Three things about that are not obvious.
//
// **It is PBKDF2-SHA256 because that is what a browser has.** The project hashes
// passwords with bcrypt, which is the better choice for a secret checked on a
// server and the wrong one here: the Web Crypto API has PBKDF2 and no bcrypt, so
// a bcrypt hash would need a bcrypt implementation shipped to the shop floor. The
// server hashes counter PINs with `PBKDF2PasswordHasher` for exactly this reason
// (`accounts/till_pin.py`), and the iteration count is read out of the string, so
// raising it there needs nothing here.
//
// **Anything it cannot verify is a no.** A hash in an algorithm this does not
// know, a malformed one, a browser with no `crypto.subtle` (an insecure origin) -
// all of them answer "not authorised". The alternative shape, "if we cannot check
// it, allow it", is a cap anybody can lift by breaking the check.
//
// **A four-digit PIN is a weak secret and is meant to be.** What makes it worth
// having is not that it cannot be guessed but that using it leaves a name and a
// time on a bill that a person has to answer for the next morning. The device it
// sits on already holds the store's whole price list; treating the PIN as the
// thing standing between an attacker and the money would be the wrong reading of
// what it is for.

import type { TillManager } from "./types";

/** The one hash format the counter can read - Django's `PBKDF2PasswordHasher`. */
const ALGORITHM = "pbkdf2_sha256";

/** Who authorised something, as the bill will carry it. */
export interface Authorisation {
  user_id: number;
  name: string;
  /** What they were shown and agreed to - `over_cap_discount`, `credit_note`.
   *
   *  A set rather than a word, because a manager authorises *what is on the bill
   *  when they type the PIN*. A cashier who then keys in an over-cap discount has
   *  produced a second exception nobody has seen, and an authorisation that
   *  covered it retrospectively would be the manager's name on something they
   *  never looked at. `covers` is where that is enforced. */
  kinds: string[];
  /** The moment the PIN was accepted, which is not Save & Print. */
  at: string;
}

/** Does this authorisation actually cover everything the bill now needs? */
export function covers(authorisation: Authorisation | null, needed: string[]): boolean {
  if (!needed.length) return true;
  if (!authorisation) return false;
  return needed.every((kind) => authorisation.kinds.includes(kind));
}

/**
 * Does `pin` belong to `manager`?
 *
 * False for every failure, deliberately and without distinguishing them: a
 * modal that said "no such algorithm" rather than "wrong PIN" would be telling
 * whoever is standing there which of the two to attack.
 */
export async function verifyPin(manager: TillManager, pin: string): Promise<boolean> {
  const parsed = parseHash(manager.till_pin_hash);
  if (!parsed || !pin) return false;
  const derived = await derive(pin, parsed.salt, parsed.iterations);
  return derived !== null && sameSecret(derived, parsed.digest);
}

/** The first manager on the cached list whose PIN this is, or null.
 *
 *  The counter types a PIN and not a name: at a busy till the manager reaches
 *  over the cashier's shoulder, and asking them to find themselves in a dropdown
 *  first is a step for the sake of the database. Which of them it was is then a
 *  fact the PIN establishes, and the bill records it. */
export async function whoAuthorised(
  managers: TillManager[],
  pin: string,
  kinds: string[],
  now: Date = new Date(),
): Promise<Authorisation | null> {
  for (const manager of managers) {
    if (await verifyPin(manager, pin)) {
      return {
        user_id: manager.user_id,
        name: manager.name,
        kinds: [...kinds],
        at: now.toISOString(),
      };
    }
  }
  return null;
}

interface ParsedHash {
  iterations: number;
  salt: string;
  digest: Uint8Array;
}

function parseHash(encoded: string): ParsedHash | null {
  const parts = (encoded || "").split("$");
  if (parts.length !== 4) return null;
  const [algorithm, iterations, salt, digest] = parts;
  const rounds = Number(iterations);
  if (algorithm !== ALGORITHM || !salt || !Number.isInteger(rounds) || rounds < 1) return null;
  const bytes = fromBase64(digest);
  return bytes && bytes.length ? { iterations: rounds, salt, digest: bytes } : null;
}

async function derive(pin: string, salt: string, iterations: number): Promise<Uint8Array | null> {
  const subtle = globalThis.crypto?.subtle;
  // No `subtle` means a page served over plain http from something that is not
  // localhost. A till is a PWA on https by construction, so this is a developer
  // on a stray origin rather than a counter - and the honest answer to "I cannot
  // check this" is still no.
  if (!subtle) return null;
  const encoder = new TextEncoder();
  const key = await subtle.importKey("raw", encoder.encode(pin), "PBKDF2", false, ["deriveBits"]);
  const bits = await subtle.deriveBits(
    { name: "PBKDF2", salt: encoder.encode(salt), iterations, hash: "SHA-256" },
    key,
    // Django's PBKDF2 hasher derives one SHA-256 digest: 32 bytes, 256 bits.
    256,
  );
  return new Uint8Array(bits);
}

/** Compare in constant time. The timing of a PIN check at a counter is not a
 *  realistic attack, and writing the comparison the other way is the habit that
 *  eventually gets applied to something where it is. */
function sameSecret(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let difference = 0;
  for (let i = 0; i < a.length; i += 1) difference |= a[i] ^ b[i];
  return difference === 0;
}

function fromBase64(text: string): Uint8Array | null {
  try {
    const binary = atob(text);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytes;
  } catch {
    return null;
  }
}
