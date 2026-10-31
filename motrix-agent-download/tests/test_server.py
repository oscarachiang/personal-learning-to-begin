import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import urllib.error

spec = importlib.util.spec_from_file_location("server", Path(__file__).resolve().parents[1] / "scripts/server.py")
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)


class Response(io.BytesIO):
    status = 206
    headers = {"Content-Range": "bytes 0-1048575/1073741824"}


class Tests(unittest.TestCase):
    def test_stdio(self):
        messages = [dict(jsonrpc="2.0", id=1, method="initialize", params={"protocolVersion": "2025-03-26"}),
                    dict(jsonrpc="2.0", method="notifications/initialized"),
                    dict(jsonrpc="2.0", id=2, method="tools/list"),
                    dict(jsonrpc="2.0", id=3, method="tools/call", params={"name": "motrix_add", "arguments": {}})]
        p = subprocess.run([sys.executable, "-I", str(Path(s.__file__))], input="\n".join(map(json.dumps, messages)), text=True, capture_output=True, check=True)
        results = list(map(json.loads, p.stdout.splitlines()))
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(len(results[1]["result"]["tools"]), 8)
        self.assertTrue(results[2]["result"]["isError"])
        self.assertEqual(p.stderr, "")

    def test_probe_cap_and_range(self):
        response = Response(b"x" * (2 * 1048576))
        with patch.object(s, "opener") as op:
            op.return_value.open.return_value = response
            result = s.probe("https://example.org/file")
        self.assertEqual(result["sample_bytes"], 1048576)
        self.assertTrue(result["range_supported"])
        self.assertEqual(result["suggested_initial_connections"], 8)

    def test_ignored_range(self):
        response = Response(b"data")
        response.status = 200
        response.headers = {"Content-Length": "1000000000"}
        with patch.object(s, "opener") as op:
            op.return_value.open.return_value = response
            result = s.probe("https://example.org/file")
        self.assertFalse(result["range_supported"])
        self.assertEqual(result["suggested_initial_connections"], 1)

    def test_small_file_range(self):
        response = Response(b"data")
        response.headers = {"Content-Range": "bytes 0-3/4"}
        with patch.object(s, "opener") as op:
            op.return_value.open.return_value = response
            result = s.probe("https://example.org/file")
        self.assertTrue(result["range_supported"])
        self.assertEqual(result["total_bytes"], 4)

    def test_bridge_does_not_rely_on_host_pid(self):
        state = json.dumps({"port": 16801, "pid": 99999999, "localToken": "fixture-token"})
        response = Response(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"activeTasks": 0}}).encode())
        with patch.dict(s.os.environ, {}, clear=True), patch.object(Path, "read_text", return_value=state), patch.object(s.os, "kill", side_effect=ProcessLookupError) as kill, patch.object(s, "opener") as op:
            op.return_value.open.return_value = response
            self.assertEqual(s.bridge("stats/get", {}), {"activeTasks": 0})
            kill.assert_not_called()

    def test_rate_limit(self):
        with patch.object(s, "opener") as op:
            op.return_value.open.side_effect = urllib.error.HTTPError("https://secret/", 429, "private", {"Retry-After": "60"}, None)
            result = s.probe("https://example.org/file")
        self.assertEqual(result["retry_after"], "60")
        self.assertNotIn("secret", json.dumps(result))

    def test_add_parameters(self):
        with patch.object(s, "bridge", return_value={"id": "test"}) as rpc:
            s.call("motrix_add", dict(url="https://example.org/file", save_dir="/downloads", connections=8, proxy=""))
        self.assertEqual(rpc.call_args.args, ("download/add", dict(kind="url", uris=["https://example.org/file"], saveDir="/downloads", connections=8, proxy="")))
        with self.assertRaises(ValueError):
            s.call("motrix_add", dict(url="https://example.org/file", save_dir="/downloads", connections=128))

    def test_checksum(self):
        path = Path(s.__file__).resolve()
        digest = s.hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertTrue(s.call("verify_sha256", {"path": str(path), "sha256": digest})["matches"])
        self.assertFalse(s.call("verify_sha256", {"path": str(path), "sha256": "0" * 64})["matches"])

    def test_cli(self):
        p = subprocess.run([sys.executable, "-I", s.__file__, "--list-tools"], text=True, capture_output=True, check=True)
        self.assertEqual(len(json.loads(p.stdout)), 8)
        p = subprocess.run([sys.executable, "-I", s.__file__, "--tool", "motrix_add"], input="{}", text=True, capture_output=True)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(p.stdout, "")
        self.assertIn("error", json.loads(p.stderr))

    def test_get_task(self):
        with patch.object(s, "bridge", return_value={"task": {"id": "test"}}) as rpc:
            result = s.call("motrix_get", {"task_id": "test"})
        self.assertEqual(result["task"]["id"], "test")
        rpc.assert_called_once_with("task/get", {"taskId": "test"})

    def test_secret_error_redaction(self):
        with patch.object(s, "bridge", side_effect=OSError("https://host/?token=secret")):
            r = s.handle(dict(id=1, method="tools/call", params={"name": "motrix_stats"}))
        self.assertTrue(r["result"]["isError"])
        self.assertNotIn("secret", json.dumps(r))


if __name__ == "__main__":
    unittest.main()
