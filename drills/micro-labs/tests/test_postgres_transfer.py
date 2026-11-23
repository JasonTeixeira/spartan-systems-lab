import importlib.util
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "pg_transfer",
    Path(__file__).resolve().parents[1] / "labs/postgres-transfer/system.py",
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def request(key="first", amount=250, destination="alice-b"):
    return {
        "operation_key": key,
        "source": "alice-a",
        "destination": destination,
        "amount": amount,
    }


class PostgresTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cluster = m.Cluster().__enter__()

    @classmethod
    def tearDownClass(cls):
        root = cls.cluster.root
        cls.cluster.close()
        if root.exists():
            raise AssertionError("owned cluster was not removed")

    def setUp(self):
        self.cluster.reset()

    def test_native_zero_row_control_commits_a_partial_effect(self):
        result = self.cluster.counterexample()
        self.assertEqual(result, {"credit_rows": 0, "source": 9750, "total": 10750})
        self.assertEqual(
            self.cluster.balances(), {"alice-a": 10000, "alice-b": 1000, "bob-a": 5000}
        )

    def test_valid_transfer_replay_captured_result_and_changed_request_conflict(self):
        first = self.cluster.transfer("alice", request())
        self.assertEqual(first["source_balance"], 9750)
        self.assertEqual(first["destination_balance"], 1250)
        self.cluster.transfer("alice", request("second", 100))
        before = self.cluster.balances()
        self.assertEqual(self.cluster.transfer("alice", request()), first)
        self.assertEqual(self.cluster.balances(), before)
        self.assertEqual(self.cluster.operation_count(), 2)
        with self.assertRaises(m.Rejected):
            self.cluster.transfer("alice", request(amount=251))
        self.assertEqual(self.cluster.balances(), before)

    def test_missing_or_other_owner_destination_denies_without_effect(self):
        for target in ["missing", "bob-a"]:
            with self.subTest(target=target):
                before = self.cluster.balances()
                with self.assertRaises(m.Rejected):
                    self.cluster.transfer("alice", request(destination=target))
                self.assertEqual(self.cluster.balances(), before)
                self.assertEqual(self.cluster.operation_count(), 0)
        with self.assertRaises(m.Rejected):
            self.cluster.transfer("bob", request())

    def test_failure_after_debit_and_zero_credit_rows_roll_back_all_state(self):
        before = self.cluster.balances()
        with self.assertRaises(m.Rejected):
            self.cluster.transfer("alice", request(), fail=True)
        self.assertEqual(self.cluster.balances(), before)
        self.assertEqual(self.cluster.operation_count(), 0)
        self.cluster.query(
            "fixture_admin",
            "UPDATE public.accounts SET balance=1000000000 WHERE id='alice-b';",
        )
        before = self.cluster.balances()
        with self.assertRaises(m.Rejected):
            self.cluster.transfer("alice", request())
        self.assertEqual(self.cluster.balances(), before)
        self.assertEqual(self.cluster.operation_count(), 0)

    def test_insufficient_funds_and_strict_payloads_do_not_mutate(self):
        before = self.cluster.balances()
        with self.assertRaises(m.Rejected):
            self.cluster.transfer("alice", request(amount=10001))
        for bad in [True, 0, -1, 1.5, 1000001, float("inf"), "250"]:
            with self.subTest(amount=bad), self.assertRaises(ValueError):
                self.cluster.transfer("alice", request(amount=bad))
        for payload in [
            dict(request(), owner="bob"),
            dict(request(), source="alice-a'; DROP TABLE accounts;--"),
            request(destination="alice-a"),
        ]:
            with self.assertRaises(ValueError):
                self.cluster.transfer("alice", payload)
        self.assertEqual(self.cluster.balances(), before)
        self.assertEqual(self.cluster.operation_count(), 0)

    def test_native_rls_and_no_direct_write_or_role_escalation(self):
        visible = json.loads(
            self.cluster.query("app_alice", "SELECT json_agg(id ORDER BY id) FROM public.accounts;")
        )
        self.assertEqual(visible, ["alice-a", "alice-b"])
        self.assertEqual(
            json.loads(self.cluster.query("app_bob", "SELECT json_agg(id) FROM public.accounts;")),
            ["bob-a"],
        )
        for sql in [
            "UPDATE public.accounts SET balance=0;",
            "SET ROLE fixture_admin;",
            "SET SESSION AUTHORIZATION fixture_admin;",
            "CREATE TABLE public.hijack(x int);",
        ]:
            with self.subTest(sql=sql), self.assertRaises(m.Rejected) as error:
                self.cluster.query("app_alice", sql)
            self.assertEqual(error.exception.state, "42501")
        self.assertEqual(len(self.cluster.balances()), 3)

    def test_concurrent_same_key_has_one_effect(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.cluster.transfer("alice", request()), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.cluster.operation_count(), 1)
        self.assertEqual(self.cluster.balances()["alice-a"], 9750)

    def test_competing_debits_cannot_overspend(self):
        def apply(key):
            try:
                return self.cluster.transfer("alice", request(key, 7000))
            except m.Rejected as error:
                return error.state

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(apply, ["left", "right"]))
        self.assertEqual(sum(type(x) is dict for x in results), 1)
        self.assertEqual([x for x in results if type(x) is str], ["P0001"])
        self.assertEqual(self.cluster.balances()["alice-a"], 3000)
        self.assertEqual(self.cluster.operation_count(), 1)

    def test_restart_persists_saved_effect_and_no_tcp_listener(self):
        first = self.cluster.transfer("alice", request())
        self.cluster.restart()
        self.assertEqual(self.cluster.transfer("alice", request()), first)
        self.assertEqual(self.cluster.operation_count(), 1)
        self.assertEqual(self.cluster.query("fixture_admin", "SHOW listen_addresses;"), "")
        self.assertEqual(self.cluster.root.stat().st_mode & 0o777, 0o700)

    def test_replay_checks_current_resource_ownership(self):
        self.cluster.transfer("alice", request())
        self.cluster.query(
            "fixture_admin",
            "UPDATE public.accounts SET owner='app_bob' WHERE id='alice-a';",
        )
        with self.assertRaises(m.Rejected):
            self.cluster.transfer("alice", request())
        self.assertEqual(self.cluster.operation_count(), 1)

    def test_adapter_uses_current_session_not_payload_and_survives_data_restart_revocation(
        self,
    ):
        adapter = m.Adapter(self.cluster)
        alice = adapter.issue("alice")
        bob = adapter.issue("bob")
        first = adapter.submit(alice, request())
        self.assertEqual(adapter.balances(bob), {"bob-a": 5000})
        with self.assertRaises(ValueError):
            adapter.submit(alice, dict(request("other"), owner="bob"))
        with self.assertRaises(m.Denied):
            adapter.submit("0" * 64, request("other"))
        adapter.revoke(alice)
        self.cluster.restart()
        with self.assertRaises(m.Denied):
            adapter.submit(alice, request())
        fresh = adapter.issue("alice")
        self.assertEqual(adapter.submit(fresh, request()), first)
        self.assertEqual(self.cluster.operation_count(), 1)

    def test_adapter_policy_outage_fails_closed(self):
        adapter = m.Adapter(self.cluster)
        token = adapter.issue("alice")
        adapter.set_available(False)
        with self.assertRaises(m.Unavailable):
            adapter.submit(token, request())
        with self.assertRaises(m.Unavailable):
            adapter.balances(token)
        self.assertEqual(self.cluster.operation_count(), 0)
        adapter.set_available(True)
        self.assertEqual(adapter.submit(token, request())["source_balance"], 9750)

    def test_lost_reply_after_real_commit_reuses_saved_effect(self):
        adapter = m.Adapter(self.cluster)
        token = adapter.issue("alice")
        with self.assertRaises(m.LostReply):
            adapter.submit(token, request(), fault="lost-reply")
        self.assertEqual(self.cluster.operation_count(), 1)
        self.assertEqual(self.cluster.balances()["alice-a"], 9750)
        reply = adapter.submit(token, request())
        self.assertEqual(reply["source_balance"], 9750)
        self.assertEqual(self.cluster.operation_count(), 1)

    def test_native_capacity_allows_saved_replay_but_rejects_new_key(self):
        self.cluster.query(
            "app_alice",
            "DO $$ BEGIN FOR i IN 1..64 LOOP PERFORM public.transfer('op-'||i,'alice-a','alice-b',1,false); END LOOP; END $$;",
        )
        self.assertEqual(self.cluster.operation_count(), 64)
        first = self.cluster.transfer("alice", request("op-1", 1))
        self.assertEqual(first["source_balance"], 9999)
        before = self.cluster.balances()
        with self.assertRaises(m.Rejected) as error:
            self.cluster.transfer("alice", request("overflow", 1))
        self.assertEqual(error.exception.state, "54000")
        self.assertEqual(self.cluster.balances(), before)

    def test_native_function_also_validates_direct_rpc_arguments(self):
        for args in [
            "NULL,'alice-a','alice-b',1,false",
            "'bad','alice-a','alice-b',0,false",
            "'bad','alice-a','alice-b',1,NULL",
        ]:
            with self.subTest(args=args), self.assertRaises(m.Rejected) as error:
                self.cluster.query("app_alice", "SELECT public.transfer(" + args + ");")
            self.assertEqual(error.exception.state, "22023")
        self.assertEqual(self.cluster.operation_count(), 0)

    def test_local_adapter_orders_revoke_after_already_admitted_transaction(self):
        adapter = m.Adapter(self.cluster)
        token = adapter.issue("alice")
        entered = threading.Event()
        release = threading.Event()
        revoke_started = threading.Event()
        order = []
        errors = []
        original = self.cluster.transfer

        def paused(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test release missing")
            result = original(*args, **kwargs)
            order.append("committed")
            return result

        def submit():
            try:
                adapter.submit(token, request())
            except BaseException as error:
                errors.append(error)

        def revoke():
            revoke_started.set()
            adapter.revoke(token)
            order.append("revoked")

        with patch.object(self.cluster, "transfer", side_effect=paused):
            worker = threading.Thread(target=submit)
            worker.start()
            self.assertTrue(entered.wait(2))
            acquired = adapter.lock.acquire(blocking=False)
            if acquired:
                adapter.lock.release()
            self.assertFalse(acquired)
            revoker = threading.Thread(target=revoke)
            revoker.start()
            self.assertTrue(revoke_started.wait(2))
            release.set()
            worker.join(4)
            revoker.join(4)
            self.assertFalse(worker.is_alive())
            self.assertFalse(revoker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(order, ["committed", "revoked"])
        with self.assertRaises(m.Denied):
            adapter.submit(token, request())

    def test_complete_native_demo_and_checked_cleanup(self):
        demo_spec = importlib.util.spec_from_file_location("pg_demo", m.HERE / "demo.py")
        demo = importlib.util.module_from_spec(demo_spec)
        demo_spec.loader.exec_module(demo)
        observed = demo.run()
        self.assertEqual(len(observed["checks"]), 9)
        self.assertTrue(all(value is True for value in observed["checks"].values()))
        self.assertTrue(observed["server_version"].startswith("14."))


class FixtureLifecycleTests(unittest.TestCase):
    def test_closed_unentered_fixture_cannot_start_a_server(self):
        fixture = m.Cluster()
        fixture.close()
        with self.assertRaises(RuntimeError):
            fixture.__enter__()
        self.assertIsNone(fixture.root)
