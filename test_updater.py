"""Mutable manifest freshness keeps verified release downloads unchanged."""
from __future__ import annotations

import hashlib
import io
import json
import ssl
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from app import updater


ASSET_URL = "https://raw.githubusercontent.com/Xeminas1/personal-ai/0123456789abcdef0123456789abcdef01234567/main.py"
NEW_PROGRAM = b"print('updated program')\n"


def file_manifest(version="999.0.0"):
    return {"version": version, "files": [{
        "path": "main.py", "url": ASSET_URL,
        "sha256": hashlib.sha256(NEW_PROGRAM).hexdigest(),
    }]}


class CachingManifestOrigin:
    """Models a raw CDN that retains each URL's first response after publishing."""

    def __init__(self):
        self.current_manifest = file_manifest(updater.VERSION)
        self.cache = {}
        self.requests = []

    def __call__(self, request, *, timeout, context):
        self.requests.append((request, timeout, context))
        payload = self.cache.setdefault(request.full_url, json.dumps(self.current_manifest).encode())
        return io.BytesIO(payload)


class UpdaterTests(unittest.TestCase):
    def assert_tls_verified(self, context):
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    @staticmethod
    def headers(request):
        return {name.lower(): value for name, value in request.header_items()}

    def test_successive_github_checks_detect_publish_despite_url_cache(self):
        manifest_url = "https://raw.githubusercontent.com/Xeminas1/personal-ai/main/update_manifest.json?channel=stable&signed=a%2Fb%2Bc&empty=#section"
        origin = CachingManifestOrigin()
        with patch.object(updater.urllib.request, "urlopen", side_effect=origin):
            self.assertIsNone(updater.check_for_update(manifest_url))
            origin.current_manifest = file_manifest()
            update = updater.check_for_update(manifest_url)
        self.assertEqual(update["version"], "999.0.0")
        self.assertEqual(len(origin.requests), 2)
        first_url, second_url = (row[0].full_url for row in origin.requests)
        self.assertNotEqual(first_url, second_url)
        for request, timeout, context in origin.requests:
            parsed = urlsplit(request.full_url)
            self.assertEqual(parsed.hostname, "raw.githubusercontent.com")
            self.assertEqual(parsed.fragment, "section")
            self.assertTrue(parsed.query.startswith("channel=stable&signed=a%2Fb%2Bc&empty=&"))
            params = parse_qs(parsed.query, keep_blank_values=True)
            self.assertEqual(params["signed"], ["a/b+c"])
            self.assertEqual(params["empty"], [""])
            self.assertEqual(len(params["_xemai_check"]), 1)
            headers = self.headers(request)
            self.assertIn("no-cache", headers["cache-control"])
            self.assertIn("max-age=0", headers["cache-control"])
            self.assertEqual(headers["pragma"], "no-cache")
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(timeout, 20)
            self.assert_tls_verified(context)

    def test_custom_signed_and_lookalike_hosts_keep_exact_url(self):
        urls = (
            "https://updates.example.test/manifest.json?X-Amz-Signature=a%2Fb%2Bz&empty=#details",
            "https://raw.githubusercontent.com.example.test/manifest.json?token=a%2Fb#details",
            "https://raw.githubusercontent.com@updates.example.test/manifest.json?token=a%2Fb#details",
        )
        for manifest_url in urls:
            with self.subTest(url=manifest_url):
                captured = []

                def download(request, *, timeout, context):
                    captured.append(request)
                    self.assert_tls_verified(context)
                    return io.BytesIO(json.dumps(file_manifest()).encode())

                with patch.object(updater.urllib.request, "urlopen", side_effect=download):
                    self.assertEqual(updater.fetch_manifest(manifest_url)["version"], "999.0.0")
                self.assertEqual(captured[0].full_url, manifest_url)
                self.assertIn("no-cache", self.headers(captured[0])["cache-control"])

    def project(self, root):
        (root / "main.py").write_bytes(b"print('original program')\n")
        (root / "config.json").write_bytes(b'{"private_setting": "preserve"}\n')
        (root / "data").mkdir()
        (root / "data/personal_ai.db").write_bytes(b"private database fixture")
        (root / "logs").mkdir()
        (root / "logs/personal_ai.log").write_bytes(b"private log fixture")

    @staticmethod
    def snapshot(root):
        return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}

    def test_install_keeps_pinned_asset_request_and_preserves_user_files(self):
        requests = []

        def download(request, *, timeout, context):
            requests.append(request)
            self.assertEqual(request.full_url, ASSET_URL)
            self.assertEqual(timeout, 120)
            self.assert_tls_verified(context)
            self.assertNotIn("cache-control", self.headers(request))
            self.assertNotIn("pragma", self.headers(request))
            return io.BytesIO(NEW_PROGRAM)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.project(root)
            original = self.snapshot(root)
            with patch.object(updater.urllib.request, "urlopen", side_effect=download):
                self.assertEqual(updater.install_update(base_dir=root, manifest=file_manifest()), "999.0.0")
            self.assertEqual((root / "main.py").read_bytes(), NEW_PROGRAM)
            for path in ("config.json", "data/personal_ai.db", "logs/personal_ai.log"):
                self.assertEqual((root / path).read_bytes(), original[path])
        self.assertEqual(len(requests), 1)

    def test_asset_hash_mismatch_rejects_install_before_any_program_or_user_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.project(root)
            original = self.snapshot(root)
            with patch.object(updater.urllib.request, "urlopen", return_value=io.BytesIO(b"corrupt or stale asset")) as download:
                with self.assertRaisesRegex(updater.UpdateError, "SHA-256 mismatch"):
                    updater.install_update(base_dir=root, manifest=file_manifest())
            self.assertEqual(self.snapshot(root), original)
            self.assertFalse((root / ".update_backups").exists())
            request = download.call_args.args[0]
            self.assertEqual(request.full_url, ASSET_URL)
            self.assertNotIn("cache-control", self.headers(request))
            self.assert_tls_verified(download.call_args.kwargs["context"])

    def test_manifest_and_asset_https_requirements_remain_enforced(self):
        with patch.object(updater.urllib.request, "urlopen") as download:
            with self.assertRaisesRegex(updater.UpdateError, "HTTPS"):
                updater.fetch_manifest("http://updates.example.test/manifest.json")
            with self.assertRaisesRegex(updater.UpdateError, "HTTPS"):
                updater._https_bytes("http://updates.example.test/source.py")
            download.assert_not_called()
        insecure_manifest = file_manifest()
        insecure_manifest["files"][0]["url"] = "http://updates.example.test/source.py"
        with patch.object(updater.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(insecure_manifest).encode())):
            with self.assertRaisesRegex(updater.UpdateError, "HTTPS"):
                updater.fetch_manifest("https://updates.example.test/manifest.json")


if __name__ == "__main__":
    unittest.main()
