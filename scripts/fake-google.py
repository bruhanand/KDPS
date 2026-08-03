#!/usr/bin/env python3
"""A local stand-in for Google, so mail can be driven with no Google account.

    python3 scripts/fake-google.py            # listens on 55240

Then point the backend at it (see the commented block in app/backend/.env) and
press "Connect my mail". There is no consent screen and no network: this server
answers the six calls the mail app makes, holds a mailbox in memory, and hands
back an ID token the app will accept.

**Why a fake Google rather than a seeded mailbox.** Rows in the database look
right until the first click. Marking a message read calls Gmail, and so does
sending, replying and opening an attachment - a fixture mailbox fails all four
the moment you touch it, and the account flips to "needs reconnecting" inside a
minute. Standing in for Google instead means every path is the real one: the
three-step consent handshake, the incremental sync watermark, the label write
behind mark-as-read, the threading headers on a reply.

**It is not a mock of our own code.** The backend is unmodified except for
knowing where Google lives, and that override only works on a debug server.
What this proves is therefore worth something: if the flow works here it is
because the flow works.

Deliberately stdlib only - no dependency, no build step, no fixture files.

Faults can be turned on and off while it runs, to see the failure paths the
code review was about:

    curl "localhost:55240/__control?modify=503"    # mark-read refuses
    curl "localhost:55240/__control?message=429"   # a message fetch is throttled
    curl "localhost:55240/__control?send=500"      # sending refuses
    curl "localhost:55240/__control?reset=1"       # back to normal
"""

from __future__ import annotations

import argparse
import base64
import email
import json
import re
import time
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

# --- the mailbox ------------------------------------------------------------

#: Deliberately KDPS-shaped: brand vendors, PT files, a booking, a transfer
#: query. Generic "Lorem ipsum" test mail hides the two things this screen has
#: to cope with - long Indian brand names in the sender column, and the HTML
#: newsletters brands actually send.
SEED = [
    dict(
        sender="Levi's Sales <sales.east@levi.in>",
        subject="PO 4471 confirmed - dispatch Thursday",
        body="Dear KDPS team,\n\nPO 4471 is confirmed. 214 pieces, dispatch Thursday "
        "by Gati. PT file attached.\n\nRegards,\nSales Desk",
        unread=True,
        attachment=("PT-LEVI-4471.xlsx", "application/vnd.ms-excel"),
    ),
    dict(
        sender="Madura Fashion & Lifestyle <po.support@madura.co.in>",
        subject="Revised price list effective 1 September",
        html="<h3 style='color:#1f2d4d'>Revised price list</h3>"
        "<p>Effective <b>1 September 2026</b>, the following MRP slabs change:</p>"
        "<table border='1' cellpadding='6' style='border-collapse:collapse'>"
        "<tr><th>Category</th><th>Old</th><th>New</th></tr>"
        "<tr><td>Formal shirts</td><td>1,799</td><td>1,899</td></tr>"
        "<tr><td>Chinos</td><td>2,299</td><td>2,499</td></tr></table>"
        "<p>Please acknowledge.</p>",
        unread=True,
    ),
    dict(
        sender="Ranchi Warehouse <ran.wh@kdps.in>",
        subject="Transfer TR-88 short by 3 pieces",
        body="Counted TR-88 against the challan this morning. Three pieces short - "
        "two 38 and one 40. Flagged on the system, not blocked.\n\nSunil",
        unread=True,
    ),
    dict(
        sender="Pepe Jeans London <eastindia@pepejeans.co.in>",
        subject="EOSS 2026 - store-wise discount grid",
        body="Attached is the EOSS grid. Note Bihar and Jharkhand are on separate "
        "slabs this year.",
        attachment=("EOSS-2026-GRID.pdf", "application/pdf"),
    ),
    dict(
        sender="Gati KWE <tracking@gati.com>",
        subject="Docket 8812443 delivered",
        body="Your consignment 8812443 was delivered at PATNA on 31 July 2026 at "
        "14:22 and signed for by R KUMAR.",
    ),
    dict(
        sender="Vaishnavi Deoghar <deoghar.store@kdps.in>",
        subject="Counter 2 printer not taking the roll",
        body="Counter 2's printer jams on every third bill since morning. Billing on "
        "counter 1 for now.",
        unread=True,
    ),
    dict(
        sender="Arvind Lifestyle Brands <ho.commercial@arvind.in>",
        subject="SOR reconciliation - June",
        body="June SOR statement attached. Please confirm the returns window on the "
        "March lot; our records show it closing 15 September.",
        attachment=("SOR-JUNE-2026.xlsx", "application/vnd.ms-excel"),
    ),
    dict(
        sender="Jockey India <trade.east@jockeyindia.com>",
        subject="Replenishment order acknowledgement",
        body="Received. Shipping in two lots, the second after 10 August.",
    ),
    dict(
        sender="Bihar Commercial Taxes <noreply@biharcommercialtax.gov.in>",
        subject="GSTR-1 filing acknowledgement - 10AAACM1234C1ZS",
        body="Your GSTR-1 for the period 06/2026 has been filed. ARN "
        "AA1006260012345. No action required.",
    ),
    dict(
        sender="United Colors of Benetton <east.sales@benetton.in>",
        subject="New season lookbook",
        html="<div style='font-family:Georgia'><h2>Autumn 2026</h2>"
        "<p>The full lookbook is on the portal. Highlights for the East:</p>"
        "<ul><li>Knitwear lands 20 August</li><li>Outerwear 5 September</li></ul>"
        "<p style='color:#888;font-size:12px'>You are receiving this because you "
        "are a Benetton trade partner.</p></div>",
    ),
    dict(
        sender="Anand Kumar <anand@kdps.in>",
        subject="Weekly numbers - week 31",
        body="Sending the week 31 pack to all store managers today. Please read the "
        "dead-stock page before Monday's call.",
        labels=["SENT"],
    ),
    dict(
        sender="Blackberrys <trade@blackberrys.com>",
        subject="Booking window closes Friday",
        body="A reminder that the AW26 booking window closes on Friday. Unbooked "
        "quantities go to the general pool.",
        unread=True,
    ),
]


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _snippet(text: str) -> str:
    return " ".join(text.split())[:120]


class Mailbox:
    """Gmail's data model, as much of it as the app actually reads."""

    def __init__(self, address: str) -> None:
        self.address = address
        self.messages: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        #: Gmail's monotonic change counter. The app's incremental sync pages
        #: through these, so they have to behave like the real thing.
        self.history_id = 1000
        self.history: list[dict[str, Any]] = []
        self.next_id = 1
        for offset, seed in enumerate(SEED):
            self.add(seed, minutes_ago=37 * (offset + 1))

    # -- writing ---------------------------------------------------------
    def add(self, seed: dict[str, Any], *, minutes_ago: int = 0) -> str:
        gid = f"msg{self.next_id:04d}"
        self.next_id += 1
        labels = list(seed.get("labels") or ["INBOX"])
        if seed.get("unread"):
            labels.append("UNREAD")
        when = time.time() - minutes_ago * 60

        parts: list[dict[str, Any]] = []
        if seed.get("html"):
            parts.append(
                {"mimeType": "text/html", "body": {"data": b64(seed["html"].encode())}}
            )
        text = seed.get("body") or ""
        if text or not parts:
            parts.append(
                {"mimeType": "text/plain", "body": {"data": b64(text.encode())}}
            )
        if seed.get("attachment"):
            filename, mime = seed["attachment"]
            parts.append(
                {
                    "mimeType": mime,
                    "filename": filename,
                    "body": {"attachmentId": f"att-{gid}", "size": 20480},
                }
            )

        self.messages[gid] = {
            "id": gid,
            "threadId": seed.get("thread") or f"thread-{gid}",
            "labelIds": labels,
            # Gmail's snippet is always plain text, even for an HTML mail - it
            # strips the markup itself. Handing the list raw tags would put
            # "<h3 style=..." down the preview column and make the screen look
            # broken for a reason that is this fixture's fault, not the app's.
            "snippet": _snippet(seed.get("body") or _strip_tags(seed.get("html") or "")),
            "internalDate": str(int(when * 1000)),
            "payload": {
                "mimeType": "multipart/mixed",
                "headers": [
                    {"name": "From", "value": seed["sender"]},
                    {"name": "To", "value": self.address},
                    {"name": "Subject", "value": seed["subject"]},
                    {
                        "name": "Date",
                        "value": time.strftime(
                            "%a, %d %b %Y %H:%M:%S +0530", time.localtime(when)
                        ),
                    },
                    # Deliberately nothing like `gid`. The two identifiers are
                    # easy to confuse - that confusion is the bug this fixture
                    # exists to expose - so a reply quoting Gmail's id instead
                    # of the RFC header is unmistakable in the log.
                    {
                        "name": "Message-ID",
                        "value": seed.get("rfc_id")
                        or f"<CAF{self.next_id:03d}x7b2q@mail.sender.example>",
                    },
                ]
                + (
                    [{"name": "References", "value": seed["references"]}]
                    if seed.get("references")
                    else []
                ),
                "parts": parts,
            },
        }
        self.order.insert(0, gid)
        self._record("messagesAdded", gid)
        return gid

    def _record(self, kind: str, gid: str) -> None:
        self.history_id += 1
        self.history.append({"id": str(self.history_id), kind: [{"message": {"id": gid}}]})

    def modify(self, gid: str, add: list[str], remove: list[str]) -> None:
        labels = self.messages[gid]["labelIds"]
        self.messages[gid]["labelIds"] = [
            *[label for label in labels if label not in remove],
            *[label for label in add if label not in labels],
        ]
        self._record("labelsRemoved" if remove else "labelsAdded", gid)

    # -- reading ---------------------------------------------------------
    def since(self, start: str, page: int, size: int) -> dict[str, Any]:
        try:
            floor = int(start)
        except (TypeError, ValueError):
            floor = 0
        records = [r for r in self.history if int(r["id"]) > floor]
        window = records[page * size : (page + 1) * size]
        answer: dict[str, Any] = {"history": window, "historyId": str(self.history_id)}
        if len(records) > (page + 1) * size:
            answer["nextPageToken"] = str(page + 1)
        return answer


# --- the server -------------------------------------------------------------

FAULTS: dict[str, int] = {}
MAILBOX: Mailbox


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # -- plumbing --------------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"  fake-google  {fmt % args}")

    def reply(self, status: int, payload: Any) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode() if length else ""
        if not raw:
            return {}
        if raw.lstrip().startswith("{"):
            return dict(json.loads(raw))
        return {k: v[0] for k, v in parse_qs(raw).items()}

    # -- routes ----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}

        if url.path == "/__control":
            return self._control(query)
        if url.path == "/o/oauth2/v2/auth":
            return self._consent(query)
        if url.path == "/gmail/v1/users/me/profile":
            return self.reply(200, {"historyId": str(MAILBOX.history_id)})
        if url.path == "/gmail/v1/users/me/history":
            return self.reply(
                200,
                MAILBOX.since(
                    query.get("startHistoryId", "0"),
                    int(query.get("pageToken") or 0),
                    int(query.get("maxResults") or 200),
                ),
            )
        if url.path == "/gmail/v1/users/me/messages":
            limit = int(query.get("maxResults") or 150)
            return self.reply(
                200, {"messages": [{"id": g} for g in MAILBOX.order[:limit]]}
            )

        attachment = re.match(
            r"^/gmail/v1/users/me/messages/([^/]+)/attachments/(.+)$", url.path
        )
        if attachment:
            note = f"A stand-in attachment for {attachment.group(1)}.\n"
            return self.reply(200, {"data": b64(note.encode()), "size": len(note)})

        message = re.match(r"^/gmail/v1/users/me/messages/([^/]+)$", url.path)
        if message:
            gid = message.group(1)
            if FAULTS.get("message"):
                return self.reply(FAULTS["message"], {"error": "injected fault"})
            if gid not in MAILBOX.messages:
                return self.reply(404, {"error": "not found"})
            return self.reply(200, MAILBOX.messages[gid])

        self.reply(404, {"error": f"fake-google has no route for {url.path}"})

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        payload = self.body()

        if url.path == "/token":
            return self._token(payload)
        if url.path == "/revoke":
            return self.reply(200, {})
        if url.path == "/gmail/v1/users/me/messages/send":
            return self._send(payload)

        modify = re.match(r"^/gmail/v1/users/me/messages/([^/]+)/modify$", url.path)
        if modify:
            if FAULTS.get("modify"):
                return self.reply(FAULTS["modify"], {"error": "injected fault"})
            gid = modify.group(1)
            if gid not in MAILBOX.messages:
                return self.reply(404, {"error": "not found"})
            MAILBOX.modify(
                gid, payload.get("addLabelIds") or [], payload.get("removeLabelIds") or []
            )
            return self.reply(200, MAILBOX.messages[gid])

        self.reply(404, {"error": f"fake-google has no route for {url.path}"})

    # -- handlers --------------------------------------------------------
    def _control(self, query: dict[str, str]) -> None:
        if query.get("reset"):
            FAULTS.clear()
        for key in ("message", "modify", "send"):
            if key in query:
                FAULTS[key] = int(query[key])
        self.reply(200, {"faults": FAULTS})

    def _consent(self, query: dict[str, str]) -> None:
        """No consent screen: straight back to the callback with a code.

        The screen is the one part of this worth nobody's time to reproduce -
        it is Google's UI, we do not control a pixel of it, and what the app
        has to get right is everything that happens after it.
        """
        back = query.get("redirect_uri", "")
        state = query.get("state", "")
        target = f"{back}?{urlencode({'code': 'fake-authorization-code', 'state': state})}"
        self.send_response(302)
        self.send_header("Location", target)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _token(self, payload: dict[str, Any]) -> None:
        client_id = str(payload.get("client_id") or "")
        claims = {
            "aud": client_id,
            "iss": "https://accounts.google.com",
            "exp": int(time.time()) + 3600,
            "email": MAILBOX.address,
            "email_verified": True,
            "hd": MAILBOX.address.split("@")[-1],
        }
        # Three dots and no signature. The app does not verify one, and says
        # why: a real token only ever arrives in the body of a client-secret
        # authenticated POST, which is exactly the call being answered here.
        id_token = f"{b64(b'{}')}.{b64(json.dumps(claims).encode())}.unsigned"
        self.reply(
            200,
            {
                "access_token": f"fake-access-{int(time.time())}",
                "refresh_token": "fake-refresh-token",
                "expires_in": 3600,
                "token_type": "Bearer",
                "id_token": id_token,
            },
        )

    def _send(self, payload: dict[str, Any]) -> None:
        if FAULTS.get("send"):
            return self.reply(FAULTS["send"], {"error": "injected fault"})
        raw = payload.get("raw") or ""
        mime: Message = email.message_from_bytes(
            base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        )
        print("  fake-google  --- sent message ---")
        for header in ("To", "Cc", "Subject", "In-Reply-To", "References"):
            if mime.get(header):
                print(f"  fake-google  {header}: {mime.get(header)}")
        gid = MAILBOX.add(
            {
                "sender": MAILBOX.address,
                "subject": mime.get("Subject") or "(no subject)",
                "body": _plain_text(mime),
                "labels": ["SENT"],
                "thread": payload.get("threadId"),
                "rfc_id": f"<sent-{int(time.time())}@fake.test>",
                "references": mime.get("References") or "",
            }
        )
        # Gmail puts the recipient in To on a sent copy; the list column reads it.
        MAILBOX.messages[gid]["payload"]["headers"] = [
            h if h["name"] != "To" else {"name": "To", "value": mime.get("To") or ""}
            for h in MAILBOX.messages[gid]["payload"]["headers"]
        ]
        self.reply(200, {"id": gid, "threadId": MAILBOX.messages[gid]["threadId"]})


def _plain_text(mime: Message) -> str:
    if not mime.is_multipart():
        return str(mime.get_payload(decode=True) or b"", "utf-8", errors="replace")
    for part in mime.walk():
        if part.get_content_type() == "text/plain":
            return str(part.get_payload(decode=True) or b"", "utf-8", errors="replace")
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=55240)
    parser.add_argument(
        "--email",
        default="anand@kdps.in",
        help="The address this stand-in says consented. Its domain becomes the "
        "ID token's hd claim, so it is also what GOOGLE_WORKSPACE_DOMAIN is "
        "checked against.",
    )
    args = parser.parse_args()

    global MAILBOX
    MAILBOX = Mailbox(args.email)

    print(f"fake-google listening on http://localhost:{args.port}")
    print(f"  mailbox      {args.email} ({len(MAILBOX.order)} messages)")
    print("  set these in app/backend/.env, then restart the API:")
    print(f"    GOOGLE_AUTH_URI=http://localhost:{args.port}/o/oauth2/v2/auth")
    print(f"    GOOGLE_TOKEN_URI=http://localhost:{args.port}/token")
    print(f"    GOOGLE_REVOKE_URI=http://localhost:{args.port}/revoke")
    print(f"    GOOGLE_GMAIL_API=http://localhost:{args.port}/gmail/v1/users/me")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
