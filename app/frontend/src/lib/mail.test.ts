// The pure parts of the mail client: who a row is "from", and when it arrived.
//
// Both look trivial and both have a wrong answer that ships silently. The Sent
// folder showing your own name down every row is useless but not *broken*, so
// nobody files it; a date rendered in the browser's zone is off by a day on any
// device left on UTC, which is the exact trap the till already fell into.
import { describe, expect, it } from "vitest";

import {
  MAIL_CONNECT_MESSAGES,
  MAIL_FOLDERS,
  counterparty,
  fmtMailWhen,
  fmtSize,
  type MailConnectOutcome,
  type MailRow,
} from "./mail";

function row(over: Partial<MailRow> = {}): MailRow {
  return {
    id: 1,
    thread_id: "t1",
    subject: "PO confirmation",
    from_name: "Levi's Sales",
    from_email: "sales@levi.in",
    to_emails: "asha@kdps.in",
    snippet: "Attached",
    sent_at: "2026-08-02T06:00:00Z",
    is_unread: true,
    is_starred: false,
    is_sent: false,
    ...over,
  };
}

describe("who the row is about", () => {
  it("names the sender on received mail", () => {
    expect(counterparty(row())).toBe("Levi's Sales");
  });

  it("falls back to the address when a sender has no display name", () => {
    expect(counterparty(row({ from_name: "" }))).toBe("sales@levi.in");
  });

  it("names the recipient on sent mail, not yourself", () => {
    // The whole point of the helper: in Sent, "Levi's Sales" is still the
    // useful name, and it lives in to_emails there rather than from_name.
    expect(counterparty(row({ is_sent: true, to_emails: "buyer@levi.in" }))).toBe("buyer@levi.in");
  });

  it("never renders an empty cell", () => {
    expect(counterparty(row({ from_name: "", from_email: "" }))).toBe("(unknown sender)");
    expect(counterparty(row({ is_sent: true, to_emails: "" }))).toBe("(no recipient)");
  });
});

describe("when it arrived", () => {
  // Both cases use a date in the past, never "now": an assertion whose answer
  // depends on the day the suite runs is a test that passes until it doesn't.
  it("reads the clock in India, not wherever the device thinks it is", () => {
    // 06:00 UTC is 11:30 in Kolkata.
    expect(fmtMailWhen("2025-03-14T06:00:00Z")).toMatch(/11:30/);
  });

  it("dates a mail sent late in the UK evening as the next Indian day", () => {
    // 20:00 UTC on the 14th is 01:30 on the 15th in Kolkata. Calling it
    // "14 Mar" is the off-by-a-day the till hit; this pins it.
    expect(fmtMailWhen("2025-03-14T20:00:00Z")).toMatch(/15 Mar/);
  });
});

describe("attachment sizes", () => {
  it("scales to the unit a person can read", () => {
    expect(fmtSize(512)).toBe("512 B");
    expect(fmtSize(2048)).toBe("2 KB");
    expect(fmtSize(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});

describe("coming back from Google", () => {
  // Every outcome the callback can redirect with has to have something to say.
  // A missing entry would render as "undefined" in the top bar, and the one
  // most likely to be missed is `bad_state` — the refusal nobody triggers by
  // accident, which is exactly why nobody would notice it reading badly.
  const outcomes: MailConnectOutcome[] = ["ready", "denied", "no_code", "bad_state", "failed"];

  it("has a sentence for every outcome except the one that succeeded", () => {
    for (const outcome of outcomes) {
      const said = MAIL_CONNECT_MESSAGES[outcome];
      expect(said, outcome).toBeTypeOf("string");
      if (outcome !== "ready") expect(said.length, outcome).toBeGreaterThan(0);
    }
    expect(MAIL_CONNECT_MESSAGES.ready).toBe("");
  });

  it("never blames the person for a refusal the server chose", () => {
    // The state check refuses a link that was finished somewhere it was not
    // started. That is the app working, so it reads as "try again", not as an
    // error the reader did something to cause.
    expect(MAIL_CONNECT_MESSAGES.bad_state).toMatch(/connect again/i);
  });
});

describe("the folders the screen offers", () => {
  it("shows Inbox and Sent, and does not offer Unread as a place to browse", () => {
    // `unread` is a real folder for the API — it is what the popup asks for —
    // but as a tab it would be a filtered Inbox that empties as you read it.
    expect(MAIL_FOLDERS.map(([key]) => key)).toEqual(["inbox", "sent"]);
  });
});
