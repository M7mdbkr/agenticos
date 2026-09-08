"""Backend HTTP checks; these never invoke a live model or user database."""
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server
from personal_os import OperationsStore


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="personal-os-http-")
        root = Path(self.temp.name)
        self.store = OperationsStore(root / "db.sqlite", root / "uploads", root / "profiles")
        self.patch = patch.object(server, "STORE", self.store)
        self.patch.start()
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:%s" % self.http.server_port

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        self.patch.stop()
        self.store.close()
        self.temp.cleanup()

    def request(self, path, data=None, headers=None):
        body = json.dumps(data).encode() if data is not None else None
        req = Request(self.url + path, data=body, headers={"Content-Type": "application/json", **(headers or {})})
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
            return response.status, raw

    def test_private_source_is_not_served_as_static_content(self):
        code, _ = self.request("/server.py")
        self.assertEqual(404, code)

    def test_cross_origin_requests_cannot_trigger_work(self):
        code, _ = self.request("/api/resources/tasks", {"name": "Untrusted"}, {"Origin": "https://example.invalid"})
        self.assertEqual(403, code)
        self.assertEqual([], self.store.list_resources("tasks"))

    def test_unconfigured_brain_does_not_write_a_canned_reply(self):
        code, _ = self.request("/api/agents/ceo/messages", {"content": "Hello"})
        self.assertEqual(503, code)
        self.assertEqual([], self.store.messages("ceo"))


if __name__ == "__main__":
    unittest.main()
