"""Inbox triage: classification, drafting, and the approval gate before any send.

Nothing here reaches the network or a live model.
"""
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import inbox
import server
from personal_os import OperationsStore

INTERVIEW = ("Interview invitation — Graduate Engineer",
             "Dear Mohammad,\n\nWe would like to invite you to an interview for the Graduate "
             "Engineer position. Please share your availability for next week.\n\nBest,\nSara")
REJECTION = ("Update on your application",
             "Thank you for applying. Unfortunately, we have decided to move forward with other "
             "candidates whose experience more closely matches the role.")
ACK = ("We received your application",
       "Thank you for your application. It is under review and we will be in touch.")
ARABIC_INTERVIEW = ("دعوة لمقابلة",
                    "مرحباً محمد، نود دعوتك لإجراء مقابلة لوظيفة مهندس حاسب. أرجو إفادتنا بأوقاتك المتاحة.")


class ClassifierTests(unittest.TestCase):
    def test_decisive_rejection_wording_outranks_the_polite_opening(self):
        # Rejections almost always open with "thank you for applying"; the
        # classifier must not file them as a plain acknowledgement.
        verdict = inbox.classify(*REJECTION)
        self.assertEqual("rejection", verdict["category"])
        self.assertTrue(verdict["signals"])

    def test_interview_invitation_and_acknowledgement_are_separated(self):
        self.assertEqual("interview_invite", inbox.classify(*INTERVIEW)["category"])
        self.assertEqual("acknowledgement", inbox.classify(*ACK)["category"])

    def test_arabic_message_is_classified_and_detected_as_arabic(self):
        verdict = inbox.classify(*ARABIC_INTERVIEW)
        self.assertEqual("interview_invite", verdict["category"])
        self.assertEqual("ar", verdict["language"])

    def test_unmatched_message_is_uncategorised_with_zero_confidence(self):
        verdict = inbox.classify("Lunch?", "Are you free on Friday for shawarma")
        self.assertEqual("other", verdict["category"])
        self.assertEqual(0.0, verdict["confidence"])

    def test_company_is_read_from_the_domain_and_never_guessed_from_free_mail(self):
        self.assertEqual("Aramco", inbox.company_from_address("careers@aramco.com"))
        self.assertEqual("Sara Recruiter", inbox.company_from_address("sara@gmail.com", "Sara Recruiter"))


class DraftTests(unittest.TestCase):
    def _email(self, subject, body, address="careers@example.com"):
        verdict = inbox.classify(subject, body)
        return {"subject": subject, "body": body, "from_address": address,
                "from_name": "Sara", "company": "Example", **verdict}

    def test_draft_keeps_unknown_facts_as_visible_placeholders(self):
        draft = inbox.draft_reply(self._email(*INTERVIEW))
        self.assertIn("[", draft["body"])
        self.assertEqual("offline-template", draft["source"])
        self.assertTrue(draft["subject"].startswith("Re:"))

    def test_arabic_email_is_answered_in_arabic(self):
        draft = inbox.draft_reply(self._email(*ARABIC_INTERVIEW))
        self.assertIn("مقابلة", draft["body"])

    def test_no_reply_senders_and_pure_acknowledgements_get_no_draft(self):
        self.assertEqual("", inbox.draft_reply(self._email(*INTERVIEW, address="no-reply@example.com"))["body"])
        self.assertEqual("", inbox.draft_reply(self._email(*ACK))["body"])

    def test_model_refinement_falls_back_when_the_model_drops_placeholders(self):
        draft = inbox.draft_reply(self._email(*INTERVIEW))
        with patch("brains._ollama_reply", return_value="Sure, Tuesday at 9am works for me."):
            result = inbox.refine_with_model(draft["body"], INTERVIEW[1], "qwen2.5:7b")
        # The model invented a time and dropped the placeholder: keep the honest draft.
        self.assertEqual(draft["body"], result["body"])
        self.assertEqual("offline-template", result["source"])

    def test_model_refinement_is_kept_when_placeholders_survive(self):
        draft = inbox.draft_reply(self._email(*INTERVIEW))
        kept = "Thanks for the invitation. I am available [add two or three concrete dates and times, with your time zone]."
        with patch("brains._ollama_reply", return_value=kept):
            result = inbox.refine_with_model(draft["body"], INTERVIEW[1], "qwen2.5:7b")
        self.assertEqual(kept, result["body"])
        self.assertEqual("ollama:qwen2.5:7b", result["source"])

    def test_unreachable_model_keeps_the_offline_draft(self):
        with patch("brains._ollama_reply", side_effect=OSError("connection refused")):
            result = inbox.refine_with_model("draft text", "original", "qwen2.5:7b")
        self.assertEqual("draft text", result["body"])
        self.assertIn("unavailable", result["note"])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = OperationsStore(root / "ops.db", root / "uploads", root / "profiles")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _ingest(self, message_id="m-1"):
        return self.store.ingest_email({"message_id": message_id, "subject": INTERVIEW[0],
                                        "body": INTERVIEW[1], "from_address": "careers@example.com",
                                        "category": "interview_invite", "confidence": 0.8})

    def test_repeated_delivery_of_the_same_message_is_not_duplicated(self):
        first = self._ingest()
        second = self._ingest()
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(1, len(self.store.list_inbox()))

    def test_an_email_without_a_message_id_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.ingest_email({"subject": "x"})

    def test_a_reply_is_only_marked_sent_with_a_provider_confirmation(self):
        email = self._ingest()
        self.store.update_email(email["id"], {"status": "approved"})
        with self.assertRaises(ValueError):
            self.store.mark_email_sent(email["id"], "")
        confirmed = self.store.mark_email_sent(email["id"], "gmail-msg-42")
        self.assertEqual("sent", confirmed["status"])
        self.assertEqual("gmail-msg-42", confirmed["provider_message_id"])
        self.assertTrue(confirmed["replied_at"])

    def test_an_unapproved_reply_cannot_be_marked_sent(self):
        email = self._ingest()
        with self.assertRaises(ValueError):
            self.store.mark_email_sent(email["id"], "gmail-msg-42")

    def test_the_body_is_kept_out_of_the_audit_trail(self):
        self._ingest()
        events = [e for e in self.store.audit_events() if e["event_type"] == "inbox.received"]
        self.assertEqual(1, len(events))
        self.assertNotIn("availability for next week", json.dumps(events[0]))


class IngestEndpointTests(unittest.TestCase):
    TOKEN = "test-ingest-token"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="personal-os-inbox-")
        root = Path(self.temp.name)
        self.store = OperationsStore(root / "db.sqlite", root / "uploads", root / "profiles")
        self.patches = [patch.object(server, "STORE", self.store),
                        patch.dict(os.environ, {"AGENTICOS_INGEST_TOKEN": self.TOKEN})]
        for item in self.patches:
            item.start()
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:%s" % self.http.server_port

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        for item in reversed(self.patches):
            item.stop()
        self.store.close()
        self.temp.cleanup()

    def request(self, path, data=None, headers=None, method=None):
        body = json.dumps(data).encode() if data is not None else None
        req = Request(self.url + path, data=body, method=method,
                      headers={"Content-Type": "application/json", **(headers or {})})
        try:
            response = urlopen(req, timeout=10)
        except HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
        try:
            return response.status, json.loads(raw)
        except ValueError:
            return response.status, {}

    def authed(self, path, data=None):
        return self.request(path, data, {"X-AgenticOS-Token": self.TOKEN})

    def email_payload(self, message_id="m-1"):
        return {"message_id": message_id, "subject": INTERVIEW[0], "body": INTERVIEW[1],
                "from_address": "careers@example.com", "from_name": "Sara"}

    def test_ingest_requires_the_shared_token(self):
        code, data = self.request("/api/inbox/ingest", self.email_payload())
        self.assertEqual(401, code)
        self.assertEqual([], self.store.list_inbox())
        code, _ = self.request("/api/inbox/ingest", self.email_payload(), {"X-AgenticOS-Token": "wrong"})
        self.assertEqual(401, code)
        self.assertEqual([], self.store.list_inbox())

    def test_ingest_classifies_and_drafts_without_calling_a_model(self):
        code, data = self.authed("/api/inbox/ingest", self.email_payload())
        self.assertEqual(201, code)
        self.assertEqual("interview_invite", data["category"])
        self.assertTrue(data["drafted"])
        stored = self.store.list_inbox()[0]
        self.assertEqual("drafted", stored["status"])
        self.assertEqual("Example", stored["company"])

    def test_a_draft_with_an_unfilled_placeholder_cannot_reach_the_review_desk(self):
        _, data = self.authed("/api/inbox/ingest", self.email_payload())
        code, error = self.request(f"/api/inbox/{data['id']}/queue", {})
        self.assertEqual(400, code)
        self.assertIn("Fill in", error["error"])
        self.assertEqual([], self.store.list_actions())

    def test_approval_gates_the_reply_and_sending_needs_a_confirmation(self):
        _, ingested = self.authed("/api/inbox/ingest", self.email_payload())
        email_id = ingested["id"]
        code, queued = self.request(f"/api/inbox/{email_id}/queue",
                                    {"subject": "Re: Interview", "body": "I am available Tuesday 10:00 AST."})
        self.assertEqual(201, code)
        action_id = queued["action"]["id"]
        self.assertEqual("awaiting_approval", self.store.get_email(email_id)["status"])
        self.assertEqual("pending", self.store.get_action(action_id)["status"])

        self.request(f"/api/actions/{action_id}/decision", {"decision": "approved"})
        # Approved is not sent: no confirmation has come back yet.
        self.assertEqual("approved", self.store.get_email(email_id)["status"])

        code, sent = self.authed(f"/api/inbox/{email_id}/sent", {"provider_message_id": "gmail-99"})
        self.assertEqual(200, code)
        self.assertEqual("sent", sent["email"]["status"])

    def test_denying_the_card_leaves_the_reply_unsent(self):
        _, ingested = self.authed("/api/inbox/ingest", self.email_payload())
        email_id = ingested["id"]
        _, queued = self.request(f"/api/inbox/{email_id}/queue", {"body": "I am available Tuesday."})
        self.request(f"/api/actions/{queued['action']['id']}/decision", {"decision": "denied"})
        email = self.store.get_email(email_id)
        self.assertEqual("denied", email["status"])
        self.assertEqual("", email["provider_message_id"])

    def test_delivery_confirmation_also_requires_the_token(self):
        _, ingested = self.authed("/api/inbox/ingest", self.email_payload())
        self.store.update_email(ingested["id"], {"status": "approved"})
        code, _ = self.request(f"/api/inbox/{ingested['id']}/sent", {"provider_message_id": "forged"})
        self.assertEqual(401, code)
        self.assertEqual("approved", self.store.get_email(ingested["id"])["status"])

    def test_a_cross_origin_page_cannot_drive_the_inbox(self):
        code, _ = self.request("/api/inbox/ingest", self.email_payload(),
                               {"X-AgenticOS-Token": self.TOKEN, "Origin": "https://example.invalid"})
        self.assertEqual(403, code)
        self.assertEqual([], self.store.list_inbox())


if __name__ == "__main__":
    unittest.main()
