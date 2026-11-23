import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "git_drill",
    Path(__file__).resolve().parents[1] / "labs/git-recovery-drill/system.py",
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class GitRecoveryDrillTests(unittest.TestCase):
    def test_stash_scope_and_ignored_files(self):
        report = m.run()
        self.assertEqual(
            report["stash"]["after_default"],
            {"tracked": "base\n", "untracked_exists": True, "ignored_exists": True},
        )
        self.assertEqual(
            report["stash"]["after_include_untracked"],
            {"untracked_exists": False, "ignored_exists": True},
        )
        self.assertEqual(
            report["stash"]["after_restore"],
            {"tracked": "edited\n", "untracked": "new\n", "ignored": "cache\n"},
        )

    def test_diverged_tip_diff_is_not_merge_base_diff(self):
        result = m.run()["diff"]
        self.assertEqual(result["tip_to_tip"], ["feature.txt", "main.txt"])
        self.assertEqual(result["merge_base_to_feature"], ["feature.txt"])
        self.assertTrue(result["base_distinct_from_both_tips"])

    def test_non_destructive_unstage_preserves_edit_and_external_backup(self):
        result = m.run()["recovery"]
        self.assertEqual(result["before_status"], "M  tracked.txt")
        self.assertEqual(result["after_status"], " M tracked.txt")
        self.assertEqual(result["working_bytes"], "edited\n")
        self.assertEqual(result["backup_bytes"], "edited\n")
        self.assertEqual(result["committed_bytes"], "base\n")
        self.assertTrue(result["head_unchanged"])

    def test_ignore_comments_and_movable_tag_packed_branch(self):
        report = m.run()
        self.assertEqual(
            report["ignore"],
            {"inline_comment_matches": False, "own_line_comment_matches": True},
        )
        self.assertTrue(report["refs"]["tag_target_changed"])
        self.assertTrue(report["refs"]["packed_branch_resolves"])
        self.assertFalse(report["refs"]["loose_branch_exists_after_pack"])

    def test_inherited_git_environment_cannot_redirect_repository(self):
        with tempfile.TemporaryDirectory() as outside:
            sentinel = Path(outside) / "keep.txt"
            sentinel.write_text("preserve")
            with patch.dict(
                os.environ,
                {
                    "GIT_DIR": outside,
                    "GIT_WORK_TREE": outside,
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "core.hooksPath",
                    "GIT_CONFIG_VALUE_0": outside,
                },
            ):
                self.assertTrue(all(m.run()["checks"].values()))
            self.assertEqual(sentinel.read_text(), "preserve")
            self.assertEqual(sorted(p.name for p in Path(outside).iterdir()), ["keep.txt"])

    def test_timeout_and_git_failure_are_not_suppressed(self):
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 5)):
            with self.assertRaises(subprocess.TimeoutExpired):
                m.run()
        with patch.object(subprocess, "run", side_effect=subprocess.CalledProcessError(1, "git")):
            with self.assertRaises(subprocess.CalledProcessError):
                m.run()
