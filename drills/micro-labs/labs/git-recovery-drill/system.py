"""Real Git observations in an internally created disposable repository only."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def run():
    executable = shutil.which("git")
    if executable is None:
        raise RuntimeError("Git executable required")
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    environment.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_ALLOW_PROTOCOL="file",
        GIT_TERMINAL_PROMPT="0",
        GIT_PAGER="cat",
    )
    with tempfile.TemporaryDirectory(prefix="sage-owned-git-drill-") as temp:
        owned = Path(temp).resolve()
        repo = owned / "repository"
        repo.mkdir()
        hooks = owned / "empty-hooks"
        hooks.mkdir()
        templates = owned / "empty-templates"
        templates.mkdir()

        def git(*arguments, expected=(0,)):
            completed = subprocess.run(
                [
                    executable,
                    "-c",
                    "core.hooksPath=" + str(hooks),
                    "-c",
                    "init.templateDir=" + str(templates),
                    "-c",
                    "user.name=Owned fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "-c",
                    "commit.gpgSign=false",
                    "-c",
                    "tag.gpgSign=false",
                    "-c",
                    "gc.auto=0",
                    "-c",
                    "maintenance.auto=false",
                    "-c",
                    "core.autocrlf=false",
                    "-c",
                    "core.excludesFile=" + os.devnull,
                    *arguments,
                ],
                cwd=repo,
                env=environment,
                capture_output=True,
                text=True,
                timeout=5,
                check=True if expected == (0,) else False,
            )
            if completed.returncode not in expected:
                raise subprocess.CalledProcessError(completed.returncode, completed.args)
            return completed

        version = git("--version").stdout.strip()
        git("init", "-b", "main")
        tracked = repo / "tracked.txt"
        tracked.write_text("base\n")
        (repo / ".gitignore").write_text("cache.txt\n")
        git("add", "tracked.txt", ".gitignore")
        git("commit", "-m", "Owned base")
        initial = git("rev-parse", "HEAD").stdout.strip()
        tracked.write_text("edited\n")
        (repo / "untracked.txt").write_text("new\n")
        (repo / "cache.txt").write_text("cache\n")
        git("stash", "push", "-m", "Tracked only")
        after_default = {
            "tracked": tracked.read_text(),
            "untracked_exists": (repo / "untracked.txt").exists(),
            "ignored_exists": (repo / "cache.txt").exists(),
        }
        git("stash", "apply", "stash@{0}")
        git("stash", "push", "-u", "-m", "Tracked and untracked")
        after_untracked = {
            "untracked_exists": (repo / "untracked.txt").exists(),
            "ignored_exists": (repo / "cache.txt").exists(),
        }
        git("stash", "apply", "stash@{0}")
        after_restore = {
            "tracked": tracked.read_text(),
            "untracked": (repo / "untracked.txt").read_text(),
            "ignored": (repo / "cache.txt").read_text(),
        }

        backup = owned / "tracked-backup.txt"
        shutil.copyfile(tracked, backup)
        git("add", "tracked.txt")
        before_status = git("status", "--porcelain=v1", "--", "tracked.txt").stdout.rstrip("\n")
        git("reset", "--mixed", "HEAD", "--", "tracked.txt")
        recovery = {
            "before_status": before_status,
            "after_status": git("status", "--porcelain=v1", "--", "tracked.txt").stdout.rstrip(
                "\n"
            ),
            "working_bytes": tracked.read_text(),
            "backup_bytes": backup.read_text(),
            "committed_bytes": git("show", "HEAD:tracked.txt").stdout,
            "head_unchanged": git("rev-parse", "HEAD").stdout.strip() == initial,
        }
        ignore = repo / ".gitignore"
        ignore.write_text("cache.txt # cache data\n")
        bad_ignore = git("check-ignore", "-q", "cache.txt", expected=(0, 1)).returncode == 0
        ignore.write_text("# Cache data\ncache.txt\n")
        good_ignore = git("check-ignore", "-q", "cache.txt", expected=(0, 1)).returncode == 0
        git("add", "tracked.txt", ".gitignore")
        git("commit", "-m", "Preserve fixture edits before branching")
        base = git("rev-parse", "HEAD").stdout.strip()
        git("branch", "feature")
        (repo / "main.txt").write_text("main addition\n")
        git("add", "main.txt")
        git("commit", "-m", "Advance main")
        main = git("rev-parse", "HEAD").stdout.strip()
        git("switch", "feature")
        (repo / "feature.txt").write_text("feature addition\n")
        git("add", "feature.txt")
        git("commit", "-m", "Advance feature independently")
        feature = git("rev-parse", "HEAD").stdout.strip()
        diff = {
            "tip_to_tip": git("diff", "--name-only", "main..feature").stdout.splitlines(),
            "merge_base_to_feature": git(
                "diff", "--name-only", "main...feature"
            ).stdout.splitlines(),
            "base_distinct_from_both_tips": base not in (main, feature)
            and git("merge-base", "main", "feature").stdout.strip() == base,
        }
        git("tag", "release", base)
        old_tag = git("rev-parse", "release").stdout.strip()
        git("tag", "-f", "release", feature)
        changed_tag = git("rev-parse", "release").stdout.strip() != old_tag
        git("pack-refs", "--all", "--prune")
        refs = {
            "tag_target_changed": changed_tag,
            "packed_branch_resolves": git("rev-parse", "refs/heads/main").stdout.strip() == main,
            "loose_branch_exists_after_pack": (repo / ".git/refs/heads/main").exists(),
        }
        checks = {
            "default_stash_leaves_untracked_and_ignored": after_default
            == {"tracked": "base\n", "untracked_exists": True, "ignored_exists": True},
            "untracked_option_still_leaves_ignored": after_untracked
            == {"untracked_exists": False, "ignored_exists": True},
            "all_fixture_bytes_restored": after_restore
            == {"tracked": "edited\n", "untracked": "new\n", "ignored": "cache\n"},
            "unstage_keeps_work_and_backup": recovery["working_bytes"]
            == recovery["backup_bytes"]
            == "edited\n"
            and recovery["head_unchanged"],
            "merge_base_diff_excludes_main_only_addition": diff["tip_to_tip"]
            == ["feature.txt", "main.txt"]
            and diff["merge_base_to_feature"] == ["feature.txt"],
            "ignore_comments_must_be_separate": not bad_ignore and good_ignore,
            "refs_are_not_permanent_or_always_loose": changed_tag
            and refs["packed_branch_resolves"]
            and not refs["loose_branch_exists_after_pack"],
        }
        if not all(checks.values()):
            raise RuntimeError("Git observation differs from fixture contract")
        return {
            "git_version": version,
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "stash": {
                "after_default": after_default,
                "after_include_untracked": after_untracked,
                "after_restore": after_restore,
            },
            "recovery": recovery,
            "diff": diff,
            "ignore": {
                "inline_comment_matches": bad_ignore,
                "own_line_comment_matches": good_ignore,
            },
            "refs": refs,
            "checks": checks,
            "limits": "Internally created disposable local repository, no remote/push, user config or hooks; not user-data backup, arbitrary filesystem sandbox, PR platform behavior or recovery guarantee. Per-command5s timeout, no whole-drill deadline. Reflog does not promise never-committed bytes.",
        }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
