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
        headers = self.merger._provider_headers({"header": {
            "Authorization": ["Bearer token", "ignored"],
            "X-Empty": [],
            "X-Number": 123
        }})
        self.assertEqual(headers, {
            "Authorization": "Bearer token",
            "X-Number": "123"
        })


class ClashVergeProtocolConversionTests(unittest.TestCase):
    def setUp(self):
        self.merger = merge.__new__(merge)

    def parse_link(self, link):
        from urllib.parse import urlsplit, parse_qs
        parsed = urlsplit(link)
        return parsed, parse_qs(parsed.query)

    def test_hysteria_v1_conversion_keeps_auth_and_transport_options(self):
        link = self.merger.clash_to_share_link({
            "type": "hysteria", "name": "HY1", "server": "hy.example.com",
            "port": 443, "auth-str": "secret token", "protocol": "udp",
            "sni": "sni.example.com", "up": "30 Mbps", "down": "100 Mbps",
            "obfs": "obfs-key", "ports": "20000-30000", "alpn": ["h3"]
        })
        parsed, query = self.parse_link(link)
        self.assertEqual(parsed.scheme, "hysteria")
        self.assertEqual(parsed.hostname, "hy.example.com")
        self.assertEqual(query["auth"], ["secret token"])
        self.assertEqual(query["protocol"], ["udp"])
        self.assertEqual(query["sni"], ["sni.example.com"])
        self.assertEqual(query["upmbps"], ["30 Mbps"])
        self.assertEqual(query["downmbps"], ["100 Mbps"])
        self.assertEqual(query["mport"], ["20000-30000"])
        self.assertEqual(query["alpn"], ["h3"])

    def test_tuic_conversion_keeps_credentials_and_options(self):
        link = self.merger.clash_to_share_link({
            "type": "tuic", "name": "TUIC", "server": "tuic.example.com",
            "port": 443, "uuid": "11111111-1111-1111-1111-111111111111",
            "password": "p@ss:word", "sni": "sni.example.com",
            "congestion-controller": "bbr", "udp-relay-mode": "native",
            "reduce-rtt": True, "alpn": ["h3"], "skip-cert-verify": True
        })
        parsed, query = self.parse_link(link)
        self.assertEqual(parsed.scheme, "tuic")
        self.assertEqual(parsed.username, "11111111-1111-1111-1111-111111111111")
        from urllib.parse import unquote
        self.assertEqual(unquote(parsed.password), "p@ss:word")
        self.assertEqual(query["congestion-controller"], ["bbr"])
        self.assertEqual(query["udp-relay-mode"], ["native"])
        self.assertEqual(query["reduce-rtt"], ["true"])
        self.assertEqual(query["skip-cert-verify"], ["1"])

    def test_anytls_conversion_keeps_tls_options(self):
        link = self.merger.clash_to_share_link({
            "type": "anytls", "name": "AnyTLS", "server": "any.example.com",
            "port": 443, "password": "secret", "sni": "sni.example.com",
            "client-fingerprint": "chrome", "alpn": ["h2", "http/1.1"],
            "skip-cert-verify": True, "idle-session-timeout": 45
        })
        parsed, query = self.parse_link(link)
        self.assertEqual(parsed.scheme, "anytls")
        self.assertEqual(parsed.username, "secret")
        self.assertEqual(query["sni"], ["sni.example.com"])
        self.assertEqual(query["client-fingerprint"], ["chrome"])
        self.assertEqual(query["alpn"], ["h2,http/1.1"])
        self.assertEqual(query["insecure"], ["1"])
        self.assertEqual(query["idle-session-timeout"], ["45"])

    def test_http_and_socks5_conversion_keep_auth_and_supported_options(self):
        http_link = self.merger.clash_to_share_link({
            "type": "http", "name": "HTTP", "server": "proxy.example.com",
            "port": 8080, "username": "user", "password": "p@ss",
            "tls": True, "skip-cert-verify": True
        })
        parsed, query = self.parse_link(http_link)
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.username, "user")
        from urllib.parse import unquote
        self.assertEqual(unquote(parsed.password), "p@ss")
        self.assertEqual(query["tls"], ["true"])
        self.assertEqual(query["skip-cert-verify"], ["true"])

        socks_link = self.merger.clash_to_share_link({
            "type": "socks5", "name": "SOCKS", "server": "proxy.example.com",
            "port": 1080, "username": "user", "password": "pass", "udp": True
        })
        parsed, query = self.parse_link(socks_link)
        self.assertEqual(parsed.scheme, "socks5")
        self.assertEqual(parsed.username, "user")
        self.assertEqual(parsed.password, "pass")
        self.assertEqual(query["udp"], ["true"])

    def test_http_does_not_silently_drop_custom_headers_or_sni(self):
        base = {"type": "http", "name": "HTTP", "server": "proxy.example.com", "port": 8080}
        self.assertIsNone(self.merger.clash_to_share_link({**base, "headers": {"Host": ["alt.example.com"]}}))
        self.assertIsNone(self.merger.clash_to_share_link({**base, "sni": "alt.example.com"}))

    def test_ipv6_hosts_are_bracketed_for_vless_trojan_and_ss(self):
        cases = [
            ({"type": "vless", "name": "V6", "server": "2001:db8::1", "port": 443,
              "uuid": "11111111-1111-1111-1111-111111111111"}, "vless://", "@[2001:db8::1]:443"),
            ({"type": "trojan", "name": "V6", "server": "2001:db8::1", "port": 443,
              "password": "secret"}, "trojan://", "@[2001:db8::1]:443"),
            ({"type": "ss", "name": "V6", "server": "2001:db8::1", "port": 8388,
              "password": "secret", "cipher": "aes-128-gcm"}, "ss://", "@[2001:db8::1]:8388"),
        ]
        for proxy, prefix, host_port in cases:
            with self.subTest(protocol=proxy["type"]):
                link = self.merger.clash_to_share_link(proxy)
                self.assertTrue(link.startswith(prefix))
                self.assertIn(host_port, link)
                self.assertIsNotNone(self.merger.node_fingerprint(link))

    def test_string_false_is_false_for_anytls_and_socks_udp(self):
        anytls = self.merger.clash_to_share_link({
            "type": "anytls", "server": "any.example.com", "port": 443,
            "password": "secret", "udp": "false"
        })
        socks = self.merger.clash_to_share_link({
            "type": "socks5", "server": "proxy.example.com", "port": 1080,
            "udp": "false"
        })
        self.assertIn("udp=false", anytls)
        self.assertIn("udp=false", socks)

    def test_ss_plugin_options_are_rejected_to_prevent_loss(self):
        base = {"type": "ss", "server": "ss.example.com", "port": 8388,
                "password": "secret", "cipher": "aes-128-gcm"}
        self.assertIsNone(self.merger.clash_to_share_link({**base, "plugin": "obfs-local"}))
        self.assertIsNone(self.merger.clash_to_share_link({**base, "plugin-opts": {"mode": "tls"}}))

    def test_conversion_failure_reason_is_recorded(self):
        proxy = {"type": "http", "server": "proxy.example.com", "port": 8080,
                 "headers": {"Host": ["alt.example.com"]}}
        self.assertIsNone(self.merger.clash_to_share_link(proxy))
        self.assertEqual(self.merger._last_conversion_failure_reason, "unsupported_headers")

    def test_wireguard_single_peer_conversion_keeps_keys_and_network_fields(self):
        link = self.merger.clash_to_share_link({
            "type": "wireguard", "name": "WG", "server": "wg.example.com",
            "port": 51820, "private-key": "client-private", "ip": "10.0.0.2/32",
            "ipv6": "fd00::2/128", "mtu": 1420, "dns": ["1.1.1.1"],
            "peers": [{
                "public-key": "server-public", "allowed-ips": ["0.0.0.0/0"],
                "pre-shared-key": "psk", "reserved": [1, 2, 3]
            }]
        })
        parsed, query = self.parse_link(link)
        self.assertEqual(parsed.scheme, "wireguard")
        self.assertEqual(parsed.username, "client-private")
        self.assertEqual(parsed.hostname, "wg.example.com")
        self.assertEqual(parsed.port, 51820)
        self.assertEqual(query["publickey"], ["server-public"])
        self.assertEqual(query["address"], ["10.0.0.2/32,fd00::2/128"])
        self.assertEqual(query["allowed-ips"], ["0.0.0.0/0"])
        self.assertEqual(query["pre-shared-key"], ["psk"])
        self.assertEqual(query["reserved"], ["1,2,3"])
        self.assertEqual(query["mtu"], ["1420"])

    def test_wireguard_multiple_peers_are_rejected_instead_of_losing_peers(self):
        self.assertIsNone(self.merger.clash_to_share_link({
            "type": "wireguard", "server": "wg.example.com", "port": 51820,
            "private-key": "client-private",
            "peers": [{"public-key": "one"}, {"public-key": "two"}]
        }))

    def test_new_protocol_links_have_stable_fingerprints(self):
        links = [
            "hysteria://hy.example.com:443/?auth=secret&protocol=udp#A",
            "tuic://11111111-1111-1111-1111-111111111111:secret@tuic.example.com:443/?sni=a.example#A",
            "anytls://secret@any.example.com:443/?sni=a.example#A",
            "http://user:pass@proxy.example.com:8080/?tls=true#A",
            "socks5://user:pass@proxy.example.com:1080/?udp=true#A",
            "wireguard://private-key@wg.example.com:51820/?publickey=public-key&address=10.0.0.2/32#A",
        ]
        for link in links:
            with self.subTest(link=link):
                self.assertIsNotNone(self.merger.node_fingerprint(link))
                renamed = link.rsplit("#", 1)[0] + "#renamed"
                self.assertEqual(self.merger.node_fingerprint(link),
                                 self.merger.node_fingerprint(renamed))



if __name__ == "__main__":
    unittest.main()
