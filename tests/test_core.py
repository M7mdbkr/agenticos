import tempfile
import unittest
from pathlib import Path

from personal_os import OperationsStore


class OperationsStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = OperationsStore(self.root / "ops.db", self.root / "uploads", self.root / "profiles")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_bootstrap_creates_required_agents_with_independent_models(self):
        agents = {a["slug"]: a for a in self.store.list_agents()}
        self.assertEqual({"ceo", "job", "dad", "tech-news"}, set(agents))
        self.store.update_agent("job", {"model_provider": "ollama", "model_id": "qwen3:8b"})
        updated = {a["slug"]: a for a in self.store.list_agents()}
        self.assertEqual("qwen3:8b", updated["job"]["model_id"])
        self.assertNotEqual("qwen3:8b", updated["ceo"]["model_id"])

    def test_each_agent_has_separate_chat_and_ceo_can_address_specialist(self):
        self.store.add_message("job", "user", "Find graduate roles")
        self.store.add_message("dad", "user", "Check the website inbox")
        self.store.add_message("ceo", "user", "@job summarize your queue", target_agent="job")
        self.assertEqual(1, len(self.store.messages("job")))
        self.assertEqual("job", self.store.messages("ceo")[0]["target_agent"])
        self.assertNotIn("website", self.store.messages("job")[0]["content"])

    def test_approval_is_bound_to_exact_action_and_edit_invalidates_it(self):
        action = self.store.create_action("job", "send_email", {"to": "jobs@example.invalid", "body": "draft"})
        self.store.decide_action(action["id"], "approved")
        self.assertEqual("approved", self.store.get_action(action["id"])["status"])
        edited = self.store.edit_action(action["id"], {"to": "jobs@example.invalid", "body": "changed"})
        self.assertEqual("pending", edited["status"])
        self.assertNotEqual(action["digest"], edited["digest"])

    def test_editable_resources_and_job_sources_are_persisted(self):
        tool = self.store.create_resource("tools", {"name": "CV reader", "description": "Reads uploaded CV files", "enabled": True})
        source = self.store.create_resource("job_sources", {"name": "Graduate careers", "kind": "website", "url": "https://example.invalid/jobs", "enabled": True})
        account = self.store.create_resource("email_accounts", {"name": "Applications", "address": "m@example.invalid", "provider": "gmail", "enabled": False})
        self.assertEqual(tool["id"], self.store.list_resources("tools")[0]["id"])
        self.assertEqual(source["url"], self.store.list_resources("job_sources")[0]["url"])
        self.assertFalse(self.store.list_resources("email_accounts")[0]["enabled"])
        self.assertEqual(account["address"], "m@example.invalid")

    def test_upload_is_sanitized_and_registered(self):
        record = self.store.save_upload("job", "../My CV.pdf", b"safe bytes")
        self.assertEqual("My_CV.pdf", record["stored_name"])
        self.assertTrue((self.root / "uploads" / record["stored_name"]).exists())

    def test_news_item_generates_a_repeatable_tiktok_script(self):
        item = self.store.add_news_item("A small AI model launches", "A local model can run on laptops.", "https://example.invalid/story")
        first = self.store.generate_script(item["id"])
        second = self.store.generate_script(item["id"])
        self.assertEqual(first["script"], second["script"])
        self.assertIn("Hook", first["script"])
        self.assertIn("Source", first["script"])

    def test_browser_profile_is_scoped_to_agent(self):
        job = self.store.browser_profile("job")
        dad = self.store.browser_profile("dad")
        self.assertNotEqual(job["profile_dir"], dad["profile_dir"])
        self.assertTrue(Path(job["profile_dir"]).exists())


if __name__ == "__main__":
    unittest.main()
