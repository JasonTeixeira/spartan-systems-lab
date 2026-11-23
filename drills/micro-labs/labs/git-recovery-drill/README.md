# Observe Git recovery boundaries in a disposable repository

From the project root:

```bash
python3 labs/git-recovery-drill/system.py
python3 -m unittest discover -s tests -p 'test_git_recovery_drill.py'
```

Requires installed Git and standard-library Python. The runner creates its own temporary repository; it takes no repository/path/command arguments. It does not push, fetch, contact a remote, execute imported lesson code, modify your Git configuration or touch personal progress. Inherited `GIT_*` variables are removed; global/system config, templates, hooks and signing are disabled for these fixture commands. The OS, executable lookup and filesystem remain trusted; this is not a hostile-process sandbox.

The script observes default versus `-u` stash behavior, tip versus merge-base diffs after both branches advance, a mixed path reset that unstages without changing work, an explicit temporary byte backup, broken/fixed ignore comments, a moved local tag and a branch resolved after ref packing. A per-command timeout is5seconds; command errors propagate. There is no whole-drill deadline. The reported source digest hashes the file at reporting time, not an immutable loaded-code attestation. Temporary fixture data and its backup disappear after the run: this is not a backup tool for your files.

Study [the visual lesson](../../teaching/git-recovery-drill/index.md). The preserved selected Git sources remain marked repair; this scoped correction does not approve their entire courses or other defective claims.
