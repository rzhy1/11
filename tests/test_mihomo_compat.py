#!/usr/bin/env python3
"""Check generated URI subscriptions against a running Mihomo core."""

import json
import os
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request

import yaml
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "utils"))
from sub_merge import merge


class MihomoShareLinkCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mihomo = os.environ.get("MIHOMO_BIN")
        if not cls.mihomo:
            raise unittest.SkipTest("MIHOMO_BIN is not configured")

        merger = merge.__new__(merge)
        fixtures = [
            {
                "type": "snell", "name": "Snell compatibility",
                "server": "snell.example.com", "port": 44046,
                "psk": "snell-secret", "version": 4,
            },
            {
                "type": "hysteria2", "name": "Hysteria2 compatibility",
                "server": "hy2.example.com", "port": 443,
                "password": "hy2-secret", "sni": "hy2.example.com",
            },
            {
                "type": "tuic", "name": "TUIC compatibility",
                "server": "tuic.example.com", "port": 443,
                "uuid": "11111111-1111-1111-1111-111111111111",
                "password": "tuic-secret", "sni": "tuic.example.com",
                "congestion-controller": "bbr", "udp-relay-mode": "native",
            },
            {
                "type": "vless", "name": "VLESS XHTTP compatibility",
                "server": "vless.example.com", "port": 443,
                "uuid": "11111111-1111-1111-1111-111111111111",
                "tls": True, "servername": "vless.example.com",
                "network": "xhttp",
                "xhttp-opts": {
                    "path": "/upload", "host": "cdn.example.com",
                    "mode": "packet-up",
                    "extra": {"xPaddingBytes": "100-1000", "noGRPCHeader": True},
                    "x-padding-bytes": "100-1000",
                },
            },
            {
                "type": "mieru", "name": "Mieru compatibility",
                "server": "mieru.example.com", "port-range": "20000-20010",
                "transport": "TCP", "username": "mieru-user",
                "password": "mieru-secret",
            },
        ]
        cls.links = []
        cls.expected_names = []
        for proxy in fixtures:
            link = merger.clash_to_share_link(proxy)
            if not link:
                raise AssertionError(
                    f"Conversion failed for {proxy['type']}: "
                    f"{merger._last_conversion_failure_reason}"
                )
            cls.links.append(link)
            cls.expected_names.append(proxy["name"])

    def test_generated_share_links_are_loaded_by_mihomo(self):
        with tempfile.TemporaryDirectory(prefix="mihomo-compat-") as home:
            provider_path = os.path.join(home, "nodes.txt")
            config_path = os.path.join(home, "config.yaml")
            api_port = 19091

            with open(provider_path, "w", encoding="utf-8", newline="\n") as file:
                file.write("\n".join(self.links) + "\n")

            config = {
                "mixed-port": 17891,
                "mode": "rule",
                "log-level": "silent",
                "external-controller": f"127.0.0.1:{api_port}",
                "proxy-providers": {
                    "compatibility": {"type": "file", "path": "./nodes.txt"}
                },
                "proxy-groups": [{
                    "name": "COMPATIBILITY",
                    "type": "select",
                    "use": ["compatibility"],
                    "proxies": ["DIRECT"],
                }],
                "rules": ["MATCH,COMPATIBILITY"],
            }
            with open(config_path, "w", encoding="utf-8") as file:
                yaml.safe_dump(config, file, allow_unicode=True, sort_keys=False)

            process = subprocess.Popen(
                [self.mihomo, "-d", home, "-f", config_path],
                cwd=home, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                endpoint = f"http://127.0.0.1:{api_port}/providers/proxies/compatibility"
                deadline = time.monotonic() + 25
                loaded = None
                last_error = None
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        output = process.stdout.read() if process.stdout else ""
                        self.fail(
                            f"Mihomo exited with {process.returncode}:\n{output}"
                        )
                    try:
                        with urllib.request.urlopen(endpoint, timeout=2) as response:
                            loaded = json.loads(response.read().decode("utf-8"))
                        break
                    except (OSError, urllib.error.URLError, TimeoutError) as error:
                        last_error = error
                        time.sleep(0.25)

                self.assertIsNotNone(
                    loaded, f"Mihomo provider API did not become ready: {last_error}"
                )
                actual_names = {
                    item.get("name") for item in loaded.get("proxies", [])
                    if isinstance(item, dict)
                }
                # Mihomo's URI provider parser does not import Snell share links;
                # Snell remains a client-specific link format (for example Potatso).
                mihomo_supported_names = {
                    "Hysteria2 compatibility",
                    "TUIC compatibility",
                    "VLESS XHTTP compatibility",
                }
                self.assertTrue(
                    mihomo_supported_names.issubset(actual_names),
                    "Mihomo failed to load supported generated URIs. "
                    f"Loaded={sorted(actual_names)}",
                )
                mieru_names = {
                    name for name in actual_names
                    if isinstance(name, str) and name.startswith("Mieru compatibility:")
                }
                self.assertEqual(
                    len(mieru_names), 1,
                    "Mihomo should load Mieru and derive its displayed name from "
                    f"the port range/transport; loaded={sorted(actual_names)}",
                )
                self.assertFalse(
                    "Snell compatibility" in actual_names,
                    "Mihomo unexpectedly accepted Snell URI; review the parser "
                    "compatibility expectation if support has been added.",
                )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
