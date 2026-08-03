"""Mail: isolation, tokens at rest, the connect handshake, and the sync watermark.

Mail is the first read in this system that does *not* narrow by store or brand.
Every other suite proves a store person cannot see another store's rows; here the
boundary is the *person*, and the tests below are the only thing standing between
"each of us reads our own inbox" and "anyone logged in can read the owner's mail
by trying message ids".

Five properties, each of which would be a serious incident if it broke:

1. **A message is reachable only through its own account's user.** Tested from
   the outside, through the API, with a real second user - not by asserting the
   queryset helper in isolation, because the helper being right is worth nothing
   if one view forgets to call it.
2. **A refresh token is never at rest in plain text.** Tested by reading the raw
   column, because that is what a database dump contains.
3. **A mailbox attaches only to the person who started *and* finished the
   flow.** The account-fixation case is written out as a test with two people in
   it, because that is the attack the three-step handshake exists to stop.
4. **Sync never steps over mail it has not stored.** A watermark that advances
   past an unread page, or past a message whose fetch failed, loses that mail
   permanently and silently - the failure mode with no symptom.
5. **"Read" means read at Google.** A local flag cleared after Gmail refused
   leaves the two sides different forever, because Gmail logs no history for a
   change it did not make.

Seams: the API seam, and one seam below it at :func:`mail.google._call` - the
single function every HTTP request to Google passes through. Faking there rather
than at ``gmail_get``/``exchange_code`` keeps the real status handling, the real
JSON decoding and the real ID-token checks under test. Nothing here touches the
network, so the suite is hermetic and runs offline.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import pytest
import requests
from _creds import TEST_PASSWORD
from _rbac import make_role
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from mail import crypto, google, service, state, sync
from mail.models import (
    MailAccount,
    MailAccountStatus,
    MailAttachment,
    MailMessage,
    MailOAuthFlow,
)
from masters.models import Gstin, LegalEntity

pytestmark = pytest.mark.django_db(transaction=True)

STATUS = "/api/mail/status"
CONNECT = "/api/mail/connect"
CALLBACK = "/api/mail/callback"
COMPLETE = "/api/mail/complete"
MESSAGES = "/api/mail/messages"
UNREAD = "/api/mail/unread"
SEND = "/api/mail/send"

#: Any passphrase works — crypto hashes it to Fernet's key size. Set on the
#: environment per test so the suite exercises the configured path.
TEST_KEY = "mail-suite-key-not-a-real-secret"

CLIENT_ID = "kdps-test-client.apps.googleusercontent.com"
DOMAIN = "kdps.in"


@pytest.fixture(autouse=True)
def _mail_key(monkeypatch):
    monkeypatch.setenv(crypto.KEY_ENV, TEST_KEY)


@pytest.fixture(autouse=True)
def _oauth_env(monkeypatch):
    """A configured server, so `server_ready()` is true everywhere.

    Set for every test rather than only the OAuth ones: "mail is not set up
    here" is a real answer and it would mask a genuine failure as a pass.
    """
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "https://api.kdps.test/api/mail/callback")
    monkeypatch.delenv("GOOGLE_WORKSPACE_DOMAIN", raising=False)
    monkeypatch.setenv("MAIL_FRONTEND_URL", "https://kdps.test/")


def _client(user: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


# --- a Google that never leaves the process ---------------------------------


def _b64(payload: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def id_token(
    email: str = f"asha@{DOMAIN}",
    *,
    hd: str | None = DOMAIN,
    aud: str = CLIENT_ID,
    iss: str = "https://accounts.google.com",
    expires_in: int = 3600,
    email_verified: bool = True,
) -> str:
    """A Google ID token, signature and all - except the signature.

    Legitimate: the code under test deliberately does not verify one, because
    this token only ever arrives in the body of our own authenticated HTTPS POST
    to Google's token endpoint. The claims are what it checks, so the claims are
    what the tests vary.
    """
    claims: dict[str, Any] = {
        "aud": aud,
        "iss": iss,
        "exp": int(time.time()) + expires_in,
        "email": email,
        "email_verified": email_verified,
    }
    if hd is not None:
        claims["hd"] = hd
    return f"{_b64({'alg': 'RS256'})}.{_b64(claims)}.not-a-real-signature"


def gmail_message(
    gid: str,
    *,
    subject: str = "PO confirmation",
    sender: str = "Levi's Sales <sales@levi.in>",
    labels: tuple[str, ...] = ("INBOX", "UNREAD"),
    rfc_id: str = "",
    references: str = "",
    body: str = "The order is confirmed.",
) -> dict[str, Any]:
    headers = [
        {"name": "Subject", "value": subject},
        {"name": "From", "value": sender},
        {"name": "To", "value": f"asha@{DOMAIN}"},
        {"name": "Date", "value": "Sat, 1 Aug 2026 10:00:00 +0530"},
    ]
    if rfc_id:
        headers.append({"name": "Message-ID", "value": rfc_id})
    if references:
        headers.append({"name": "References", "value": references})
    return {
        "id": gid,
        "threadId": f"thread-{gid}",
        "labelIds": list(labels),
        "snippet": body[:50],
        "payload": {
            "mimeType": "text/plain",
            "headers": headers,
            "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()},
        },
    }


class FakeResponse:
    def __init__(self, status: int = 200, payload: Any = None, text: str = "") -> None:
        self.status_code = status
        self._payload = payload
        self.text = text if text else ("" if payload is None else json.dumps(payload))
        self.content = self.text.encode()

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeGoogle:
    """Stands in for :func:`mail.google._call`, the one door to the network."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.messages: dict[str, dict[str, Any]] = {}
        self.listing: list[str] = []
        self.history_pages: list[dict[str, Any]] = []
        self.profile_history_id = "5000"
        self.token_response: dict[str, Any] = {
            "access_token": "fresh-access",
            "refresh_token": "fresh-refresh",
            "expires_in": 3600,
            "id_token": id_token(),
        }
        self.token_status = 200
        #: message id -> HTTP status to answer with instead of the message.
        self.message_faults: dict[str, int] = {}
        self.modify_status = 200
        self.modified: list[str] = []
        self.sent: list[dict[str, Any]] = []
        #: Bumped whenever /profile is asked, so a test can prove the backfill
        #: watermark was taken *before* the listing.
        self.profile_reads: list[int] = []

    # -- the seam ---------------------------------------------------------
    def __call__(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, url))
        if url == google.TOKEN_URI:
            if self.token_status >= 400:
                return FakeResponse(self.token_status, text="invalid_grant")
            return FakeResponse(200, self.token_response)
        if url == google.REVOKE_URI:
            return FakeResponse(200, {})
        if not url.startswith(google.GMAIL_API):
            raise AssertionError(f"unexpected call to {url}")
        return self._gmail(method, url[len(google.GMAIL_API) :], kwargs)

    def _gmail(self, method: str, path: str, kwargs: dict[str, Any]) -> FakeResponse:
        if path == "/profile":
            self.profile_reads.append(len(self.calls))
            return FakeResponse(200, {"historyId": self.profile_history_id})
        if path == "/history":
            return FakeResponse(200, self._history_page())
        if path == "/messages/send":
            self.sent.append(dict(kwargs.get("json") or {}))
            return FakeResponse(200, {"id": "sent-1", "threadId": "thread-sent"})
        if path.endswith("/modify"):
            gid = path.split("/")[2]
            if self.modify_status >= 400:
                return FakeResponse(self.modify_status, text="nope")
            self.modified.append(gid)
            return FakeResponse(200, {"id": gid})
        if path == "/messages" and method == "GET":
            return FakeResponse(200, {"messages": [{"id": g} for g in self.listing]})
        if path.startswith("/messages/"):
            gid = path.split("/")[2]
            fault = self.message_faults.get(gid)
            if fault:
                return FakeResponse(fault, text="refused")
            if gid not in self.messages:
                return FakeResponse(404, text="not found")
            return FakeResponse(200, self.messages[gid])
        raise AssertionError(f"unexpected Gmail path {path}")

    def _history_page(self) -> dict[str, Any]:
        if not self.history_pages:
            return {"historyId": self.profile_history_id}
        return self.history_pages.pop(0)

    # -- helpers ----------------------------------------------------------
    def hold(self, *messages: dict[str, Any]) -> None:
        for message in messages:
            self.messages[message["id"]] = message
            if message["id"] not in self.listing:
                self.listing.append(message["id"])


@pytest.fixture()
def fake_google(monkeypatch) -> FakeGoogle:
    fake = FakeGoogle()
    monkeypatch.setattr(google, "_call", fake)
    return fake


@pytest.fixture()
def entity(db):
    entity = LegalEntity.objects.create(code="ml-ent", name="Mail Entity", pan="AAACM1234C")
    Gstin.objects.create(
        gstin="10AAACM1234C1ZS", state_code="10", state_name="Bihar", legal_entity=entity
    )
    return entity


@pytest.fixture()
def two_people(entity):
    """Two ordinary KDPS logins, each with their own mailbox and one message.

    Same role, same entity, same everything: the *only* difference between them
    is which account their mail hangs off. That is deliberate — if isolation
    ever came from a role or a store rather than from identity, this fixture
    would not catch it.
    """
    role = make_role("ho_ops", "HO Ops (mail test)")

    def _person(username: str, address: str):
        user = User.objects.create_user(
            username=username, password=TEST_PASSWORD, role=role, entity=entity
        )
        account = MailAccount.objects.create(
            user=user, email_address=address, status=MailAccountStatus.CONNECTED
        )
        account.refresh_token = f"refresh-for-{username}"
        # Far-future expiry so no test can accidentally trigger a live refresh.
        account.access_token = f"access-for-{username}"
        account.access_expires_at = timezone.now() + timezone.timedelta(hours=5)
        # A watermark, so a list read takes the incremental path and not a
        # backfill — neither of which runs here, since sync is rate-limited off.
        account.history_id = "9999"
        account.last_synced_at = timezone.now()
        account.save()
        message = MailMessage.objects.create(
            account=account,
            google_id=f"g-{username}",
            thread_id=f"t-{username}",
            rfc_message_id=f"<{username}@levi.in>",
            subject=f"{username} private subject",
            from_name="Levi's Sales",
            from_email="sales@levi.in",
            snippet="Booking confirmation attached",
            body_text="secret body",
            sent_at=timezone.now(),
            is_unread=True,
            label_ids=["INBOX", "UNREAD"],
        )
        attachment = MailAttachment.objects.create(
            message=message,
            google_attachment_id="att-handle",
            filename="pt-file.xlsx",
            size_bytes=1024,
        )
        return {"user": user, "account": account, "message": message, "attachment": attachment}

    return {"asha": _person("ml_asha", "asha@kdps.in"), "ravi": _person("ml_ravi", "ravi@kdps.in")}


@pytest.fixture()
def newcomer(entity):
    """Somebody with no mailbox yet, for the connect flow to attach one to."""
    return User.objects.create_user(
        username="ml_new",
        password=TEST_PASSWORD,
        role=make_role("ho_ops_new", "HO Ops (mail connect test)"),
        entity=entity,
    )


# --- 1. isolation -----------------------------------------------------------


def test_the_list_shows_only_my_own_mail(two_people):
    """The whole feature in one assertion: Asha's list contains Asha's message
    and nothing of Ravi's, even though both rows sit in the same table."""
    response = _client(two_people["asha"]["user"]).get(MESSAGES, {"sync": "0"})
    assert response.status_code == 200
    subjects = [m["subject"] for m in response.data["messages"]]
    assert subjects == ["ml_asha private subject"]


def test_another_persons_message_is_a_404_not_a_403(two_people):
    """Ravi asks for Asha's message *by its real id*.

    404, not 403: from Ravi's side that row genuinely does not exist, and a 403
    would confirm the id is real — which is a free oracle for walking the table.
    """
    ravi = _client(two_people["ravi"]["user"])
    asha_message_id = two_people["asha"]["message"].id

    detail = ravi.get(f"{MESSAGES}/{asha_message_id}")
    assert detail.status_code == 404
    assert "secret body" not in str(detail.data)

    read = ravi.post(f"{MESSAGES}/{asha_message_id}/read")
    assert read.status_code == 404
    # And the mark-read must not have landed on somebody else's row.
    two_people["asha"]["message"].refresh_from_db()
    assert two_people["asha"]["message"].is_unread is True


def test_another_persons_attachment_cannot_be_streamed(two_people):
    """The attachment route reaches bytes through the message, so it inherits
    the same boundary — but it is a separate view and gets its own test, since
    that is exactly the kind of second door that gets left open."""
    ravi = _client(two_people["ravi"]["user"])
    asha_attachment_id = two_people["asha"]["attachment"].id
    assert ravi.get(f"/api/mail/attachments/{asha_attachment_id}").status_code == 404


def test_the_unread_badge_counts_only_my_own(two_people):
    response = _client(two_people["asha"]["user"]).get(UNREAD)
    assert response.status_code == 200
    assert response.data["unread"] == 1


def test_replying_to_another_persons_message_is_refused(two_people):
    """Send takes a `reply_to` id, which is a second path into the message table
    and therefore a second chance to forget the boundary."""
    response = _client(two_people["ravi"]["user"]).post(
        SEND,
        {"to": "vendor@example.com", "body": "hello", "reply_to": two_people["asha"]["message"].id},
        format="json",
    )
    assert response.status_code == 404


def test_mail_needs_no_section_but_does_need_a_login(two_people):
    """Mail is gated on identity alone (see views): every authenticated person
    reaches it, and an anonymous caller reaches nothing."""
    assert APIClient().get(STATUS).status_code in (401, 403)
    assert _client(two_people["asha"]["user"]).get(STATUS).status_code == 200


# --- 2. tokens at rest ------------------------------------------------------


def test_the_refresh_token_is_not_in_the_database_as_text(two_people):
    """What a leaked dump would show. Read straight from the column, bypassing
    the property, because the property is the thing under test."""
    account = two_people["asha"]["account"]
    stored = MailAccount.objects.values_list("refresh_token_enc", flat=True).get(pk=account.pk)
    assert stored
    assert "refresh-for-ml_asha" not in stored
    # And it is genuinely recoverable, not just mangled.
    assert MailAccount.objects.get(pk=account.pk).refresh_token == "refresh-for-ml_asha"


def test_a_changed_key_asks_for_a_reconnect_rather_than_exploding(two_people, monkeypatch):
    """Key rotation must degrade to "please reconnect", never to a 500 on the
    top bar of every screen."""
    monkeypatch.setenv(crypto.KEY_ENV, "a-completely-different-key")
    assert MailAccount.objects.get(pk=two_people["asha"]["account"].pk).refresh_token == ""


def test_no_endpoint_ever_serialises_a_token(two_people):
    """A belt-and-braces sweep of the two shapes that reach a browser."""
    client = _client(two_people["asha"]["user"])
    for body in (client.get(STATUS).data, client.get(MESSAGES, {"sync": "0"}).data):
        rendered = str(body)
        assert "refresh-for-" not in rendered
        assert "access-for-" not in rendered
        assert "token" not in rendered.lower()


def test_the_parked_authorization_code_is_encrypted_too(newcomer, fake_google):
    """The code is a bearer secret for the ten minutes it sits in the flow row,
    so it gets the same treatment as the refresh token."""
    returned_state = state.start(newcomer)
    APIClient().get(CALLBACK, {"code": "the-authorization-code", "state": returned_state})
    stored = MailOAuthFlow.objects.values_list("code_enc", flat=True).get(state=returned_state)
    assert stored
    assert "the-authorization-code" not in stored


# --- 3. connecting a mailbox ------------------------------------------------


def _connect(user: User, client: APIClient | None = None) -> str:
    """Walk the two steps before the last one, and return the handoff."""
    caller = client or _client(user)
    assert caller.get(CONNECT).status_code == 200
    returned_state = MailOAuthFlow.objects.get(user=user).state
    callback = APIClient().get(CALLBACK, {"code": "auth-code", "state": returned_state})
    assert callback.status_code == 302
    assert "mail=ready" in callback["Location"]
    return callback["Location"].split("mail_handoff=")[1]


def test_connecting_attaches_the_mailbox_google_named(newcomer, fake_google):
    """The success path, end to end: consent, callback, complete."""
    fake_google.hold(gmail_message("m1", subject="Welcome"))
    fake_google.token_response["id_token"] = id_token(f"r.kumar@{DOMAIN}")

    handoff = _connect(newcomer)
    done = _client(newcomer).post(COMPLETE, {"handoff": handoff}, format="json")

    assert done.status_code == 200
    assert done.data["connected"] is True
    account = MailAccount.objects.get(user=newcomer)
    # The address is the one Google named, not the KDPS username: a person may
    # sign in as `ml_new` and hold mail at `r.kumar@…`.
    assert account.email_address == f"r.kumar@{DOMAIN}"
    assert account.refresh_token == "fresh-refresh"
    assert account.status == MailAccountStatus.CONNECTED
    # And the first backfill ran, so there is mail on screen immediately.
    assert MailMessage.objects.filter(account=account, subject="Welcome").count() == 1


def test_the_callback_alone_attaches_nothing(newcomer, fake_google):
    """The redirect from Google is the step that must *not* be trusted: it can
    be handed to anybody, so it parks the code and decides nothing."""
    _connect(newcomer)
    assert not MailAccount.objects.filter(user=newcomer).exists()


def test_a_mailbox_cannot_be_pushed_onto_somebody_elses_login(two_people, newcomer, fake_google):
    """Account fixation, written out.

    The attacker starts a flow on their own login and sends the Google URL to a
    colleague. The colleague consents — their own mailbox, their own Google
    account — and lands back in KDPS signed in as themselves. The completing
    request is theirs; the flow is the attacker's; they disagree, so nothing
    attaches to either of them.
    """
    attacker = newcomer
    victim = two_people["ravi"]["user"]
    handoff = _connect(attacker)

    hijack = _client(victim).post(COMPLETE, {"handoff": handoff}, format="json")

    assert hijack.status_code == 400
    assert hijack.data["code"] == "MAIL_BAD_HANDOFF"
    # Nothing landed on the attacker either — the code is consumed by nobody.
    assert not MailAccount.objects.filter(user=attacker).exists()
    two_people["ravi"]["account"].refresh_from_db()
    assert two_people["ravi"]["account"].email_address == "ravi@kdps.in"


def test_a_handoff_works_once(newcomer, fake_google):
    """Single-use, under a row lock. A replayed handoff finds nothing."""
    handoff = _connect(newcomer)
    caller = _client(newcomer)
    assert caller.post(COMPLETE, {"handoff": handoff}, format="json").status_code == 200
    again = caller.post(COMPLETE, {"handoff": handoff}, format="json")
    assert again.status_code == 400


def test_a_state_cannot_be_claimed_twice(newcomer, fake_google):
    """Nor can the step before it. Two callbacks racing one state: the first
    claims it, the second is refused rather than minting a second handoff."""
    returned_state = state.start(newcomer)
    first = APIClient().get(CALLBACK, {"code": "auth-code", "state": returned_state})
    second = APIClient().get(CALLBACK, {"code": "auth-code", "state": returned_state})
    assert "mail=ready" in first["Location"]
    assert "mail=bad_state" in second["Location"]


def test_a_forged_state_attaches_nothing(two_people, fake_google):
    """The callback is unauthenticated by necessity, so `state` is the only
    thing tying the redirect to a flow we started. A value we never issued must
    park nothing at all."""
    before = MailAccount.objects.count()
    response = APIClient().get(CALLBACK, {"code": "whatever", "state": "not-a-state-we-issued"})
    assert response.status_code == 302
    assert "mail=bad_state" in response["Location"]
    assert MailAccount.objects.count() == before


def test_an_expired_flow_is_refused(newcomer, fake_google):
    """Ten minutes is generous for two consent screens; an hour-old state is
    somebody replaying a link out of a browser history."""
    returned_state = state.start(newcomer)
    MailOAuthFlow.objects.filter(state=returned_state).update(
        created_at=timezone.now() - timezone.timedelta(hours=1)
    )
    response = APIClient().get(CALLBACK, {"code": "auth-code", "state": returned_state})
    assert "mail=bad_state" in response["Location"]


def test_a_declined_consent_says_so_and_changes_nothing(two_people, fake_google):
    before = MailAccount.objects.count()
    response = APIClient().get(CALLBACK, {"error": "access_denied", "state": "x"})
    assert "mail=denied" in response["Location"]
    assert MailAccount.objects.count() == before


def test_a_declined_consent_burns_the_flow(newcomer, fake_google):
    """A state left alive after a refusal is a state somebody can still use."""
    returned_state = state.start(newcomer)
    APIClient().get(CALLBACK, {"error": "access_denied", "state": returned_state})
    assert not MailOAuthFlow.objects.filter(state=returned_state).exists()


# --- 3b. the Workspace domain -----------------------------------------------


def test_an_outside_mailbox_cannot_be_attached(newcomer, fake_google, monkeypatch):
    """`hd` on the consent URL only changes which accounts Google *offers*.

    A personal Gmail picked anyway comes back with no `hd` claim, and that is
    where it has to be caught — on the way in, not on the way out.
    """
    monkeypatch.setenv("GOOGLE_WORKSPACE_DOMAIN", DOMAIN)
    fake_google.token_response["id_token"] = id_token("somebody@gmail.com", hd=None)

    handoff = _connect(newcomer)
    refused = _client(newcomer).post(COMPLETE, {"handoff": handoff}, format="json")

    assert refused.status_code == 400
    assert refused.data["code"] == "MAIL_WRONG_DOMAIN"
    assert not MailAccount.objects.filter(user=newcomer).exists()


def test_an_address_outside_the_domain_is_refused_even_with_the_right_hd(
    newcomer, fake_google, monkeypatch
):
    """An account can sit in the Workspace and still send as an alias outside
    it. The address is what the screen shows over the inbox, so it is checked
    too."""
    monkeypatch.setenv("GOOGLE_WORKSPACE_DOMAIN", DOMAIN)
    fake_google.token_response["id_token"] = id_token("asha@elsewhere.com", hd=DOMAIN)

    handoff = _connect(newcomer)
    refused = _client(newcomer).post(COMPLETE, {"handoff": handoff}, format="json")
    assert refused.data["code"] == "MAIL_WRONG_DOMAIN"


def test_the_right_domain_still_connects(newcomer, fake_google, monkeypatch):
    """The other half of the pair, so the check cannot pass by refusing
    everybody."""
    monkeypatch.setenv("GOOGLE_WORKSPACE_DOMAIN", DOMAIN)
    fake_google.token_response["id_token"] = id_token(f"asha@{DOMAIN}", hd=DOMAIN)

    handoff = _connect(newcomer)
    assert _client(newcomer).post(COMPLETE, {"handoff": handoff}, format="json").status_code == 200


@pytest.mark.parametrize(
    ("token", "why"),
    [
        (id_token(aud="another-app.apps.googleusercontent.com"), "issued for another application"),
        (id_token(iss="https://accounts.evil.test"), "did not come from Google"),
        (id_token(expires_in=-60), "already expired"),
        (id_token(email_verified=False), "unverified address"),
    ],
)
def test_a_bad_id_token_connects_nothing(newcomer, fake_google, token, why):
    fake_google.token_response["id_token"] = token
    handoff = _connect(newcomer)
    refused = _client(newcomer).post(COMPLETE, {"handoff": handoff}, format="json")
    assert refused.status_code == 502, why
    assert not MailAccount.objects.filter(user=newcomer).exists()


# --- 4. tokens that expire --------------------------------------------------


def test_an_expired_access_token_is_refreshed_and_written_back(two_people, fake_google):
    """Refreshing and not saving means every request refreshes again — slow, and
    a good way to be rate-limited by Google."""
    account = two_people["asha"]["account"]
    account.access_expires_at = timezone.now() - timezone.timedelta(minutes=5)
    account.save()

    assert sync.usable_access_token(account) == "fresh-access"

    account.refresh_from_db()
    assert account.access_token == "fresh-access"
    assert account.access_expires_at > timezone.now()


def test_a_revoked_grant_asks_the_person_to_reconnect(two_people, fake_google):
    """`invalid_grant` is the one refusal a person can act on, and the only one
    that should change the account's status."""
    account = two_people["asha"]["account"]
    account.access_expires_at = timezone.now() - timezone.timedelta(minutes=5)
    account.save()
    fake_google.token_status = 400  # body says invalid_grant

    with pytest.raises(google.GoogleError):
        sync.usable_access_token(account)

    account.refresh_from_db()
    assert account.status == MailAccountStatus.NEEDS_RECONNECT


# --- 5. sync, and the watermark ---------------------------------------------


def _ready_to_sync(account: MailAccount, *, history_id: str = "") -> MailAccount:
    """Clear the rate-limit window so a sync actually runs."""
    account.history_id = history_id
    account.last_synced_at = None
    account.save()
    return account


def history_page(
    *records: dict[str, Any], next_token: str = "", history_id: str = ""
) -> dict[str, Any]:
    page: dict[str, Any] = {"history": list(records)}
    if next_token:
        page["nextPageToken"] = next_token
    if history_id:
        page["historyId"] = history_id
    return page


def added(record_id: str, message_id: str) -> dict[str, Any]:
    return {"id": record_id, "messagesAdded": [{"message": {"id": message_id}}]}


def test_a_first_backfill_takes_its_watermark_before_listing(two_people, fake_google):
    """Mail arriving *during* a backfill must land inside the next window, not
    behind it. Reading the watermark first re-reads a message at worst; reading
    it last loses one."""
    account = _ready_to_sync(two_people["asha"]["account"])
    fake_google.hold(gmail_message("m1"), gmail_message("m2"))

    assert sync.sync_account(account, force=True) == 2

    # /profile was the first Gmail call of the sync, before /messages.
    assert fake_google.profile_reads == [1]
    account.refresh_from_db()
    assert account.history_id == "5000"


def test_incremental_sync_reads_every_page_of_history(two_people, fake_google):
    """Gmail pages `users.history.list`. Stopping at page one and stamping the
    newest id anyway silently drops everything on page two, for good."""
    account = _ready_to_sync(two_people["asha"]["account"], history_id="100")
    fake_google.hold(gmail_message("m1"), gmail_message("m2"), gmail_message("m3"))
    fake_google.history_pages = [
        history_page(added("101", "m1"), next_token="page-2"),
        history_page(added("102", "m2"), next_token="page-3"),
        history_page(added("103", "m3"), history_id="103"),
    ]

    assert sync.sync_account(account, force=True) == 3

    stored = set(MailMessage.objects.filter(account=account).values_list("google_id", flat=True))
    assert {"m1", "m2", "m3"} <= stored
    account.refresh_from_db()
    assert account.history_id == "103"


def test_a_page_that_fails_leaves_the_watermark_where_it_was(two_people, fake_google):
    """The failure with no symptom: a sync that gives up halfway but stamps the
    end anyway. Page two never completed, so the watermark does not move past
    page one either — the whole window is simply re-read next time, and the
    upserts make that free."""
    account = _ready_to_sync(two_people["asha"]["account"], history_id="100")
    fake_google.hold(gmail_message("m1"))
    fake_google.message_faults["m2"] = 500
    fake_google.history_pages = [
        history_page(added("101", "m1"), next_token="page-2"),
        history_page(added("102", "m2"), history_id="102"),
    ]

    sync.sync_account(account, force=True)

    account.refresh_from_db()
    assert account.history_id == "100"
    assert account.last_sync_error
    # Page one's message did land, and re-reading it next time costs an upsert.
    assert MailMessage.objects.filter(account=account, google_id="m1").exists()


def test_a_rate_limited_message_is_asked_for_again_next_time(two_people, fake_google):
    """A 429 is not a deleted message. Treating every refusal as "gone" is how
    a throttled mail is skipped and never fetched again."""
    account = _ready_to_sync(two_people["asha"]["account"], history_id="100")
    fake_google.message_faults["m9"] = 429
    fake_google.history_pages = [history_page(added("101", "m9"), history_id="101")]

    sync.sync_account(account, force=True)

    account.refresh_from_db()
    assert account.history_id == "100"

    # Google recovers; the same window is re-read and the message lands.
    fake_google.message_faults.clear()
    fake_google.hold(gmail_message("m9"))
    fake_google.history_pages = [history_page(added("101", "m9"), history_id="101")]
    sync.sync_account(account, force=True)
    assert MailMessage.objects.filter(account=account, google_id="m9").exists()


def test_a_message_deleted_mid_sync_does_not_abandon_the_rest(two_people, fake_google):
    """The one refusal that *is* safe to skip: 404. There is nothing to come
    back for, so the other messages in the window still land."""
    account = _ready_to_sync(two_people["asha"]["account"], history_id="100")
    fake_google.hold(gmail_message("m1"))  # m-gone is deliberately not held
    fake_google.history_pages = [
        history_page(added("101", "m-gone"), added("102", "m1"), history_id="102")
    ]

    assert sync.sync_account(account, force=True) == 1

    account.refresh_from_db()
    assert account.history_id == "102"
    assert account.last_sync_error == ""


def test_an_expired_watermark_falls_back_to_a_full_reload(two_people, fake_google, monkeypatch):
    """Gmail drops a watermark that gets too old and answers 404. That is an
    instruction, not an error to put on somebody's screen."""
    account = _ready_to_sync(two_people["asha"]["account"], history_id="1")
    fake_google.hold(gmail_message("m1"))

    def history_404(method, url, **kwargs):
        if url.endswith("/history"):
            return FakeResponse(404, text="startHistoryId is too old")
        return fake_google(method, url, **kwargs)

    monkeypatch.setattr(google, "_call", history_404)

    assert sync.sync_account(account, force=True) == 1
    account.refresh_from_db()
    assert account.history_id == "5000"
    assert account.last_sync_error == ""


def test_a_stale_watermark_is_the_only_history_refusal_that_reloads(
    two_people, fake_google, monkeypatch
):
    """A 500 on /history is Google being unwell, not our watermark being old.
    Treating the two alike would re-download the mailbox on every hiccup."""
    account = _ready_to_sync(two_people["asha"]["account"], history_id="100")
    fake_google.hold(gmail_message("m1"))

    monkeypatch.setattr(
        google,
        "_call",
        lambda method, url, **kw: (
            FakeResponse(500, text="unwell")
            if url.endswith("/history")
            else fake_google(method, url, **kw)
        ),
    )

    assert sync.sync_account(account, force=True) == 0
    account.refresh_from_db()
    assert account.history_id == "100"
    assert not MailMessage.objects.filter(account=account, google_id="m1").exists()


def test_a_transport_failure_reads_as_google_being_unreachable(
    two_people, fake_google, monkeypatch
):
    """A timeout is not a 500 on somebody's top bar. It is one quiet line."""

    def timeout(method, url, **kwargs):
        raise requests.ConnectTimeout("took too long")

    monkeypatch.setattr(google, "_call", timeout)
    account = _ready_to_sync(two_people["asha"]["account"])

    assert sync.sync_account(account, force=True) == 0

    account.refresh_from_db()
    assert "Could not reach Google" in account.last_sync_error
    # Not a reconnect: nothing about the person's grant has changed.
    assert account.status == MailAccountStatus.CONNECTED


# --- 6. marking read --------------------------------------------------------


def test_marking_read_tells_google_first(two_people, fake_google):
    asha = two_people["asha"]
    response = _client(asha["user"]).post(f"{MESSAGES}/{asha['message'].id}/read")

    assert response.status_code == 200
    assert response.data["is_unread"] is False
    assert fake_google.modified == ["g-ml_asha"]
    asha["message"].refresh_from_db()
    assert asha["message"].is_unread is False
    assert "UNREAD" not in asha["message"].label_ids


def test_a_refused_mark_read_leaves_the_message_unread(two_people, fake_google):
    """Gmail logs no history for a change it did not make, so a local row
    cleared here would never be reconciled — bold on the phone, read at the
    desk, forever. Better to say it failed."""
    asha = two_people["asha"]
    fake_google.modify_status = 503

    response = _client(asha["user"]).post(f"{MESSAGES}/{asha['message'].id}/read")

    assert response.status_code == 502
    assert response.data["code"] == "MAIL_READ_FAILED"
    asha["message"].refresh_from_db()
    assert asha["message"].is_unread is True


def test_a_message_gone_from_gmail_is_settled_locally(two_people, fake_google):
    """The exception: nothing to come back for, so the row stops being unread
    rather than sticking on the badge until somebody notices."""
    asha = two_people["asha"]
    fake_google.modify_status = 404

    response = _client(asha["user"]).post(f"{MESSAGES}/{asha['message'].id}/read")

    assert response.status_code == 200
    asha["message"].refresh_from_db()
    assert asha["message"].is_unread is False


# --- 7. sending -------------------------------------------------------------


def _sent_mime(fake: FakeGoogle) -> str:
    return google.b64url_decode(fake.sent[-1]["raw"]).decode()


def test_a_new_mail_goes_out_with_the_mailbox_as_sender(two_people, fake_google):
    asha = two_people["asha"]
    response = _client(asha["user"]).post(
        SEND,
        {"to": "sales@levi.in", "subject": "Booking 41", "body": "Please confirm."},
        format="json",
    )

    assert response.status_code == 201
    mime = _sent_mime(fake_google)
    assert "To: sales@levi.in" in mime
    assert "From: asha@kdps.in" in mime
    assert "Subject: Booking 41" in mime
    # A new mail is not part of a conversation, so it carries no thread.
    assert "threadId" not in fake_google.sent[-1]


def test_a_reply_threads_on_the_rfc_message_id_not_gmails(two_people, fake_google):
    """Gmail's `google_id` is a different identifier and means nothing to the
    recipient's client. Quoting it puts the reply beside the conversation
    instead of inside it — everywhere except Gmail, which threads on threadId
    anyway and so hides the bug from us."""
    asha = two_people["asha"]
    parent = asha["message"]
    parent.rfc_references = "<start@levi.in>"
    parent.save()

    response = _client(asha["user"]).post(
        SEND, {"to": "sales@levi.in", "body": "Confirmed.", "reply_to": parent.id}, format="json"
    )

    assert response.status_code == 201
    mime = _sent_mime(fake_google)
    assert "In-Reply-To: <ml_asha@levi.in>" in mime
    # The chain is appended to, not replaced: a long vendor thread must not
    # split in two half way down.
    assert "References: <start@levi.in> <ml_asha@levi.in>" in mime
    assert parent.google_id not in mime
    assert fake_google.sent[-1]["threadId"] == parent.thread_id


def test_a_reply_to_a_message_with_no_message_id_still_sends(two_people, fake_google):
    """Some senders omit the header. Threading is lost, which is a shame; the
    reply not going at all would be worse."""
    asha = two_people["asha"]
    asha["message"].rfc_message_id = ""
    asha["message"].save()

    response = _client(asha["user"]).post(
        SEND, {"to": "sales@levi.in", "body": "ok", "reply_to": asha["message"].id}, format="json"
    )

    assert response.status_code == 201
    assert "In-Reply-To" not in _sent_mime(fake_google)


def test_a_refused_send_is_reported_not_swallowed(two_people, fake_google, monkeypatch):
    asha = two_people["asha"]

    def refuse(method, url, **kwargs):
        if url.endswith("/messages/send"):
            return FakeResponse(500, text="Gmail is unwell")
        return fake_google(method, url, **kwargs)

    monkeypatch.setattr(google, "_call", refuse)

    response = _client(asha["user"]).post(
        SEND, {"to": "sales@levi.in", "body": "hello"}, format="json"
    )
    assert response.status_code == 502
    assert response.data["code"] == "MAIL_SEND_FAILED"


def test_a_sent_mail_appears_in_sent_without_waiting_for_a_sync(two_people, fake_google):
    asha = two_people["asha"]
    fake_google.messages["sent-1"] = gmail_message("sent-1", subject="Booking 41", labels=("SENT",))

    _client(asha["user"]).post(
        SEND, {"to": "sales@levi.in", "subject": "Booking 41", "body": "x"}, format="json"
    )

    listing = _client(asha["user"]).get(MESSAGES, {"box": "sent", "sync": "0"})
    assert [m["subject"] for m in listing.data["messages"]] == ["Booking 41"]


def test_sending_without_a_recipient_is_refused_before_google(two_people, fake_google):
    response = _client(two_people["asha"]["user"]).post(SEND, {"body": "hello"}, format="json")
    assert response.status_code == 400
    assert response.data["code"] == "MAIL_NO_RECIPIENT"
    assert fake_google.sent == []


# --- 8. disconnect really disconnects ---------------------------------------


def test_disconnect_drops_the_cached_mail_too(two_people, fake_google):
    """ "Disconnect" must not leave a person's correspondence sitting in KDPS."""
    asha = two_people["asha"]
    response = _client(asha["user"]).post("/api/mail/disconnect")
    assert response.status_code == 200
    asha["account"].refresh_from_db()
    assert asha["account"].status == MailAccountStatus.DISCONNECTED
    assert asha["account"].refresh_token == ""
    assert MailMessage.objects.filter(account=asha["account"]).count() == 0
    # Ravi's mailbox is untouched by Asha's disconnect.
    assert MailMessage.objects.filter(account=two_people["ravi"]["account"]).count() == 1


# --- 9. the server that has no credentials ----------------------------------


def test_an_unconfigured_server_offers_no_connect_button(two_people, monkeypatch):
    """A button whose only outcome is "not set up on this server" is noise in a
    top bar every person in KDPS looks at all day."""
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID")
    client = _client(two_people["asha"]["user"])

    assert client.get(STATUS).data == {"configured": False, "connected": False}
    refused = client.get(CONNECT)
    assert refused.status_code == 503
    assert refused.data["code"] == "MAIL_NOT_CONFIGURED"


def test_the_service_layer_is_the_only_way_into_a_message(two_people):
    """A guard on the seam itself, not on a URL: every view reaches a message
    through this one helper, and it starts at the person."""
    asha, ravi = two_people["asha"], two_people["ravi"]
    assert list(service.messages_of(asha["user"])) == [asha["message"]]
    with pytest.raises(service.MailRefused):
        service.message_or_refuse(ravi["user"], asha["message"].id)
