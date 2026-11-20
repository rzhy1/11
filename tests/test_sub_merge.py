import base64
import json
import os
import sys
import unittest
import tempfile
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "utils"))
from sub_merge import merge, base64_encode
import sub_merge


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

    def test_vless_flow_and_reality_key_are_part_of_fingerprint(self):
        base = "vless://11111111-1111-1111-1111-111111111111@example.com:443?security=reality&pbk=key-a&flow=xtls-rprx-vision"
        flow_changed = base.replace("xtls-rprx-vision", "none")
        key_changed = base.replace("key-a", "key-b")
        self.assertNotEqual(self.merger.node_fingerprint(base),
                            self.merger.node_fingerprint(flow_changed))
        self.assertNotEqual(self.merger.node_fingerprint(base),
                            self.merger.node_fingerprint(key_changed))

    def test_trojan_password_is_part_of_fingerprint(self):
        a = "trojan://password-a@example.com:443?sni=sni.example"
        b = "trojan://password-b@example.com:443?sni=sni.example"
        self.assertNotEqual(self.merger.node_fingerprint(a),
                            self.merger.node_fingerprint(b))

    def test_hysteria_v1_auth_and_options_are_part_of_fingerprint(self):
        base = "hysteria://hy.example.com:443/?auth=secret&sni=a.example&protocol=udp"
        auth_changed = base.replace("auth=secret", "auth=other")
        sni_changed = base.replace("sni=a.example", "sni=b.example")
        self.assertNotEqual(self.merger.node_fingerprint(base),
                            self.merger.node_fingerprint(auth_changed))
        self.assertNotEqual(self.merger.node_fingerprint(base),
                            self.merger.node_fingerprint(sni_changed))

    def test_hysteria2_password_and_options_are_part_of_fingerprint(self):
        base = "hysteria2://secret@example.com:443/?sni=a.example&obfs=salamander"
        password_changed = base.replace("secret@", "other@")
        obfs_changed = base.replace("salamander", "other")
        self.assertNotEqual(self.merger.node_fingerprint(base),
                            self.merger.node_fingerprint(password_changed))
        self.assertNotEqual(self.merger.node_fingerprint(base),
                            self.merger.node_fingerprint(obfs_changed))

    def test_tuic_credentials_and_options_are_part_of_fingerprint(self):
        base = "tuic://uuid:password@example.com:443/?sni=a.example&congestion-controller=bbr"
        password_changed = base.replace(":password@", ":other@")
        mode_changed = base.replace("bbr", "cubic")
        self.assertNotEqual(self.merger.node_fingerprint(base),
                            self.merger.node_fingerprint(password_changed))
        self.assertNotEqual(self.merger.node_fingerprint(base),
                            self.merger.node_fingerprint(mode_changed))

    def test_anytls_password_and_tls_options_are_part_of_fingerprint(self):
        base = "anytls://secret@example.com:443/?sni=a.example&client-fingerprint=chrome"
        password_changed = base.replace("secret@", "other@")
        fingerprint_changed = base.replace("chrome", "firefox")
        self.assertNotEqual(self.merger.node_fingerprint(base),
                            self.merger.node_fingerprint(password_changed))
        self.assertNotEqual(self.merger.node_fingerprint(base),
                            self.merger.node_fingerprint(fingerprint_changed))

    def test_query_order_does_not_change_fingerprint(self):
        a = "vless://11111111-1111-1111-1111-111111111111@example.com:443?type=ws&security=tls&host=cdn.example.com"
        b = "vless://11111111-1111-1111-1111-111111111111@example.com:443?host=cdn.example.com&security=tls&type=ws"
        self.assertEqual(self.merger.node_fingerprint(a),
                         self.merger.node_fingerprint(b))

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

    def test_ss_base64_userinfo_and_plain_credentials_are_equivalent(self):
        encoded = base64.b64encode(b"aes-128-gcm:secret").decode("ascii")
        encoded_link = f"ss://{encoded}@ss.example.com:8388#A"
        plain_link = "ss://aes-128-gcm:secret@ss.example.com:8388#B"
        self.assertEqual(self.merger.node_fingerprint(encoded_link),
                         self.merger.node_fingerprint(plain_link))

    def test_ss_plugin_options_are_part_of_fingerprint(self):
        base = "ss://aes-128-gcm:secret@ss.example.com:8388"
        a = base + "?plugin=obfs-local%3Bmode%3Dhttp#A"
        b = base + "?plugin=obfs-local%3Bmode%3Dtls#B"
        self.assertNotEqual(self.merger.node_fingerprint(a),
                            self.merger.node_fingerprint(b))

    def test_ssr_protocol_parameters_are_part_of_fingerprint(self):
        config = "example.com:443:origin:aes-256-cfb:plain:" + base64_encode("secret")
        a = "ssr://" + base64_encode(config + "/?obfsparam=" + base64_encode("a.example"))
        b = "ssr://" + base64_encode(config + "/?obfsparam=" + base64_encode("b.example"))
        self.assertNotEqual(self.merger.node_fingerprint(a),
                            self.merger.node_fingerprint(b))

    def test_query_parameter_names_preserve_case(self):
        a = "vless://11111111-1111-1111-1111-111111111111@example.com:443?Foo=1"
        b = "vless://11111111-1111-1111-1111-111111111111@example.com:443?foo=1"
        self.assertNotEqual(self.merger.node_fingerprint(a),
                            self.merger.node_fingerprint(b))

    def test_explicit_default_port_equals_omitted_port(self):
        a = "https://proxy.example.com/"
        b = "https://proxy.example.com:443/"
        self.assertEqual(self.merger.node_fingerprint(a),
                         self.merger.node_fingerprint(b))

    def test_zero_port_does_not_alias_default_port(self):
        a = "https://proxy.example.com:0/"
        b = "https://proxy.example.com:443/"
        self.assertNotEqual(self.merger.node_fingerprint(a),
                            self.merger.node_fingerprint(b))

    def test_wireguard_peer_key_and_allowed_ips_are_part_of_fingerprint(self):
        base = "wireguard://private@wg.example.com:51820/?publickey=server&address=10.0.0.2%2F32"
        allowed_a = base + "&allowed-ips=0.0.0.0%2F0"
        allowed_b = base + "&allowed-ips=10.0.0.0%2F8"
        key_b = base.replace("publickey=server", "publickey=other")
        self.assertNotEqual(self.merger.node_fingerprint(allowed_a),
                            self.merger.node_fingerprint(allowed_b))
        self.assertNotEqual(self.merger.node_fingerprint(base),
                            self.merger.node_fingerprint(key_b))

    def test_socks5_credentials_are_part_of_fingerprint(self):
        a = "socks5://user:pass@proxy.example.com:1080"
        b = "socks5://user:other@proxy.example.com:1080"
        self.assertNotEqual(self.merger.node_fingerprint(a),
                            self.merger.node_fingerprint(b))

    def test_invalid_provider_regex_is_ignored(self):
        self.assertIsNone(self.merger._provider_name_matches("[", "node"))
        self.assertTrue(self.merger._provider_name_matches("HK|Hong Kong", "HK-01"))

    def test_provider_filters_apply_include_exclude_and_protocol_rules(self):
        provider = {
            "filter": "(?i)HK|SG",
            "exclude_filter": "(?i)test|expire",
            "exclude_type": ["ss", "ssr"]
        }
        self.assertTrue(self.merger._provider_proxy_allowed(
            {"name": "HK-01", "type": "vless"}, provider
        ))
        self.assertFalse(self.merger._provider_proxy_allowed(
            {"name": "US-01", "type": "vless"}, provider
        ))
        self.assertFalse(self.merger._provider_proxy_allowed(
            {"name": "HK-test", "type": "vless"}, provider
        ))
        self.assertFalse(self.merger._provider_proxy_allowed(
            {"name": "HK-02", "type": "ss"}, provider
        ))

    def test_provider_rename_rules_run_before_prefix_and_suffix(self):
        provider = {
            "proxy_name": [
                {"pattern": "^(HK)-(\\d+)$", "target": "$2-$1"}
            ],
            "additional_prefix": "P-",
            "additional_suffix": "-S"
        }
        self.assertEqual(
            self.merger._provider_node_name("HK-01", provider),
            "P-01-HK-S"
        )

    def test_provider_invalid_filter_regex_does_not_drop_nodes(self):
        provider = {"filter": "[", "exclude_filter": "["}
        self.assertTrue(self.merger._provider_proxy_allowed(
            {"name": "HK-01", "type": "vless"}, provider
        ))

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

    def test_valid_port_accepts_only_decimal_range_without_whitespace(self):
        valid = [1, 443, 65535, "1", "443", "65535"]
        invalid = [None, True, False, 0, 65536, -1, 1.0, "0", "65536",
                   " 443", "443 ", "44 3", "+443", "4.43", ""]
        for value in valid:
            with self.subTest(value=value):
                self.assertTrue(self.merger._valid_port(value))
        for value in invalid:
            with self.subTest(value=value):
                self.assertFalse(self.merger._valid_port(value))

    def test_wireguard_peer_level_endpoint_is_converted_and_validated(self):
        link = self.merger.clash_to_share_link({
            "type": "wireguard", "name": "WG peer endpoint",
            "private-key": "client-private", "ip": "10.0.0.2/32",
            "peers": [{
                "server": "wg-peer.example.com", "port": 51820,
                "public-key": "server-public", "allowed-ips": ["0.0.0.0/0"]
            }]
        })
        parsed, query = self.parse_link(link)
        self.assertEqual(parsed.hostname, "wg-peer.example.com")
        self.assertEqual(parsed.port, 51820)
        self.assertEqual(query["publickey"], ["server-public"])

    def test_wireguard_invalid_peer_port_is_classified(self):
        proxy = {
            "type": "wireguard", "name": "WG invalid port",
            "private-key": "client-private",
            "peers": [{
                "server": "wg-peer.example.com", "port": " 51820",
                "public-key": "server-public"
            }]
        }
        self.assertIsNone(self.merger.clash_to_share_link(proxy))
        self.assertEqual(self.merger._last_conversion_failure_reason, "invalid_port")

    def parse_link(self, link):
        from urllib.parse import urlsplit, parse_qs
        parsed = urlsplit(link)
        return parsed, parse_qs(parsed.query)

    def test_hysteria_v1_conversion_keeps_auth_and_transport_options(self):
        link = self.merger.clash_to_share_link({
            "type": "hysteria", "name": "HY1", "server": "hy.example.com",
            "port": 443, "auth-str": "secret token", "protocol": "udp",
            "sni": "sni.example.com", "up": "30 Mbps", "down": "100 Mbps",
            "obfs": "obfs-key", "alpn": ["h3"]
        })
        parsed, query = self.parse_link(link)
        self.assertEqual(parsed.scheme, "hysteria")
        self.assertEqual(parsed.hostname, "hy.example.com")
        self.assertEqual(query["auth"], ["secret token"])
        self.assertEqual(query["protocol"], ["udp"])
        self.assertEqual(query["peer"], ["sni.example.com"])
        self.assertEqual(query["upmbps"], ["30"])
        self.assertEqual(query["downmbps"], ["100"])
        self.assertEqual(query["obfs"], ["xplus"])
        self.assertEqual(query["obfsParam"], ["obfs-key"])
        self.assertNotIn("sni", query)
        self.assertNotIn("mport", query)
        self.assertEqual(query["alpn"], ["h3"])

    def test_tuic_conversion_keeps_credentials_and_standard_uri_options(self):
        link = self.merger.clash_to_share_link({
            "type": "tuic", "name": "TUIC", "server": "tuic.example.com",
            "port": 443, "uuid": "11111111-1111-1111-1111-111111111111",
            "password": "p@ss:word", "sni": "sni.example.com",
            "congestion-controller": "bbr", "udp-relay-mode": "native",
            "reduce-rtt": True, "alpn": ["h3"], "skip-cert-verify": True,
            "disable-sni": True, "heartbeat-interval": 10000,
            "fast-open": True, "max-open-streams": 32
        })
        parsed, query = self.parse_link(link)
        self.assertEqual(parsed.scheme, "tuic")
        self.assertEqual(parsed.username, "11111111-1111-1111-1111-111111111111")
        from urllib.parse import unquote
        self.assertEqual(unquote(parsed.password), "p@ss:word")
        self.assertEqual(query["congestion_control"], ["bbr"])
        self.assertEqual(query["udp_relay_mode"], ["native"])
        self.assertEqual(query["reduce_rtt"], ["true"])
        self.assertEqual(query["allow_insecure"], ["1"])
        self.assertEqual(query["disable_sni"], ["true"])
        self.assertEqual(query["heartbeat_interval"], ["10000"])
        self.assertEqual(query["fast_open"], ["true"])
        self.assertEqual(query["max_open_streams"], ["32"])

    def test_tuic_v4_token_auth_is_supported_and_mixed_auth_is_rejected(self):
        link = self.merger.clash_to_share_link({
            "type": "tuic", "name": "TUIC v4", "server": "tuic.example.com",
            "port": 443, "token": "legacy-token"
        })
        parsed, _ = self.parse_link(link)
        self.assertEqual(parsed.username, "legacy-token")
        self.assertIsNone(self.merger.clash_to_share_link({
            "type": "tuic", "server": "tuic.example.com", "port": 443,
            "token": "token", "uuid": "uuid", "password": "password"
        }))

    def test_snell_conversion_keeps_portable_fields(self):
        link = self.merger.clash_to_share_link({
            "type": "snell", "name": "Snell", "server": "snell.example.com",
            "port": 44046, "psk": "p@ss word", "version": 4,
            "obfs-opts": {"mode": "http", "host": "cdn.example.com"}
        })
        parsed, query = self.parse_link(link)
        from urllib.parse import unquote
        self.assertEqual(parsed.scheme, "snell")
        self.assertEqual(unquote(parsed.username), "p@ss word")
        self.assertEqual(parsed.port, 44046)
        self.assertEqual(query["version"], ["4"])
        self.assertEqual(query["obfs"], ["http"])
        self.assertEqual(query["obfs-host"], ["cdn.example.com"])

    def test_snell_rejects_unrepresentable_or_invalid_options(self):
        base = {"type": "snell", "server": "snell.example.com",
                "port": 44046, "psk": "secret", "version": 4}
        self.assertIsNone(self.merger.clash_to_share_link({**base, "udp": True}))
        self.assertIsNone(self.merger.clash_to_share_link({
            **base, "obfs-opts": {"mode": "shadow-tls", "host": "cdn.example.com"}
        }))
        self.assertIsNone(self.merger.clash_to_share_link({
            **base, "obfs-opts": {"mode": "tls"}
        }))
        self.assertIsNone(self.merger.clash_to_share_link({**base, "version": 7}))

    def test_snell_rejects_version_incompatible_obfuscation(self):
        base = {"type": "snell", "server": "snell.example.com",
                "port": 44046, "psk": "secret"}
        self.assertIsNone(self.merger.clash_to_share_link({
            **base, "version": 2, "obfs-opts": {"mode": "http"}
        }))
        self.assertIsNone(self.merger.clash_to_share_link({
            **base, "version": 4, "obfs-opts": {"mode": "tls"}
        }))
        self.assertIsNone(self.merger.clash_to_share_link({
            **base, "version": True
        }))
        link = self.merger.clash_to_share_link({
            **base, "version": 4, "udp": "false", "reuse": "false",
            "mode": "default"
        })
        self.assertTrue(link.startswith("snell://"))

    def test_snell_auth_version_and_obfs_are_part_of_fingerprint(self):
        base = "snell://secret@snell.example.com:44046?version=4&obfs=http&obfs-host=cdn.example.com"
        self.assertNotEqual(self.merger.node_fingerprint(base),
                            self.merger.node_fingerprint(base.replace("secret@", "other@")))
        self.assertNotEqual(self.merger.node_fingerprint(base),
                            self.merger.node_fingerprint(base.replace("version=4", "version=5")))
        self.assertNotEqual(self.merger.node_fingerprint(base),
                            self.merger.node_fingerprint(base.replace("obfs=http", "obfs=tls")))

    def test_hysteria2_port_hopping_and_tls_pin_are_preserved(self):
        link = self.merger.clash_to_share_link({
            "type": "hysteria2", "name": "HY2", "server": "hy2.example.com",
            "ports": "443,20000-20010", "password": "secret",
            "sni": "sni.example.com", "fingerprint": "sha256-pin",
            "obfs": "gecko", "obfs-password": "obfs-secret",
            "skip-cert-verify": True, "alpn": ["h3"]
        })
        parsed, query = self.parse_link(link)
        self.assertEqual(parsed.scheme, "hysteria2")
        self.assertEqual(parsed.netloc.split("@", 1)[1], "hy2.example.com:443,20000-20010")
        self.assertEqual(query["pinSHA256"], ["sha256-pin"])
        self.assertEqual(query["obfs"], ["gecko"])
        self.assertEqual(query["insecure"], ["1"])
        self.assertEqual(query["sni"], ["sni.example.com"])

    def test_hysteria2_port_hopping_fingerprint_is_stable_and_distinct(self):
        a = "hysteria2://secret@hy2.example.com:443,20000-20010/?sni=hy2.example.com"
        b = "hysteria2://secret@hy2.example.com:443,20000-20020/?sni=hy2.example.com"
        self.assertNotEqual(self.merger.node_fingerprint(a), self.merger.node_fingerprint(b))
        self.assertEqual(self.merger.node_fingerprint(a),
                         self.merger.node_fingerprint(a.replace("443,20000-20010", "443,20000-20010")))

    def test_hysteria2_rejects_unrepresentable_tuning_and_invalid_ports(self):
        base = {"type": "hysteria2", "server": "hy2.example.com",
                "port": 443, "password": "secret"}
        self.assertIsNone(self.merger.clash_to_share_link({**base, "hop-interval": 15}))
        self.assertIsNone(self.merger.clash_to_share_link({**base, "up": "30 Mbps"}))
        self.assertIsNone(self.merger.clash_to_share_link({**base, "ports": "0,443"}))
        self.assertIsNone(self.merger.clash_to_share_link({**base, "ports": "443,70000"}))

    def test_ssh_yaml_conversion_is_explicitly_rejected(self):
        proxy = {"type": "ssh", "server": "ssh.example.com", "port": 22,
                 "username": "root", "private-key": "PRIVATE KEY"}
        self.assertIsNone(self.merger.clash_to_share_link(proxy))
        self.assertEqual(self.merger._last_conversion_failure_reason,
                         "ssh_share_link_not_portable")

    def test_naive_https_and_quic_links_preserve_supported_options(self):
        https = self.merger.clash_to_share_link({
            "type": "naive", "name": "Naive HTTPS", "server": "naive.example.com",
            "port": 443, "username": "user", "password": "p@ss",
            "padding": True, "extra-headers": "X-Test: value"
        })
        parsed, query = self.parse_link(https)
        from urllib.parse import unquote
        self.assertEqual(parsed.scheme, "naive+https")
        self.assertEqual(unquote(parsed.username), "user")
        self.assertEqual(unquote(parsed.password), "p@ss")
        self.assertEqual(query["padding"], ["true"])
        self.assertEqual(query["extra-headers"], ["X-Test: value"])

        quic = self.merger.clash_to_share_link({
            "type": "naive", "name": "Naive QUIC", "server": "naive.example.com",
            "port": 443, "quic": True
        })
        parsed, _ = self.parse_link(quic)
        self.assertEqual(parsed.scheme, "naive+quic")

    def test_naive_rejects_incomplete_auth_and_nonportable_options(self):
        base = {"type": "naive", "server": "naive.example.com", "port": 443}
        self.assertIsNone(self.merger.clash_to_share_link({**base, "username": "user"}))
        self.assertIsNone(self.merger.clash_to_share_link({**base, "sni": "other.example.com"}))
        self.assertIsNone(self.merger.clash_to_share_link({
            **base, "extra-headers": "X-Test: one\r\nX-Evil: two"
        }))

    def test_naive_quic_raw_link_is_fingerprinted(self):
        link = "naive+quic://user:pass@naive.example.com:443?padding=true#Naive"
        self.assertIsNotNone(self.merger.node_fingerprint(link))
        self.assertNotEqual(self.merger.node_fingerprint(link),
                            self.merger.node_fingerprint(link.replace("padding=true", "padding=false")))

    def test_mieru_simple_link_preserves_all_supported_options(self):
        link = self.merger.clash_to_share_link({
            "type": "mieru", "name": "Mieru", "server": "mieru.example.com",
            "port-range": "20000-20010", "transport": "UDP",
            "username": "user", "password": "p@ss", "profile": "work",
            "mtu": 1400, "multiplexing": "MULTIPLEXING_HIGH",
            "handshake-mode": "HANDSHAKE_NO_WAIT", "traffic-pattern": "AQID"
        })
        parsed, query = self.parse_link(link)
        from urllib.parse import unquote
        self.assertEqual(parsed.scheme, "mierus")
        self.assertEqual(unquote(parsed.username), "user")
        self.assertEqual(unquote(parsed.password), "p@ss")
        self.assertEqual(query["profile"], ["work"])
        self.assertEqual(query["port"], ["20000-20010"])
        self.assertEqual(query["protocol"], ["UDP"])
        self.assertEqual(query["mtu"], ["1400"])
        self.assertEqual(query["multiplexing"], ["MULTIPLEXING_HIGH"])
        self.assertEqual(query["handshake-mode"], ["HANDSHAKE_NO_WAIT"])
        self.assertEqual(query["traffic-pattern"], ["AQID"])

    def test_mieru_rejects_invalid_multiplexing_handshake_and_mtu(self):
        base = {"type": "mieru", "server": "mieru.example.com",
                "port": 2999, "username": "user", "password": "pass"}
        self.assertIsNone(self.merger.clash_to_share_link({
            **base, "multiplexing": "MULTIPLEXING_UNKNOWN"
        }))
        self.assertIsNone(self.merger.clash_to_share_link({
            **base, "handshake-mode": "HANDSHAKE_FAST"
        }))
        self.assertIsNone(self.merger.clash_to_share_link({**base, "mtu": 1500}))

    def test_vless_reality_tls_and_alpn_options_are_preserved(self):
        link = self.merger.clash_to_share_link({
            "type": "vless", "name": "VLESS Reality", "server": "vless.example.com",
            "port": 443, "uuid": "11111111-1111-1111-1111-111111111111",
            "tls": True, "servername": "sni.example.com",
            "client-fingerprint": "firefox", "alpn": ["h2", "http/1.1"],
            "skip-cert-verify": True,
            "reality-opts": {"public-key": "public-key", "short-id": "abcd", "spider-x": "/"}
        })
        parsed, query = self.parse_link(link)
        self.assertEqual(parsed.scheme, "vless")
        self.assertEqual(query["security"], ["reality"])
        self.assertEqual(query["pbk"], ["public-key"])
        self.assertEqual(query["sid"], ["abcd"])
        self.assertEqual(query["spx"], ["/"])
        self.assertEqual(query["sni"], ["sni.example.com"])
        self.assertEqual(query["fp"], ["firefox"])
        self.assertEqual(query["alpn"], ["h2,http/1.1"])
        self.assertEqual(query["allowInsecure"], ["1"])

    def test_vless_websocket_early_data_is_preserved(self):
        link = self.merger.clash_to_share_link({
            "type": "vless", "name": "VLESS WS", "server": "vless.example.com",
            "port": 443, "uuid": "11111111-1111-1111-1111-111111111111",
            "network": "ws", "tls": True,
            "ws-opts": {
                "path": "/ws", "headers": {"Host": "cdn.example.com"},
                "max-early-data": 2048,
                "early-data-header-name": "Sec-WebSocket-Protocol"
            }
        })
        _, query = self.parse_link(link)
        self.assertEqual(query["type"], ["ws"])
        self.assertEqual(query["host"], ["cdn.example.com"])
        self.assertEqual(query["path"], ["/ws"])
        self.assertEqual(query["ed"], ["2048"])
        self.assertEqual(query["eh"], ["Sec-WebSocket-Protocol"])

    def test_vless_xhttp_extra_and_padding_are_preserved(self):
        extra = {"xPaddingBytes": "100-1000", "noGRPCHeader": True}
        link = self.merger.clash_to_share_link({
            "type": "vless", "name": "VLESS XHTTP", "server": "vless.example.com",
            "port": 443, "uuid": "11111111-1111-1111-1111-111111111111",
            "network": "xhttp", "tls": True,
            "xhttp-opts": {
                "path": "/upload", "host": "cdn.example.com",
                "mode": "packet-up", "extra": extra,
                "x-padding-bytes": "100-1000"
            }
        })
        _, query = self.parse_link(link)
        self.assertEqual(query["type"], ["xhttp"])
        self.assertEqual(query["path"], ["/upload"])
        self.assertEqual(query["host"], ["cdn.example.com"])
        self.assertEqual(query["mode"], ["packet-up"])
        self.assertEqual(query["x_padding_bytes"], ["100-1000"])
        self.assertEqual(json.loads(query["extra"][0]), extra)

    def test_vless_rejects_invalid_reality_and_xhttp_extra(self):
        base = {"type": "vless", "server": "vless.example.com", "port": 443,
                "uuid": "11111111-1111-1111-1111-111111111111", "tls": True}
        self.assertIsNone(self.merger.clash_to_share_link({
            **base, "reality-opts": {"short-id": "abcd"}
        }))
        self.assertIsNone(self.merger.clash_to_share_link({
            **base, "network": "xhttp", "xhttp-opts": {"extra": "not-json-object"}
        }))

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
        self.assertEqual(query["fp"], ["chrome"])
        self.assertNotIn("client-fingerprint", query)
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
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.username, "user")
        from urllib.parse import unquote
        self.assertEqual(unquote(parsed.password), "p@ss")
        self.assertNotIn("tls", query)
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

    def test_http_rejects_unrepresentable_headers_and_keeps_sni(self):
        base = {"type": "http", "name": "HTTP", "server": "proxy.example.com", "port": 8080}
        self.assertIsNone(self.merger.clash_to_share_link({**base, "headers": {"Host": ["alt.example.com"]}}))
        link = self.merger.clash_to_share_link({**base, "sni": "alt.example.com"})
        self.assertTrue(link.startswith("https://"))
        self.assertIn("sni=alt.example.com", link)

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

    def test_ss_plugin_options_are_preserved_or_rejected(self):
        base = {"type": "ss", "server": "ss.example.com", "port": 8388,
                "password": "secret", "cipher": "aes-128-gcm"}
        link = self.merger.clash_to_share_link({
            **base, "plugin": "obfs-local",
            "plugin-opts": {"mode": "tls", "host": "cdn.example.com"}
        })
        from urllib.parse import parse_qs, urlsplit
        plugin = parse_qs(urlsplit(link).query)["plugin"][0]
        self.assertEqual(plugin, "obfs-local;mode=tls;host=cdn.example.com")
        self.assertIsNone(self.merger.clash_to_share_link({
            **base, "plugin-opts": {"mode": "tls"}
        }))

    def test_conversion_failure_reason_is_recorded(self):
        proxy = {"type": "http", "server": "proxy.example.com", "port": 8080,
                 "headers": {"Host": ["alt.example.com"]}}
        self.assertIsNone(self.merger.clash_to_share_link(proxy))
        self.assertEqual(self.merger._last_conversion_failure_reason, "unsupported_headers")

    def test_http_basic_auth_preserves_empty_username_and_escapes_colon(self):
        base = {"type": "http", "server": "proxy.example.com", "port": 8080}
        password_only = self.merger.clash_to_share_link({**base, "password": "secret"})
        self.assertIn("://:secret@", password_only)

        colon_username = self.merger.clash_to_share_link({
            **base, "username": "user:name", "password": "secret"
        })
        self.assertIn("user%3Aname:secret@", colon_username)

    def test_conversion_failures_are_counted_by_protocol_and_reason(self):
        protocol_counts = {}
        reason_counts = {}
        merge._record_conversion_failure("http", "unsupported_sni", protocol_counts, reason_counts)
        merge._record_conversion_failure("http", "unsupported_sni", protocol_counts, reason_counts)
        merge._record_conversion_failure("socks5", "password_without_username", protocol_counts, reason_counts)

        self.assertEqual(protocol_counts, {
            "http": {"unsupported_sni": 2},
            "socks5": {"password_without_username": 1}
        })
        self.assertEqual(reason_counts, {
            "unsupported_sni": 2,
            "password_without_username": 1
        })

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


    def test_vmess_failure_diagnostics_distinguish_unsupported_networks(self):
        base = {"type": "vmess", "server": "example.com", "port": 443,
                "uuid": "11111111-1111-1111-1111-111111111111"}
        expected = {
            "xhttp": "xhttp",
            "splithttp": "splithttp",
            "kcp": "kcp",
            "quic": "quic",
        }
        for network, label in expected.items():
            with self.subTest(network=network):
                self.assertIsNone(self.merger.clash_to_share_link({**base, "network": network}))
                self.assertEqual(self.merger._last_conversion_failure_reason,
                                 "vmess_unsupported_network")
                self.assertEqual(self.merger._last_conversion_failure_network, label)

    def test_vmess_failure_diagnostics_identify_missing_uuid(self):
        proxy = {"type": "vmess", "server": "example.com", "port": 443}
        self.assertIsNone(self.merger.clash_to_share_link(proxy))
        self.assertEqual(self.merger._last_conversion_failure_reason, "vmess_missing_uuid")

    def test_vmess_failure_diagnostics_identify_missing_grpc_service_name(self):
        proxy = {"type": "vmess", "server": "example.com", "port": 443,
                 "uuid": "11111111-1111-1111-1111-111111111111",
                 "network": "grpc", "grpc-opts": {}}
        self.assertIsNone(self.merger.clash_to_share_link(proxy))
        self.assertEqual(self.merger._last_conversion_failure_reason,
                         "vmess_missing_grpc_service_name")

    def test_vmess_failure_diagnostics_identify_unsupported_tcp_header(self):
        proxy = {"type": "vmess", "server": "example.com", "port": 443,
                 "uuid": "11111111-1111-1111-1111-111111111111",
                 "network": "tcp", "tcp-opts": {"header": {"type": "srtp"}}}
        self.assertIsNone(self.merger.clash_to_share_link(proxy))
        self.assertEqual(self.merger._last_conversion_failure_reason,
                         "vmess_unsupported_tcp_header")

    def test_vmess_failure_diagnostics_identify_tls_options_without_tls(self):
        proxy = {"type": "vmess", "server": "example.com", "port": 443,
                 "uuid": "11111111-1111-1111-1111-111111111111",
                 "tls": False, "servername": "sni.example.com"}
        self.assertIsNone(self.merger.clash_to_share_link(proxy))
        self.assertEqual(self.merger._last_conversion_failure_reason,
                         "vmess_tls_options_without_tls")

    def test_vmess_failure_diagnostics_identify_unrepresentable_tls_credentials(self):
        proxy = {"type": "vmess", "server": "example.com", "port": 443,
                 "uuid": "11111111-1111-1111-1111-111111111111",
                 "tls": True, "certificate": "CERTIFICATE"}
        self.assertIsNone(self.merger.clash_to_share_link(proxy))
        self.assertEqual(self.merger._last_conversion_failure_reason,
                         "vmess_unrepresentable_tls_credentials")

    def test_vmess_failure_diagnostics_identify_invalid_transport_shapes(self):
        cases = [
            {"network": "ws", "ws-opts": ["bad"]},
            {"network": "h2", "h2-opts": {"headers": ["bad"]}},
            {"network": "grpc", "grpc-opts": ["bad"]},
            {"network": "httpupgrade", "http-upgrade-opts": ["bad"]},
            {"network": "tcp", "tcp-opts": {"header": ["bad"]}},
        ]
        base = {"type": "vmess", "server": "example.com", "port": 443,
                "uuid": "11111111-1111-1111-1111-111111111111"}
        for options in cases:
            with self.subTest(options=options):
                self.assertIsNone(self.merger.clash_to_share_link({**base, **options}))
                self.assertEqual(self.merger._last_conversion_failure_reason,
                                 "vmess_invalid_transport_options")

    def test_vmess_failure_diagnostics_identify_multiple_transport_hosts(self):
        proxy = {"type": "vmess", "server": "example.com", "port": 443,
                 "uuid": "11111111-1111-1111-1111-111111111111",
                 "network": "h2", "h2-opts": {"host": ["a.example.com", "b.example.com"]}}
        self.assertIsNone(self.merger.clash_to_share_link(proxy))
        self.assertEqual(self.merger._last_conversion_failure_reason,
                         "vmess_multiple_transport_hosts_or_paths")

    def test_vmess_rejects_unrepresented_transports(self):
        base = {"type": "vmess", "server": "example.com", "port": 443,
                "uuid": "11111111-1111-1111-1111-111111111111"}
        for network in ("xhttp", "splithttp", "kcp", "quic"):
            with self.subTest(network=network):
                self.assertIsNone(self.merger.clash_to_share_link({**base, "network": network}))

    def test_vmess_preserves_tls_security_parameters(self):
        link = self.merger.clash_to_share_link({
            "type": "vmess", "server": "example.com", "port": 443,
            "uuid": "11111111-1111-1111-1111-111111111111",
            "network": "ws", "tls": True, "skip-cert-verify": "false",
            "servername": "sni.example.com", "client-fingerprint": "chrome",
            "alpn": ["h2", "http/1.1"]
        })
        payload = json.loads(sub_merge.base64_decode(link.split("://", 1)[1]))
        self.assertEqual(payload["sni"], "sni.example.com")
        self.assertEqual(payload["fp"], "chrome")
        self.assertEqual(payload["alpn"], "h2,http/1.1")
        self.assertNotIn("insecure", payload)

    def test_vmess_string_true_skip_cert_verify_is_preserved(self):
        link = self.merger.clash_to_share_link({
            "type": "vmess", "server": "example.com", "port": 443,
            "uuid": "11111111-1111-1111-1111-111111111111",
            "tls": True, "skip-cert-verify": "true"
        })
        payload = json.loads(sub_merge.base64_decode(link.split("://", 1)[1]))
        self.assertEqual(payload["insecure"], "1")

    def test_trojan_and_http_string_false_do_not_disable_verification(self):
        trojan = self.merger.clash_to_share_link({
            "type": "trojan", "server": "example.com", "port": 443,
            "password": "secret", "skip-cert-verify": "false"
        })
        self.assertNotIn("allowInsecure=1", trojan)
        http = self.merger.clash_to_share_link({
            "type": "http", "server": "proxy.example.com", "port": 443,
            "tls": True, "skip-cert-verify": "false"
        })
        self.assertTrue(http.startswith("https://"))
        self.assertNotIn("skip-cert-verify=true", http)

    def test_http_tls_uses_https_uri_scheme(self):
        link = self.merger.clash_to_share_link({
            "type": "http", "server": "proxy.example.com", "port": 443, "tls": True
        })
        self.assertTrue(link.startswith("https://"))

    def test_vless_h2_uses_xray_http_transport_name(self):
        link = self.merger.clash_to_share_link({
            "type": "vless", "server": "example.com", "port": 443,
            "uuid": "11111111-1111-1111-1111-111111111111",
            "network": "h2", "tls": True,
            "h2-opts": {"host": ["cdn.example.com"], "path": ["/h2"]}
        })
        from urllib.parse import parse_qs, urlsplit
        query = parse_qs(urlsplit(link).query)
        self.assertEqual(query["type"], ["http"])
        self.assertEqual(query["host"], ["cdn.example.com"])
        self.assertEqual(query["path"], ["/h2"])

    def test_naive_quic_scheme_is_not_rejected_by_scheme_validation(self):
        yaml_text = """proxies:
  - name: naive-quic
    type: naive
    server: example.com
    port: 443
    quic: true
"""
        response = Mock()
        response.content = yaml_text.encode("utf-8")
        response.raise_for_status = Mock()
        with tempfile.TemporaryDirectory() as temp_dir:
            merger = merge.__new__(merge)
            merger.list_dir = os.path.join(temp_dir, "list")
            merger.merge_dir = temp_dir
            merger.url_list = [{"id": 1, "remarks": "naive-test", "url": "https://example.invalid/naive.yaml"}]
            session = Mock()
            session.get.return_value = response
            with patch.object(sub_merge.requests, "Session", return_value=session):
                self.assertTrue(merger.sub_merge())
            with open(os.path.join(temp_dir, "sub_merge_base64.txt"), "r", encoding="utf-8") as f:
                output = sub_merge.base64_decode(f.read())
        self.assertIn("naive+quic://", output)


    def test_https_http_proxy_survives_yaml_scheme_validation(self):
        yaml_text = """proxies:
  - name: https-proxy
    type: http
    server: proxy.example.com
    port: 443
    tls: true
"""
        response = Mock()
        response.content = yaml_text.encode("utf-8")
        response.raise_for_status = Mock()
        with tempfile.TemporaryDirectory() as temp_dir:
            merger = merge.__new__(merge)
            merger.list_dir = os.path.join(temp_dir, "list")
            merger.merge_dir = temp_dir
            merger.url_list = [{"id": 2, "remarks": "https-test", "url": "https://example.invalid/http.yaml"}]
            session = Mock()
            session.get.return_value = response
            with patch.object(sub_merge.requests, "Session", return_value=session):
                self.assertTrue(merger.sub_merge())
            with open(os.path.join(temp_dir, "sub_merge_base64.txt"), "r", encoding="utf-8") as f:
                output = sub_merge.base64_decode(f.read())
        self.assertIn("https://proxy.example.com:443", output)


    def test_hysteria_v1_uri_uses_standard_peer_and_obfs_param(self):
        link = self.merger.clash_to_share_link({
            "type": "hysteria", "server": "hy.example.com", "port": 443,
            "up": "30 Mbps", "down": "100 Mbps", "sni": "sni.example.com",
            "obfs": "secret-obfs", "protocol": "udp"
        })
        from urllib.parse import parse_qs, urlsplit
        query = parse_qs(urlsplit(link).query)
        self.assertEqual(query["peer"], ["sni.example.com"])
        self.assertEqual(query["obfs"], ["xplus"])
        self.assertEqual(query["obfsParam"], ["secret-obfs"])
        self.assertEqual(query["upmbps"], ["30"])
        self.assertEqual(query["downmbps"], ["100"])
        self.assertNotIn("sni", query)

    def test_hysteria_v1_rejects_nonstandard_fields_and_missing_bandwidth(self):
        base = {"type": "hysteria", "server": "hy.example.com", "port": 443,
                "up": "30", "down": "100"}
        self.assertIsNone(self.merger.clash_to_share_link({**base, "recv-window-conn": 1024}))
        self.assertIsNone(self.merger.clash_to_share_link({**base, "up": None}))


    def test_hysteria_v1_normalizes_bandwidth_units_and_rejects_invalid_rates(self):
        link = self.merger.clash_to_share_link({
            "type": "hysteria", "server": "hy.example.com", "port": 443,
            "up": "1 Gbps", "down": "800 Mbps"
        })
        from urllib.parse import parse_qs, urlsplit
        query = parse_qs(urlsplit(link).query)
        self.assertEqual(query["upmbps"], ["1000"])
        self.assertEqual(query["downmbps"], ["800"])
        self.assertIsNone(self.merger.clash_to_share_link({
            "type": "hysteria", "server": "hy.example.com", "port": 443,
            "up": "100 Kbps", "down": "800 Mbps"
        }))

    def test_anytls_client_fingerprint_uses_fp_parameter(self):
        link = self.merger.clash_to_share_link({
            "type": "anytls", "server": "any.example.com", "port": 443,
            "password": "secret", "client-fingerprint": "chrome"
        })
        from urllib.parse import parse_qs, urlsplit
        query = parse_qs(urlsplit(link).query)
        self.assertEqual(query["fp"], ["chrome"])
        self.assertNotIn("client-fingerprint", query)

    def test_ss_userinfo_uses_urlsafe_base64_without_padding(self):
        link = self.merger.clash_to_share_link({
            "type": "ss", "server": "ss.example.com", "port": 8388,
            "password": "?+/=secret", "cipher": "aes-128-gcm"
        })
        userinfo = link.split("://", 1)[1].split("@", 1)[0]
        self.assertNotIn("+", userinfo)
        self.assertNotIn("/", userinfo)
        self.assertNotIn("=", userinfo)
        self.assertEqual(base64.urlsafe_b64decode(userinfo + "=" * (-len(userinfo) % 4)).decode(),
                         "aes-128-gcm:?+/=secret")


class ClashYamlMergeRegressionTests(unittest.TestCase):
    def test_yaml_proxy_conversion_does_not_raise_undefined_proxy_type(self):
        yaml_text = """proxies:
  - name: regression-vless
    type: vless
    server: example.com
    port: 443
    uuid: 11111111-1111-1111-1111-111111111111
"""
        response = Mock()
        response.content = yaml_text.encode("utf-8")
        response.raise_for_status = Mock()

        with tempfile.TemporaryDirectory() as temp_dir:
            merger = merge.__new__(merge)
            merger.list_dir = os.path.join(temp_dir, "list")
            merger.merge_dir = temp_dir
            merger.url_list = [{
                "id": 1,
                "remarks": "regression-test",
                "url": "https://example.invalid/proxies.yaml"
            }]

            session = Mock()
            session.get.return_value = response
            with patch.object(sub_merge.requests, "Session", return_value=session):
                self.assertTrue(merger.sub_merge())

            output_path = os.path.join(temp_dir, "sub_merge_base64.txt")
            with open(output_path, "r", encoding="utf-8") as output_file:
                merged_text = sub_merge.base64_decode(output_file.read())

        self.assertIn("vless://", merged_text)
        self.assertIn("example.com:443", merged_text)


    def test_sub_merge_reports_vmess_unsupported_network_breakdown(self):
        yaml_text = """proxies:
  - name: unsupported-xhttp
    type: vmess
    server: xhttp.example.com
    port: 443
    uuid: 11111111-1111-1111-1111-111111111111
    network: xhttp
  - name: unsupported-splithttp
    type: vmess
    server: splithttp.example.com
    port: 443
    uuid: 22222222-2222-2222-2222-222222222222
    network: splithttp
  - name: supported-tcp
    type: vmess
    server: tcp.example.com
    port: 443
    uuid: 33333333-3333-3333-3333-333333333333
    network: tcp
"""
        response = Mock()
        response.content = yaml_text.encode("utf-8")
        response.raise_for_status = Mock()

        with tempfile.TemporaryDirectory() as temp_dir:
            merger = merge.__new__(merge)
            merger.list_dir = os.path.join(temp_dir, "list")
            merger.merge_dir = temp_dir
            merger.url_list = [{
                "id": 1,
                "remarks": "vmess-diagnostic-test",
                "url": "https://example.invalid/vmess.yaml"
            }]
            session = Mock()
            session.get.return_value = response
            with patch.object(sub_merge.requests, "Session", return_value=session):
                with patch("builtins.print") as print_mock:
                    self.assertTrue(merger.sub_merge())

        output = "\n".join(
            " ".join(str(value) for value in call.args)
            for call in print_mock.call_args_list
        )
        self.assertIn("vmess_unsupported_network=2", output)
        self.assertIn("VMess unsupported network types: splithttp=1, xhttp=1", output)
        self.assertIn("vmess: vmess_unsupported_network=2", output)


class FirstStageLosslessTransportTests(unittest.TestCase):
    def setUp(self):
        self.merger = merge.__new__(merge)

    def vmess_payload(self, proxy):
        link = self.merger.clash_to_share_link(proxy)
        self.assertIsNotNone(link)
        self.assertTrue(link.startswith("vmess://"))
        return json.loads(sub_merge.base64_decode(link.split("://", 1)[1]))

    def base_proxy(self, protocol, **extra):
        return {
            "type": protocol,
            "name": "regression",
            "server": "example.com",
            "port": 443,
            "uuid": "11111111-1111-1111-1111-111111111111",
            **extra,
        }

    def test_vmess_http_network_maps_to_tcp_http_header_without_loss(self):
        payload = self.vmess_payload(self.base_proxy(
            "vmess", network="http", **{"http-opts": {
                "method": "GET",
                "path": ["/legacy"],
                "headers": {"Host": ["cdn.example.com"]},
            }}
        ))
        self.assertEqual(payload["net"], "tcp")
        self.assertEqual(payload["type"], "http")
        self.assertEqual(payload["host"], "cdn.example.com")
        self.assertEqual(payload["path"], "/legacy")

    def test_vmess_http_network_rejects_unrepresentable_http_options(self):
        cases = [
            {"method": "POST", "path": ["/"], "headers": {}},
            {"method": "GET", "path": ["/"], "headers": {"Connection": ["keep-alive"]}},
            {"method": "GET", "path": ["/a", "/b"], "headers": {}},
            {"method": "GET", "path": ["/"], "headers": {"Host": ["a.example.com", "b.example.com"]}},
        ]
        for options in cases:
            with self.subTest(options=options):
                proxy = self.base_proxy("vmess", network="http", **{"http-opts": options})
                self.assertIsNone(self.merger.clash_to_share_link(proxy))
                self.assertTrue(self.merger._last_conversion_failure_reason.startswith("vmess_"))

    def test_vmess_ws_httpupgrade_flag_is_preserved(self):
        payload = self.vmess_payload(self.base_proxy(
            "vmess", network="ws",
            **{"ws-opts": {
                "path": "/upgrade",
                "headers": {"Host": "cdn.example.com"},
                "v2ray-http-upgrade": True,
            }}
        ))
        self.assertEqual(payload["net"], "httpupgrade")
        self.assertNotIn("httpupgrade", payload)
        self.assertEqual(payload["host"], "cdn.example.com")
        self.assertEqual(payload["path"], "/upgrade")

    def test_vmess_ws_httpupgrade_fast_open_is_rejected(self):
        proxy = self.base_proxy("vmess", network="ws", **{"ws-opts": {
            "v2ray-http-upgrade": True,
            "v2ray-http-upgrade-fast-open": True,
        }})
        self.assertIsNone(self.merger.clash_to_share_link(proxy))
        self.assertEqual(self.merger._last_conversion_failure_reason,
                         "vmess_unrepresentable_httpupgrade_fast_open")

    def test_vless_ws_httpupgrade_maps_to_httpupgrade_uri(self):
        from urllib.parse import parse_qs, urlsplit
        link = self.merger.clash_to_share_link(self.base_proxy(
            "vless", network="ws",
            **{"ws-opts": {"path": "/upgrade", "headers": {"Host": "cdn.example.com"},
                           "v2ray-http-upgrade": True}}
        ))
        query = parse_qs(urlsplit(link).query)
        self.assertEqual(query["type"], ["httpupgrade"])
        self.assertEqual(query["host"], ["cdn.example.com"])
        self.assertEqual(query["path"], ["/upgrade"])

    def test_trojan_ws_httpupgrade_maps_to_httpupgrade_uri(self):
        from urllib.parse import parse_qs, urlsplit
        link = self.merger.clash_to_share_link(self.base_proxy(
            "trojan", password="secret", network="ws",
            **{"ws-opts": {"path": "/upgrade", "headers": {"Host": "cdn.example.com"},
                           "v2ray-http-upgrade": True}}
        ))
        query = parse_qs(urlsplit(link).query)
        self.assertEqual(query["type"], ["httpupgrade"])
        self.assertEqual(query["host"], ["cdn.example.com"])
        self.assertEqual(query["path"], ["/upgrade"])

    def test_vless_encryption_is_preserved_and_packet_encoding_is_rejected(self):
        from urllib.parse import parse_qs, urlsplit
        link = self.merger.clash_to_share_link(self.base_proxy(
            "vless", encryption="mlkem768x25519plus.native"
        ))
        self.assertEqual(parse_qs(urlsplit(link).query)["encryption"],
                         ["mlkem768x25519plus.native"])
        rejected = self.merger.clash_to_share_link(self.base_proxy(
            "vless", **{"packet-encoding": "packetaddr"}
        ))
        self.assertIsNone(rejected)


    def test_httpupgrade_rejects_unrepresentable_request_headers(self):
        cases = [
            self.base_proxy("vmess", network="ws", **{"ws-opts": {
                "v2ray-http-upgrade": True,
                "headers": {"Host": "cdn.example.com", "Connection": "keep-alive"},
            }}),
            self.base_proxy("vless", network="ws", **{"ws-opts": {
                "v2ray-http-upgrade": True,
                "headers": {"Host": "cdn.example.com", "Connection": "keep-alive"},
            }}),
            self.base_proxy("trojan", password="secret", network="ws", **{"ws-opts": {
                "v2ray-http-upgrade": True,
                "headers": {"Host": "cdn.example.com", "Connection": "keep-alive"},
            }}),
        ]
        for proxy in cases:
            with self.subTest(protocol=proxy["type"]):
                self.assertIsNone(self.merger.clash_to_share_link(proxy))


class VlessPacketEncodingAndDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.merger = merge.__new__(merge)

    def base_proxy(self, **extra):
        return {
            "type": "vless", "name": "VLESS regression",
            "server": "vless.example.com", "port": 443,
            "uuid": "11111111-1111-1111-1111-111111111111",
            **extra,
        }

    def test_vless_empty_encryption_is_accepted_and_omitted(self):
        from urllib.parse import parse_qs, urlsplit
        link = self.merger.clash_to_share_link(self.base_proxy(encryption=""))
        self.assertIsNotNone(link)
        self.assertNotIn("encryption", parse_qs(urlsplit(link).query))

    def test_vless_nonempty_encryption_is_preserved_in_uri(self):
        from urllib.parse import parse_qs, urlsplit
        value = "mlkem768x25519plus.native"
        link = self.merger.clash_to_share_link(self.base_proxy(encryption=value))
        self.assertEqual(parse_qs(urlsplit(link).query)["encryption"], [value])

    def test_vless_packet_encoding_maps_to_mihomo_v_share_tokens(self):
        from urllib.parse import parse_qs, urlsplit
        cases = {"xudp": "xudp", "packetaddr": "packet", "": "none"}
        for yaml_value, uri_value in cases.items():
            with self.subTest(packet_encoding=yaml_value):
                link = self.merger.clash_to_share_link(
                    self.base_proxy(**{"packet-encoding": yaml_value})
                )
                self.assertIsNotNone(link)
                self.assertEqual(parse_qs(urlsplit(link).query)["packetEncoding"], [uri_value])

    def test_vless_invalid_packet_encoding_is_rejected_with_specific_reason(self):
        proxy = self.base_proxy(**{"packet-encoding": "unknown"})
        self.assertIsNone(self.merger.clash_to_share_link(proxy))
        self.assertEqual(self.merger._last_conversion_failure_reason,
                         "vless_unsupported_packet_encoding")

    def test_vless_diagnostics_distinguish_common_failure_classes(self):
        cases = [
            ({"uuid": ""}, "vless_missing_uuid"),
            ({"network": "mkcp"}, "vless_unsupported_network"),
            ({"encryption": None}, "vless_invalid_encryption"),
            ({"reality-opts": {"short-id": "abcd"}}, "vless_missing_reality_public_key"),
            ({"tls": False, "servername": "sni.example.com"}, "vless_tls_options_without_tls"),
            ({"network": "ws", "ws-opts": ["bad"]}, "vless_invalid_ws_options"),
            ({"network": "xhttp", "xhttp-opts": {"extra": "bad"}}, "vless_invalid_xhttp_extra"),
        ]
        for extra, expected in cases:
            with self.subTest(expected=expected):
                self.assertIsNone(self.merger.clash_to_share_link(self.base_proxy(**extra)))
                self.assertEqual(self.merger._last_conversion_failure_reason, expected)

    def test_vmess_raw_and_none_networks_normalize_to_tcp(self):
        from urllib.parse import urlsplit
        for network in ("raw", "none"):
            with self.subTest(network=network):
                link = self.merger.clash_to_share_link({
                    "type": "vmess", "server": "vmess.example.com", "port": 443,
                    "uuid": "11111111-1111-1111-1111-111111111111",
                    "network": network,
                })
                self.assertIsNotNone(link)
                payload = json.loads(sub_merge.base64_decode(urlsplit(link).netloc))
                self.assertEqual(payload["net"], "tcp")


if __name__ == "__main__":
    unittest.main()
