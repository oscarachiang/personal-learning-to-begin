#!/usr/bin/env python3
"""Dependency-free MCP stdio adapter for Motrix MDXP and bounded HTTP probes."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def obj(props, required=()):
    return dict(type="object", properties=props, required=list(required), additionalProperties=False)


S = {"type": "string"}
TOOLS = [
    ("motrix_stats", "Read aggregate speeds and task counts.", obj({})),
    ("motrix_list", "List tasks (first 100); does not expose download URLs.", obj({})),
    ("motrix_get", "Get an identified task without relying on list pagination.", obj({"task_id": S}, ("task_id",))),
    ("motrix_add", "Queue an explicitly requested HTTP download. Probe first. Connections are initial settings, not live tuning. Multiple mirrors are deliberately unsupported.", obj({"url": S, "save_dir": S, "filename": S, "connections": {"type": "integer", "minimum": 1, "maximum": 16}, "proxy": S}, ("url", "save_dir"))),
    ("motrix_pause", "Pause an identified task only when requested.", obj({"task_id": S}, ("task_id",))),
    ("motrix_resume", "Resume an identified task only when requested.", obj({"task_id": S}, ("task_id",))),
    ("download_probe", "Range GET consuming at most 1 MiB, with a 5 s socket timeout and approximate 5 s read budget (not a strict total deadline). proxy omitted means direct. Compare repeated direct/proxy samples; short samples do not prove sustained speed. Does not save content.", obj({"url": S, "proxy": S}, ("url",))),
    ("verify_sha256", "Verify a completed local regular file against a trusted SHA256.", obj({"path": S, "sha256": S}, ("path", "sha256"))),
]


def validate(name, args):
    schema = next((s for n, _, s in TOOLS if n == name), None)
    if schema is None or not isinstance(args, dict):
        raise ValueError("Unknown tool or invalid arguments")
    if set(args) - set(schema["properties"]) or set(schema["required"]) - set(args):
        raise ValueError("Missing or unknown arguments")
    for key, value in args.items():
        spec = schema["properties"][key]
        if spec["type"] == "string" and (not isinstance(value, str) or "\n" in value or "\r" in value):
            raise ValueError("Invalid string argument")
        if spec["type"] == "integer" and (type(value) is not int or not spec["minimum"] <= value <= spec["maximum"]):
            raise ValueError("Integer outside supported range")


def http_url(url):
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise ValueError("Expected HTTP(S) URL without embedded credentials")
    return url


def opener(proxy=""):
    if proxy:
        http_url(proxy)
        if urllib.parse.urlsplit(proxy).scheme != "http":
            raise ValueError("Only HTTP proxies are supported by this adapter")
    return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {}))


def bridge(method, params):
    endpoint = os.environ.get("MOTRIX_ENDPOINT")
    token = os.environ.get("MOTRIX_BRIDGE_TOKEN")
    if not endpoint:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        try:
            state = json.loads((base / "Motrix/bridge/endpoint.json").read_text())
            # Desktop PIDs may be invisible inside an agent's PID namespace.
            # Let the authenticated HTTP request determine bridge availability.
            endpoint = "http://127.0.0.1:" + str(int(state["port"]))
            token = token or state["localToken"]
        except (OSError, KeyError, ValueError):
            raise ValueError("Motrix bridge discovery unavailable; start the desktop app") from None
    http_url(endpoint)
    if not token:
        raise ValueError("Set MOTRIX_BRIDGE_TOKEN for an explicit endpoint")
    if urllib.parse.urlsplit(endpoint).hostname not in ("127.0.0.1", "localhost", "::1") and not endpoint.startswith("https://"):
        raise ValueError("Remote bridge requires HTTPS")
    payload = json.dumps(dict(jsonrpc="2.0", id=1, method=method, params=params)).encode()
    request = urllib.request.Request(endpoint.rstrip("/") + "/mdxp", payload,
                                     {"Content-Type": "application/json", "Authorization": "Bearer " + token})
    with opener().open(request, timeout=10) as response:
        result = json.load(response)
    if "error" in result:
        raise ValueError("Motrix RPC rejected request (code %s)" % result["error"].get("code"))
    return result["result"]


def probe(url, proxy=""):
    request = urllib.request.Request(http_url(url), headers={"Range": "bytes=0-1048575", "Accept-Encoding": "identity"})
    start = time.monotonic()
    try:
        with opener(proxy).open(request, timeout=5) as response:
            ttfb = time.monotonic() - start
            received = 0
            while received < 1048576 and time.monotonic() - start < 5:
                chunk = response.read1(min(65536, 1048576 - received))
                if not chunk:
                    break
                received += len(chunk)
            elapsed = time.monotonic() - start
            cr = response.headers.get("Content-Range", "")
            match = re.fullmatch(r"bytes 0-(\d+)/(\d+)", cr)
            total = int(match[2]) if match else None
            ranged = response.status == 206 and bool(match) and total > 0 and int(match[1]) == min(1048575, total - 1)
            if total is None and response.status == 200:
                length = response.headers.get("Content-Length", "")
                total = int(length) if length.isdigit() else None
            connections = 1 if not ranged or total is None or total < 32 * 1024**2 else (4 if total < 256 * 1024**2 else 8)
            return dict(status=response.status, range_supported=ranged, total_bytes=total,
                        sample_bytes=received, elapsed_seconds=round(elapsed, 4),
                        ttfb_seconds=round(ttfb, 4), sample_Bps=round(received / max(elapsed, .001)),
                        suggested_initial_connections=connections,
                        note="Heuristic only. Repeat samples; compare 1/4/8 connections on actual authorized tasks. No live connection tuning via MDXP.")
    except urllib.error.HTTPError as exc:
        return dict(status=exc.code, retry_after=exc.headers.get("Retry-After"),
                    note="401/403: refresh authorized URL; 429: wait; do not multiply connections or retry blindly.")


def call(name, args):
    validate(name, args)
    if name == "motrix_stats":
        return bridge("stats/get", {})
    if name == "motrix_list":
        return bridge("task/list", {"limit": 100, "offset": 0})
    if name == "motrix_get":
        return bridge("task/get", {"taskId": args["task_id"]})
    if name in ("motrix_pause", "motrix_resume"):
        return bridge("task/" + name.removeprefix("motrix_"), {"taskId": args["task_id"]})
    if name == "motrix_add":
        if not Path(args["save_dir"]).is_absolute():
            raise ValueError("save_dir must be absolute")
        filename = args.get("filename")
        if filename is not None and (not filename or filename in (".", "..") or "/" in filename or "\\" in filename):
            raise ValueError("filename must be a single basename")
        params = dict(kind="url", uris=[http_url(args["url"])], saveDir=args["save_dir"], connections=args.get("connections", 4))
        if filename is not None:
            params["filename"] = filename
        if "proxy" in args:
            if args["proxy"]:
                http_url(args["proxy"])
            params["proxy"] = args["proxy"]
        return bridge("download/add", params)
    if name == "download_probe":
        return probe(**args)
    if name == "verify_sha256":
        if not re.fullmatch(r"[0-9a-fA-F]{64}", args["sha256"]):
            raise ValueError("Expected 64 hex digits")
        path = Path(args["path"])
        if not path.is_absolute() or not path.is_file():
            raise ValueError("Expected absolute regular file path")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return dict(sha256=digest, matches=digest == args["sha256"].lower(), bytes=path.stat().st_size)


def handle(message):
    method = message.get("method")
    if "id" not in message:
        return None
    result = {}
    if method == "initialize":
        version = message.get("params", {}).get("protocolVersion")
        result = dict(protocolVersion=version if version in ("2024-11-05", "2025-03-26", "2025-06-18") else "2024-11-05",
                      capabilities={"tools": {}}, serverInfo={"name": "motrix-agent", "version": "0.1.0"},
                      instructions="Only download user-requested resources. Read stats first. Probe authorized URLs and explicitly supplied proxies; repeat samples before comparing routes. Start with suggested connections, capped at 16. Short probe throughput is not sustained speed. Do not blindly retry 401/403/429. MDXP cannot change live connection counts: do not claim automatic runtime tuning. Queueing is not completion; list task status, then verify trusted SHA256 when supplied. Never delete files or pause unrelated tasks. Do not log signed URLs or credentials.")
    elif method == "tools/list":
        result = {"tools": [dict(name=n, description=d, inputSchema=s) for n, d, s in TOOLS]}
    elif method == "tools/call":
        try:
            p = message["params"]
            value = call(p["name"], p.get("arguments", {}))
            result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}
        except Exception as exc:
            # Never echo exception URLs, tokens, response bodies or arbitrary server messages.
            detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            result = {"isError": True, "content": [{"type": "text", "text": detail}]}
    elif method != "ping":
        return dict(jsonrpc="2.0", id=message["id"], error={"code": -32601, "message": "Method not found"})
    return dict(jsonrpc="2.0", id=message["id"], result=result)


def main():
    if len(sys.argv) > 1:
        if sys.argv[1:] == ["--list-tools"]:
            print(json.dumps([dict(name=n, description=d, inputSchema=s) for n, d, s in TOOLS], ensure_ascii=False))
            return
        if len(sys.argv) != 3 or sys.argv[1] != "--tool":
            print("Usage: server.py [--list-tools | --tool NAME < arguments.json]", file=sys.stderr)
            raise SystemExit(2)
        try:
            result = call(sys.argv[2], json.load(sys.stdin))
        except Exception as exc:
            print(json.dumps({"error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__}), file=sys.stderr)
            raise SystemExit(1) from None
        print(json.dumps(result, ensure_ascii=False))
        return
    for line in sys.stdin:
        try:
            result = handle(json.loads(line))
        except Exception:
            result = dict(jsonrpc="2.0", id=None, error={"code": -32700, "message": "Invalid request"})
        if result is not None:
            print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
