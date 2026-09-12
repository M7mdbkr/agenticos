"""Offline adapter tests: these never invoke a subscription model."""
import importlib.util
import json
import subprocess
import unittest
from unittest import mock


class ProviderStatusTests(unittest.TestCase):
    def test_subscription_status_uses_sanitized_cli_auth_and_hides_identity(self):
        import brains
        outcomes = [subprocess.CompletedProcess([], 0, "", "Logged in using ChatGPT\n"),
                    subprocess.CompletedProcess([], 0, json.dumps({"loggedIn": True,
                        "authMethod": "claude.ai", "subscriptionType": "pro",
                        "email": "private@example.invalid", "apiKey": "private-token"}), "")]
        with mock.patch.object(brains, "_executable", return_value="/safe/cli"), \
             mock.patch.object(brains, "_ollama_status", return_value={
                 "installed": True, "authenticated": True, "note": "Local server OK"}), \
             mock.patch.object(brains, "_run", create=True, side_effect=outcomes):
            statuses = brains.provider_status()
        self.assertTrue(all(s["authenticated"] for s in statuses.values()))
        self.assertNotIn("private", json.dumps(statuses))
        for status in statuses.values():
            self.assertEqual(set(status), {"installed", "authenticated", "note"})

    def test_missing_clis_have_only_public_status_fields(self):
        self.assertIsNotNone(importlib.util.find_spec("brains"), "brains adapter must exist")
        import brains
        with mock.patch.object(brains, "_executable", return_value=None), \
             mock.patch.object(brains, "_ollama_status", return_value={"installed": False, "authenticated": False, "note": "Not running"}):
            statuses = brains.provider_status()
        self.assertEqual(set(statuses), {"codex-cli", "claude-code", "ollama"})
        for status in statuses.values():
            self.assertEqual(set(status), {"installed", "authenticated", "note"})
            self.assertIs(status["installed"], False)
            self.assertIs(status["authenticated"], False)
            self.assertTrue(status["note"])


class ReplyTests(unittest.TestCase):
    def test_history_is_bounded_to_own_agent_recent_messages_and_characters(self):
        import brains
        history = [{"role": "user", "content": "old-" + str(i), "agent_slug": "job"}
                   for i in range(45)]
        history += [{"role": "system", "content": "secret-system"},
                    {"role": "user", "content": "other-agent-secret", "agent_slug": "dad"},
                    {"role": "tool", "content": "secret-tool"},
                    {"role": "user", "content": "latest"}]
        system, prompt = brains._prompt({"slug": "job"}, history)
        records = json.loads(prompt)
        self.assertLessEqual(len(records), 40)
        self.assertNotIn("other-agent-secret", prompt)
        self.assertNotIn("secret-system", prompt)
        self.assertNotIn("secret-tool", prompt)
        self.assertEqual(records[-1]["content"], "latest")
        self.assertNotIn("old-0", prompt)
        huge = [{"role": "user", "content": "x" * 40000},
                {"role": "assistant", "content": "y" * 40000},
                {"role": "user", "content": "latest"}]
        _, prompt = brains._prompt({"slug": "job"}, huge)
        self.assertLessEqual(sum(len(m["content"]) for m in json.loads(prompt)), 60000)
        self.assertEqual(json.loads(prompt)[-1]["content"], "latest")

    def test_codex_one_turn_read_only_has_no_external_capabilities(self):
        import brains
        import tempfile
        calls = []
        events = [{"type": "thread.started", "thread_id": "private-session"},
                  {"type": "turn.started"},
                  {"type": "item.completed", "item": {"type": "agent_message",
                    "id": "item_0", "text": "A genuine model draft"}},
                  {"type": "turn.completed", "usage": {"input_tokens": 3}}]
        def run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess([], 0,
                "Logged in using ChatGPT\n" if command[-2:] == ["login", "status"]
                else "\n".join(json.dumps(e) for e in events), "")
        with tempfile.TemporaryDirectory() as root, \
             mock.patch.object(brains, "_executable", return_value="/safe/codex"), \
             mock.patch.object(brains, "_run", side_effect=run):
            result = brains.reply({"slug": "job", "model_provider": "codex-cli",
                "model_id": "requested-model"}, [{"role": "user", "content": "Draft"}], root)
        self.assertEqual(result, {"content": "A genuine model draft", "runtime": "codex-cli",
                                  "model": "requested-model"})
        command, kwargs = calls[-1]
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ignore-rules", command)
        self.assertIn("--ephemeral", command)
        self.assertIn("--skip-git-repo-check", command)
        self.assertNotIn("--strict-config", command)
        self.assertEqual(command[-1], "-")
        for flag, value in (("-a", "never"), ("--sandbox", "read-only"),
                            ("--model", "requested-model")):
            self.assertEqual(command[command.index(flag) + 1], value)
        disabled = {command[i+1] for i, v in enumerate(command) if v == "--disable"}
        self.assertTrue({"shell_tool", "unified_exec", "apps", "hooks", "plugins",
            "remote_plugin", "browser_use", "browser_use_external", "computer_use",
            "multi_agent", "multi_agent_v2", "memories",
            "image_generation", "view_image", "skill_search", "skill_mcp_dependency_install",
            "workspace_dependencies", "shell_snapshot", "shell_snapshot_v2",
            "external_agent_memory_import", "in_app_browser", "in_app_local_automation",
            "request_permissions_tool", "tool_suggest", "goals", "chronicle",
            "deferred_executor", "realtime_conversation", "unbounded_connection_retries"} <= disabled)
        configs = {command[i+1] for i, v in enumerate(command) if v == "--config"}
        self.assertTrue({'model_provider="openai"',
            'web_search="disabled"', 'mcp_servers={}', 'notify=[]', 'project_doc_max_bytes=0',
            'skills.include_instructions=false', 'skills.bundled.enabled=false',
            'agents.enabled=false', 'memories.generate_memories=false',
            'memories.use_memories=false', 'memories.dedicated_tools=false',
            'history.persistence="none"', 'tools.update_plan.enabled=false',
            'tools.experimental_request_user_input.enabled=false',
            'include_environment_context=false', 'include_apps_instructions=false',
            'suppress_unstable_features_warning=true',
            'features.skip_host_skill_discovery=true',
            'shell_environment_policy.inherit="none"'} <= configs)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertEqual(kwargs["timeout"], 120)

    def test_brain_error_never_contains_private_fields(self):
        import brains
        for msg in ("The brain timed out. Try again; no fallback provider was used.",
                    "The brain CLI failed. Check subscription login, limits and model configuration.",
                    "Configure this agent's brain with Codex CLI or Claude Code subscription login.",
                    "Configure this agent's brain; this runtime is not ready."):
            err = brains.BrainError(msg)
            serialized = json.dumps({"error": str(err)})
            for field in ("token", "key", "email", "api", "secret", "credential", "auth"):
                self.assertNotIn(field, serialized.lower(),
                                 f"Error message must not leak auth fields: {msg}")

    def test_claude_one_turn_isolated_no_tools_returns_real_result(self):
        import brains
        self.assertTrue(callable(getattr(brains, "reply", None)), "reply adapter must exist")
        import tempfile
        from pathlib import Path
        agent = {"slug": "job", "name": "Job helper", "purpose": "Career drafts",
                 "system_prompt": "Be succinct.", "model_provider": "claude-code",
                 "model_id": "default", "enabled": True}
        messages = [{"role": "user", "content": "Draft a greeting", "agent_slug": "job"}]
        calls = []
        def run(command, **kwargs):
            calls.append((command, kwargs))
            if command[-2:] == ["auth", "status"]:
                return subprocess.CompletedProcess([], 0, json.dumps({"loggedIn": True,
                    "authMethod": "claude.ai", "subscriptionType": "pro"}), "")
            self.assertTrue(Path(kwargs["cwd"]).is_dir())
            self.assertEqual(list(Path(kwargs["cwd"]).iterdir()), [])
            return subprocess.CompletedProcess([], 0, json.dumps({"type": "result",
                "subtype": "success", "is_error": False, "result": "Hello from the model",
                "modelUsage": {"claude-observed": {}}}), "")
        with tempfile.TemporaryDirectory() as root, \
             mock.patch.object(brains, "_executable", return_value="/safe/claude"), \
             mock.patch.object(brains, "_run", side_effect=run):
            result = brains.reply(agent, messages, root)
            self.assertEqual(list(Path(root).iterdir()), [])
        self.assertEqual(result, {"content": "Hello from the model", "runtime": "claude-code",
                                  "model": "claude-observed"})
        command, kwargs = calls[-1]
        for flag in ("--safe-mode", "--restricted", "--strict-mcp-config", "--no-chrome",
                     "--disable-slash-commands", "--no-session-persistence"):
            self.assertIn(flag, command)
        for flag, value in (("--tools", ""), ("--setting-sources", ""),
                            ("--max-turns", "1"), ("--permission-mode", "dontAsk"),
                            ("--mcp-config", '{"mcpServers":{}}')):
            self.assertEqual(command[command.index(flag) + 1], value)
        self.assertNotIn("--bare", command)
        self.assertNotIn("--model", command)
        self.assertNotIn("--fallback-model", command)
        self.assertIn("Job helper", command[command.index("--system-prompt") + 1])
        self.assertIn("Career drafts", command[command.index("--system-prompt") + 1])
        self.assertIn("Draft a greeting", kwargs["input_text"])
        self.assertNotIn("Draft a greeting", " ".join(command))
        self.assertEqual(kwargs["timeout"], 120)


if __name__ == "__main__":
    unittest.main()
