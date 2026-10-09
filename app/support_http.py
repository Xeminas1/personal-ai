from __future__ import annotations

from http import HTTPStatus
import re
from urllib.parse import parse_qs, urlparse

from . import support_access


def support_endpoints(root) -> list[str]:
    from .hybrid_autosetup import _tailscale_exe, _tailscale_json, _serve_status
    ts = _tailscale_exe()
    data = _tailscale_json(ts, "status", "--json") if ts else None
    dns = str(((data or {}).get("Self") or {}).get("DNSName") or "").rstrip(".")
    if not re.fullmatch(r"[A-Za-z0-9.-]+\.ts\.net", dns):
        return []
    config = support_access.safe_config(root)
    serve = _serve_status(ts) if ts else ""
    result = []
    if str(config.get("mobile_server_port", 8765)) in serve:
        result.append(f"https://{dns}/api/support")
    worker_port = config.get("hybrid_worker_port", 8766)
    if str(worker_port) in serve:
        result.append(f"https://{dns}:{worker_port}/api/support")
    return result


def handle_support_read(handler, root) -> bool:
    parsed = urlparse(handler.path)
    if not parsed.path.startswith("/api/support/"):
        return False
    supplied = handler.headers.get("Authorization", "")
    token = supplied.removeprefix("Bearer ") if supplied.startswith("Bearer ") else ""
    if not support_access.authorized(root, token):
        handler._error("Live support is disabled, expired, or the key is invalid.", HTTPStatus.UNAUTHORIZED)
        return True
    try:
        if parsed.path == "/api/support/files" and not parsed.query:
            handler._json({"ok": True, "files": support_access.list_files(root)})
        elif parsed.path == "/api/support/report" and not parsed.query:
            from .hybrid_autosetup import _tailscale_exe, _tailscale_json, _serve_status
            report = support_access.get_report(root)
            ts = _tailscale_exe()
            data = _tailscale_json(ts, "status", "--json") if ts else None
            serve = _serve_status(ts) if ts else ""
            own = (data or {}).get("Self") or {}
            peers = (data or {}).get("Peer") or (data or {}).get("Peers") or {}
            report["tailscale"] = {
                "executable_found": bool(ts), "status_available": data is not None,
                "identity_available": bool(own.get("DNSName")),
                "mobile_route_found": "8765" in serve,
                "worker_route_found": "8766" in serve,
                "online_peer_count": sum(bool(p.get("Online")) for p in peers.values() if isinstance(p, dict)) if isinstance(peers, dict) else 0,
            }
            handler._json({"ok": True, "report": report})
        elif parsed.path == "/api/support/file":
            query = parse_qs(parsed.query, keep_blank_values=True)
            if set(query) != {"path"} or len(query["path"]) != 1:
                raise ValueError("Specify one supported relative file path.")
            handler._json({"ok": True, "file": support_access.read_file(root, query["path"][0])})
        else:
            handler._error("Unknown read-only support endpoint.", HTTPStatus.NOT_FOUND)
    except (ValueError, OSError) as error:
        handler._error("This file is unavailable or outside the support scope.", HTTPStatus.BAD_REQUEST)
    return True
