# Local credential-leak fixture

Read the [maintained lesson](../../teaching/security/credential-leak/lesson.md). Python standard library only; no install, network, real credentials or external scanning.

From the project root, run each command separately:

```bash
python3 labs/credential-leak/scanner.py --fixture unsafe
```

Expected exit 1: two synthetic matches across four events.

```bash
python3 labs/credential-leak/scanner.py --fixture repaired
```

Expected exit 0: no matches across the same four events.

```bash
python3 labs/credential-leak/scanner.py --fixture invalid
```

Expected exit 2: invalid schema, no clean result established. Never suppress these failures in a gate.

```bash
python3 labs/credential-leak/scanner.py --self-check
python3 -m unittest discover -s tests -p test_credential_leak.py -v
```

Both verification commands should exit 0. They explicitly assert the negative cases. Reports omit matched values; inputs remain unchanged. Named fixtures are bounded and schema validated. The scanner's synthetic rule is not a general credential detector or production security assurance. Do not replace these fixtures with real secrets.
