import base64
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "utils"))
from sub_merge import merge, base64_encode


class MergeFingerprintTests(unittest.TestCase):
    def setUp(self):
        self.merger = merge.__new__(merge)

    def vmess(self, **overrides):
        config = {
            "v": "2", "ps": "node", "add": "example.com", "port": "443",
            "id": "11111111-1111-1111-1111-111111111111", "aid": 0,
            "net": "tcp", "type": "none", "host": "", "path": "", "tls": ""
        }
        config.update(overrides)
        return "vmess://" + base64_encode(json.dumps(config, separators=(",", ":")))

    def test_vmess_remark_does_not_affect_fingerprint(self):
        self.assertEqual(self.merger.node_fingerprint(self.vmess(ps="A")),
                         self.merger.node_fingerprint(self.vmess(ps="B")))

    def test_vmess_transport_difference_is_preserved(self):
        self.assertNotEqual(self.merger.node_fingerprint(self.vmess(net="tcp")),
                            self.merger.node_fingerprint(self.vmess(net="ws")))

    def test_vless_transport_and_security_query_are_preserved(self):
        tcp = "vless://11111111-1111-1111-1111-111111111111@example.com:443?type=tcp&security=tls#A"
        ws = "vless://11111111-1111-1111-1111-111111111111@example.com:443?type=ws&security=tls#B"
        reality = "vless://11111111-1111-1111-1111-111111111111@example.com:443?type=tcp&security=reality&pbk=abc#C"
        self.assertNotEqual(self.merger.node_fingerprint(tcp), self.merger.node_fingerprint(ws))
        self.assertNotEqual(self.merger.node_fingerprint(tcp), self.merger.node_fingerprint(reality))

    def test_remark_only_difference_is_deduplicated(self):
        a = "trojan://secret@example.com:443?sni=one.example#A"
        b = "trojan://secret@example.com:443?sni=one.example#B"
        self.assertEqual(len(self.merger.deduplicate_nodes([a, b])), 1)

    def test_trojan_sni_difference_is_not_deduplicated(self):
        a = "trojan://secret@example.com:443?sni=a.example#A"
        b = "trojan://secret@example.com:443?sni=b.example#B"
        self.assertEqual(len(self.merger.deduplicate_nodes([a, b])), 2)

    def test_legacy_shadowsocks_uri_is_supported(self):
        legacy = base64.b64encode(b"aes-128-gcm:secret@example.com:8388").decode()
        link = "ss://" + legacy + "#legacy"
        self.assertIsNotNone(self.merger.node_fingerprint(link))

    def test_ssr_remark_does_not_affect_fingerprint(self):
        config = "example.com:443:origin:aes-256-cfb:plain:" + base64_encode("secret")
        a = "ssr://" + base64_encode(config + "/?remarks=" + base64_encode("A"))
        b = "ssr://" + base64_encode(config + "/?remarks=" + base64_encode("B"))
        self.assertEqual(self.merger.node_fingerprint(a), self.merger.node_fingerprint(b))

    def test_invalid_provider_regex_is_ignored(self):
        self.assertIsNone(self.merger._provider_name_matches("[", "node"))
        self.assertTrue(self.merger._provider_name_matches("HK|Hong Kong", "HK-01"))

    def test_provider_header_array_is_normalized(self):
        headers = self.merger._provider_headers({
            "Authorization": ["Bearer token", "ignored"],
            "X-Empty": [],
            "X-Number": 123
        })
        self.assertEqual(headers, {
            "Authorization": "Bearer token",
            "X-Number": "123"
        })


if __name__ == "__main__":
    unittest.main()
