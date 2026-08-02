// The counter's copy, in memory (#181).
//
// The Billing screen reads the local database once and then works out of arrays.
// That is deliberate, and it is what makes the D10 rule "lookup is local:
// instant, offline, never a spinner" true rather than aspirational: a scan
// resolves inside the same tick as the beep, and typing into the search box
// filters twenty thousand rows without touching IndexedDB per keystroke.
//
// Twenty thousand pieces is a few megabytes on a machine that does nothing else
// all day, and the alternative - a Dexie query per scan and per keystroke - puts
// an await between the scanner and the line appearing. On a counter with a queue
// of customers that await is the whole difference.
//
// It reloads when the dataset lands and after every bill, because the local
// shelf moves at Save & Print and the next scan has to read the new count.

import { useCallback, useEffect, useState } from "react";

import { META, readMeta } from "./db";
import type { TillDb } from "./db";
import { DEFAULT_POLICY } from "./sync";
import type {
  TillCreditNote,
  TillGstSlab,
  TillItem,
  TillKnownCustomer,
  TillManager,
  TillOffer,
  TillPolicy,
  TillSalesman,
  TillSeason,
  TillStock,
  TillStoreIdentity,
} from "./types";

export interface TillWorld {
  items: TillItem[];
  stock: TillStock[];
  /** The rulebook as it stood at the last sync. Read here rather than queried
   *  per line: pricing runs on every keystroke in the discount box, and an
   *  await between a scan and the offer chip is an await the counter feels. */
  offers: TillOffer[];
  seasons: TillSeason[];
  slabs: TillGstSlab[];
  salesmen: TillSalesman[];
  /** The open notes this store issued, as the last sync left them, less anything
   *  the queue has already spent (#182). Offline redemption is only ever against
   *  one of these. */
  creditNotes: TillCreditNote[];
  /** Who may authorise an exception here, with the hash their PIN is checked
   *  against. Empty until an administrator grants somebody the rung. */
  managers: TillManager[];
  /** Everybody KDPS has billed, as the last sync left them - the list the
   *  customer typeahead searches. In memory for the same reason the items are:
   *  the search runs on every keystroke in the mobile box, and an await between
   *  a digit and the suggestions is an await the counter feels. */
  customers: TillKnownCustomer[];
  policy: TillPolicy;
  store: TillStoreIdentity | null;
  /** The salesman the counter credited last, defaulted onto the next line so a
   *  busy cashier accepts it with no keystrokes at all (D10 §4). */
  lastSalesman: number | null;
  loaded: boolean;
}

const EMPTY: TillWorld = {
  items: [],
  stock: [],
  offers: [],
  seasons: [],
  slabs: [],
  salesmen: [],
  creditNotes: [],
  managers: [],
  customers: [],
  policy: DEFAULT_POLICY,
  store: null,
  lastSalesman: null,
  loaded: false,
};

/**
 * Read the whole counter into memory, and again whenever `version` changes.
 *
 * `version` is whatever the caller can point at that means "this is stale" - the
 * last sync time and the number of bills committed. A hook cannot know when
 * IndexedDB moved underneath it, so the screen says.
 */
export function useTillWorld(db: TillDb | null, version: string): TillWorld {
  const [world, setWorld] = useState<TillWorld>(EMPTY);

  const load = useCallback(async (): Promise<TillWorld> => {
    if (!db) return EMPTY;
    const [items, stock, offers, seasons, slabs, salesmen, creditNotes, managers, customers] =
      await Promise.all([
        db.items.toArray(),
        db.stock.toArray(),
        db.offers.toArray(),
        db.seasons.toArray(),
        db.gstSlabs.toArray(),
        db.salesmen.toArray(),
        db.creditNotes.toArray(),
        db.managers.toArray(),
        db.customers.toArray(),
      ]);
    return {
      items,
      stock,
      offers,
      seasons,
      slabs,
      salesmen: salesmen.filter((s) => s.is_active),
      // A note with nothing left on it stays in the cache so the counter can say
      // "there is nothing left on that note" rather than "never heard of it",
      // which is a different sentence with a different remedy.
      creditNotes,
      managers,
      customers,
      policy: await readMeta<TillPolicy>(db, META.policy, DEFAULT_POLICY),
      store: await readMeta<TillStoreIdentity | null>(db, META.store, null),
      lastSalesman: await readMeta<number | null>(db, META.lastSalesman, null),
      loaded: true,
    };
  }, [db]);

  useEffect(() => {
    let current = true;
    // A load that lost its race is dropped rather than written: two reloads can
    // overlap (a sync landing while a bill commits), and the older one finishing
    // last would put the pre-sale shelf back on the screen.
    void load().then((next) => {
      if (current) setWorld(next);
    });
    return () => {
      current = false;
    };
  }, [load, version]);

  return world;
}
