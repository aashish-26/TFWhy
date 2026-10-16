import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tfwhy.analyzer import load_plan  # noqa: E402
from tfwhy.history import HistoryError, clear_history, list_history, save_history  # noqa: E402


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.directory, ignore_errors=True))
        self.history_path = self.directory / "history.json"

    def write_plan(self, secret="SYNTHETIC_SECRET_MARKER"):
        path = self.directory / "plan.json"
        path.write_text(json.dumps({
            "format_version": "1.0",
            "terraform_version": "1.6.0",
            "resource_changes": [{
                "address": "aws_instance.app",
                "type": "aws_instance",
                "change": {
                    "actions": ["delete", "create"],
                    "replace_paths": [["user_data"]],
                    "before": {"password": secret},
                    "after": {"password": secret},
                },
                "action_reason": "replace_because_cannot_update",
            }],
        }), encoding="utf-8")
        return path

    def test_save_is_opt_in_and_cli_history_commands_persist_safely(self):
        plan_path = self.write_plan()
        env = {"PYTHONPATH": str(ROOT / "src")}
        no_save = subprocess.run([sys.executable, "-m", "tfwhy", "explain", str(plan_path), "--history-file", str(self.history_path)], cwd=ROOT, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(no_save.returncode, 0)
        self.assertFalse(self.history_path.exists())

        saved = subprocess.run([sys.executable, "-m", "tfwhy", "explain", str(plan_path), "--save-history", "--history-file", str(self.history_path)], cwd=ROOT, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(saved.returncode, 0)
        content = self.history_path.read_text(encoding="utf-8")
        self.assertNotIn("SYNTHETIC_SECRET_MARKER", content)
        self.assertNotIn('"before"', content)
        self.assertNotIn('"after"', content)

        shown = subprocess.run([sys.executable, "-m", "tfwhy", "history", "show", "1", "--history-file", str(self.history_path), "--format", "json"], cwd=ROOT, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(shown.returncode, 0)
        self.assertIn('"id": "1"', shown.stdout)
        self.assertNotIn("SYNTHETIC_SECRET_MARKER", shown.stdout)

    def test_recurrence_is_observed_without_root_cause_claim(self):
        summary = load_plan(self.write_plan())
        save_history(summary, self.history_path)
        save_history(summary, self.history_path)
        document = list_history(self.history_path)
        replacement = document["entries"][1]["resources"][0]
        self.assertEqual(replacement["recurrence_count"], 2)
        self.assertIn("does not prove a root cause", replacement["recurrence_note"])

    def test_corrupt_history_is_refused_and_not_overwritten(self):
        self.history_path.write_text("{not-json", encoding="utf-8")
        with self.assertRaisesRegex(HistoryError, "corrupt"):
            list_history(self.history_path)
        original = self.history_path.read_text(encoding="utf-8")
        with self.assertRaisesRegex(HistoryError, "corrupt"):
            save_history(load_plan(self.write_plan()), self.history_path)
        self.assertEqual(self.history_path.read_text(encoding="utf-8"), original)

    def test_clear_requires_confirmation_and_corrupt_clear_is_explicit(self):
        self.history_path.write_text(json.dumps({"schema_version": 1, "entries": []}), encoding="utf-8")
        with self.assertRaisesRegex(HistoryError, "explicit confirmation"):
            clear_history(self.history_path)
        self.assertTrue(self.history_path.exists())
        clear_history(self.history_path, confirmed=True)
        self.assertFalse(self.history_path.exists())

        self.history_path.write_text("not json", encoding="utf-8")
        with self.assertRaisesRegex(HistoryError, "explicit confirmation"):
            clear_history(self.history_path)
        clear_history(self.history_path, confirmed=True)
        self.assertFalse(self.history_path.exists())

    def test_cli_clear_confirmation_and_corrupt_file_error(self):
        self.history_path.write_text("not json", encoding="utf-8")
        env = {"PYTHONPATH": str(ROOT / "src")}
        result = subprocess.run([sys.executable, "-m", "tfwhy", "history", "--history-file", str(self.history_path)], cwd=ROOT, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("corrupt", result.stderr)

        result = subprocess.run([sys.executable, "-m", "tfwhy", "history", "clear", "--history-file", str(self.history_path)], cwd=ROOT, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("confirmation", result.stderr)
        self.assertTrue(self.history_path.exists())

        result = subprocess.run([sys.executable, "-m", "tfwhy", "history", "clear", "--confirm", "--history-file", str(self.history_path)], cwd=ROOT, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(self.history_path.exists())


if __name__ == "__main__":
    unittest.main()