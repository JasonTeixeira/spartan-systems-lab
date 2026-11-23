"""Owned PostgreSQL14 cluster with private Unix socket; fictional transfer data only."""

import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE_SHA = hashlib.sha256((HERE / "system.py").read_bytes()).hexdigest()
SCHEMA = (HERE / "schema.sql").read_bytes()
SCHEMA_SHA = hashlib.sha256(SCHEMA).hexdigest()
ROLES = {"fixture_admin", "app_alice", "app_bob"}


class Rejected(RuntimeError):
    def __init__(self, state="unknown"):
        super().__init__("database rejected the operation")
        self.state = state


def request(value):
    if type(value) is not dict or set(value) != {
        "operation_key",
        "source",
        "destination",
        "amount",
    }:
        raise ValueError("exact transfer fields required")
    for name, pattern in [
        ("operation_key", r"[a-z0-9-]{1,32}"),
        ("source", r"[a-z][a-z0-9-]{0,31}"),
        ("destination", r"[a-z][a-z0-9-]{0,31}"),
    ]:
        if type(value[name]) is not str or not re.fullmatch(pattern, value[name]):
            raise ValueError("invalid identifier")
    if (
        value["source"] == value["destination"]
        or type(value["amount"]) is not int
        or not 1 <= value["amount"] <= 1000000
    ):
        raise ValueError("invalid amount or same account")
    return dict(value)


class Cluster:
    """Trusted test-driver API. No external cluster, SQL or identity is accepted by the CLI."""

    def __init__(self):
        self.root = None
        self.initialized = False
        self.closed = False
        self.commands = {
            name: shutil.which(name) for name in ["postgres", "initdb", "pg_ctl", "psql"]
        }
        if not all(self.commands.values()):
            raise RuntimeError(
                "installed PostgreSQL14 tools required; nothing installed automatically"
            )
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
        self.env.update(PGPASSFILE=os.devnull, PGCONNECT_TIMEOUT="2")
        self.version = self._run("postgres", ["--version"]).stdout.strip()
        for name in ["postgres", "initdb", "pg_ctl", "psql"]:
            if not re.search(r"\b14\.", self._run(name, ["--version"]).stdout):
                raise RuntimeError("all PostgreSQL executables must be major14")

    def _run(self, name, args, **kwargs):
        return subprocess.run(
            [self.commands[name], *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=kwargs.pop("timeout", 10),
            **kwargs,
        )

    def __enter__(self):
        if self.root is not None or self.closed:
            raise RuntimeError("new fixture only")
        if (
            hashlib.sha256((HERE / "system.py").read_bytes()).hexdigest() != CODE_SHA
            or (HERE / "schema.sql").read_bytes() != SCHEMA
        ):
            raise RuntimeError("fixture edition drift")
        self.root = Path(tempfile.mkdtemp(prefix="sage-pg-", dir=Path("/tmp").resolve()))
        self.data = self.root / "d"
        self.socket = self.root / "s"
        self.socket.mkdir(mode=0o700)
        try:
            self._run(
                "initdb",
                [
                    "-D",
                    str(self.data),
                    "-U",
                    "fixture_admin",
                    "--auth-local=trust",
                    "--auth-host=reject",
                    "--no-locale",
                    "-E",
                    "UTF8",
                ],
                check=True,
                timeout=20,
            )
            self.initialized = True
            self._start()
            self.query("fixture_admin", SCHEMA.decode())
            self.reset()
            return self
        except BaseException:
            if self.initialized:
                self.close()
            else:
                raise RuntimeError(
                    "initialization failed; owned diagnostic directory retained: " + str(self.root)
                ) from None
            raise

    def _start(self):
        options = shlex.join(
            [
                "-k",
                str(self.socket),
                "-h",
                "",
                "-p",
                "65431",
                "-c",
                "unix_socket_permissions=0700",
                "-c",
                "max_connections=8",
                "-c",
                "shared_buffers=16MB",
            ]
        )
        self._run(
            "pg_ctl",
            [
                "start",
                "-D",
                str(self.data),
                "-l",
                str(self.root / "server.log"),
                "-w",
                "-t",
                "5",
                "-o",
                options,
            ],
            check=True,
        )

    def _stop(self):
        status = self._run("pg_ctl", ["status", "-D", str(self.data)])
        if status.returncode == 0:
            self._run(
                "pg_ctl",
                ["stop", "-D", str(self.data), "-m", "fast", "-w", "-t", "5"],
                check=True,
            )
        elif status.returncode != 3:
            raise RuntimeError("cannot confirm owned server state; retain " + str(self.root))
        if self._run("pg_ctl", ["status", "-D", str(self.data)]).returncode != 3:
            raise RuntimeError("owned server still active; retain " + str(self.root))

    def close(self):
        if self.closed:
            return
        if self.root is not None:
            self._stop()  # Never remove files while this owned postmaster might be active.
            shutil.rmtree(self.root)
        self.closed = True

    def __exit__(self, *args):
        self.close()

    def query(self, role, sql, variables=None):
        if self.closed or not self.initialized:
            raise RuntimeError("fixture is not available")
        if role not in ROLES or type(sql) is not str or len(sql) > 65536:
            raise ValueError("trusted operator query")
        args = [
            "-X",
            "-w",
            "-A",
            "-t",
            "-q",
            "-h",
            str(self.socket),
            "-p",
            "65431",
            "-U",
            role,
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
            "-v",
            "VERBOSITY=sqlstate",
        ]
        for key, value in (variables or {}).items():
            if not re.fullmatch("[a-z_]+", key) or type(value) is not str or len(value) > 512:
                raise ValueError("query variable")
            args += ["-v", key + "=" + value]
        completed = self._run(
            "psql",
            args,
            input="SET statement_timeout=2000; SET lock_timeout=1000;\n" + sql,
            timeout=5,
        )
        if completed.returncode:
            state = re.search(r"ERROR:\s+([A-Z0-9]{5})", completed.stderr)
            raise Rejected(state.group(1) if state else "unknown")
        return completed.stdout.rstrip("\n")

    def reset(self):
        self.query(
            "fixture_admin",
            "TRUNCATE public.accounts,public.operations,public.bad_accounts; INSERT INTO public.accounts VALUES('alice-a','app_alice',10000),('alice-b','app_alice',1000),('bob-a','app_bob',5000);",
        )

    def transfer(self, actor, value, fail=False):
        if actor not in ("alice", "bob"):
            raise ValueError("trusted fixture actor")
        value = request(value)
        if type(fail) is not bool:
            raise ValueError("trusted failure control")
        variables = {
            "k": value["operation_key"],
            "src": value["source"],
            "dst": value["destination"],
            "amount": str(value["amount"]),
            "fault": "true" if fail else "false",
        }
        raw = self.query(
            "app_" + actor,
            "SELECT public.transfer(:'k',:'src',:'dst',:'amount'::bigint,:'fault'::boolean);",
            variables,
        )
        return json.loads(raw)

    def balances(self):
        return json.loads(
            self.query(
                "fixture_admin",
                "SELECT json_object_agg(id,balance) FROM public.accounts;",
            )
        )

    def operation_count(self):
        return int(self.query("fixture_admin", "SELECT count(*) FROM public.operations;"))

    def counterexample(self):
        # Owned negative control, never imported source code or user data.
        sql = """BEGIN; TRUNCATE public.bad_accounts;
        INSERT INTO public.bad_accounts VALUES('a',10000),('b',1000);
        UPDATE public.bad_accounts SET balance=balance-250 WHERE id='a';
        WITH credit AS (UPDATE public.bad_accounts SET balance=balance+250 WHERE id='missing' RETURNING id)
        SELECT json_build_object('credit_rows',(SELECT count(*) FROM credit),'source',(SELECT balance FROM public.bad_accounts WHERE id='a'),'total',(SELECT sum(balance) FROM public.bad_accounts)); COMMIT;"""
        return json.loads(self.query("fixture_admin", sql))

    def restart(self):
        self._stop()
        self._start()


class Denied(PermissionError):
    pass


class Unavailable(RuntimeError):
    pass


class LostReply(RuntimeError):
    pass


class Adapter:
    def __init__(self, cluster):
        self.cluster = cluster
        self.sessions = {}
        self.available = True
        self.lock = threading.RLock()

    def issue(self, actor):
        with self.lock:
            if actor not in ("alice", "bob") or len(self.sessions) >= 16:
                raise ValueError("fixture actor/session capacity")
            token = secrets.token_hex(32)
            self.sessions[hashlib.sha256(token.encode()).hexdigest()] = actor
            return token

    def _actor(self, token):
        if type(token) is not str or not re.fullmatch("[a-f0-9]{64}", token):
            raise Denied("session required")
        actor = self.sessions.get(hashlib.sha256(token.encode()).hexdigest())
        if actor is None:
            raise Denied("session required")
        if not self.available:
            raise Unavailable("policy unavailable")
        return actor

    def revoke(self, token):
        with self.lock:
            if type(token) is not str or not re.fullmatch("[a-f0-9]{64}", token):
                raise ValueError("fixture session")
            self.sessions.pop(hashlib.sha256(token.encode()).hexdigest(), None)

    def set_available(self, available):
        if type(available) is not bool:
            raise ValueError("policy flag")
        with self.lock:
            self.available = available

    def submit(self, token, value, fault=None):
        # Coarse local lock orders revocation after an already admitted RPC.
        # It does not interrupt a running SQL transaction or model distributed identity.
        with self.lock:
            actor = self._actor(token)
            if fault not in (None, "after-debit", "lost-reply"):
                raise ValueError("named fixture fault")
            result = self.cluster.transfer(actor, value, fail=fault == "after-debit")
            if fault == "lost-reply":
                raise LostReply("simulated response loss after confirmed commit")
            return result

    def balances(self, token):
        with self.lock:
            actor = self._actor(token)
            return json.loads(
                self.cluster.query(
                    "app_" + actor,
                    "SELECT json_object_agg(id,balance) FROM public.accounts;",
                )
            )
