"""Actual private PostgreSQL experiment; no account, network or learner-data actions."""

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("owned_postgres_transfer", HERE / "system.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def run():
    value = {
        "operation_key": "paper-transfer",
        "source": "alice-a",
        "destination": "alice-b",
        "amount": 250,
    }
    with m.Cluster() as cluster:
        root = cluster.root
        initial = cluster.balances()
        negative = cluster.counterexample()
        adapter = m.Adapter(cluster)
        alice = adapter.issue("alice")
        bob = adapter.issue("bob")
        denied = []
        for label, payload, fault in [
            ("missing-destination", dict(value, destination="missing"), None),
            ("other-owner-destination", dict(value, destination="bob-a"), None),
            ("after-debit-failure", value, "after-debit"),
        ]:
            try:
                adapter.submit(alice, payload, fault=fault)
            except m.Rejected as error:
                denied.append(
                    {
                        "case": label,
                        "sqlstate": error.state,
                        "balances_unchanged": cluster.balances() == initial,
                        "operation_count": cluster.operation_count(),
                    }
                )
            else:
                raise RuntimeError("required denial did not occur")
        try:
            adapter.submit(alice, value, fault="lost-reply")
        except m.LostReply:
            pass
        else:
            raise RuntimeError("named reply loss missing")
        committed = cluster.balances()
        reply = adapter.submit(alice, value)
        replay_unchanged = cluster.balances() == committed and cluster.operation_count() == 1
        changed_denied = False
        try:
            adapter.submit(alice, dict(value, amount=251))
        except m.Rejected as error:
            changed_denied = error.state == "22023" and cluster.balances() == committed
        direct_write_denied = False
        try:
            cluster.query("app_alice", "UPDATE public.accounts SET balance=0;")
        except m.Rejected as error:
            direct_write_denied = error.state == "42501"
        bob_visible = adapter.balances(bob)
        adapter.revoke(alice)
        cluster.restart()
        revoked = False
        try:
            adapter.submit(alice, value)
        except m.Denied:
            revoked = True
        fresh = adapter.issue("alice")
        restarted = adapter.submit(fresh, value)
        server_version = cluster.query("fixture_admin", "SHOW server_version;")
        no_tcp = cluster.query("fixture_admin", "SHOW listen_addresses;") == ""
        checks = {
            "native_zero_row_update_committed_partial_control": negative
            == {"credit_rows": 0, "source": 9750, "total": 10750},
            "required_denials_rolled_back": len(denied) == 3
            and all(
                x["balances_unchanged"] and x["operation_count"] == 0 and x["sqlstate"] == "P0001"
                for x in denied
            ),
            "lost_reply_retry_reuses_one_effect": replay_unchanged,
            "changed_request_conflicts": changed_denied,
            "same_caller_rls_and_privileges": bob_visible == {"bob-a": 5000}
            and direct_write_denied,
            "database_restart_preserves_effect_not_revoked_capability": revoked
            and restarted == reply
            and cluster.operation_count() == 1,
            "native_server_has_no_tcp_listener": no_tcp,
            "authorized_transfer_conserves_fixture_total": sum(committed.values())
            == sum(initial.values())
            and committed == {"alice-a": 9750, "alice-b": 1250, "bob-a": 5000},
        }
        report = {
            "server_version": server_version,
            "loaded_code_sha256": m.CODE_SHA,
            "schema_sha256": m.SCHEMA_SHA,
            "initial_cents": initial,
            "negative_control": negative,
            "denials": denied,
            "committed_cents": committed,
            "captured_reply": reply,
            "checks": checks,
            "limits": "PostgreSQL14 native fixture, private same-OS-user Unix-socket trust and fictional sessions; no real login, HTTP/Supabase/Next.js validation, provider calls or money. SECURITY DEFINER uses explicit session_user guards, not RLS enforcement inside owner code. Normal database stop/restart only, policy stays in this Python process; reply loss is injected after confirmed commit, no crash/power-loss or durable identity claim.",
        }
    report["checks"]["owned_server_stopped_and_workspace_removed"] = not root.exists()
    if not all(type(x) is bool and x for x in report["checks"].values()):
        raise RuntimeError("native transfer experiment failed")
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
