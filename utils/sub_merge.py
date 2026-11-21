#!/usr/bin/env python3

import json
import os
import base64
import re
import urllib.parse
import requests
import yaml


def base64_decode(s):
    try:
        s = re.sub(r'\s+', '', s)
        if not s:
            return ""
        s = s.replace('-', '+').replace('_', '/')
        missing_padding = len(s) % 4
        if missing_padding:
            s += '=' * (4 - missing_padding)
        decoded = base64.b64decode(s, validate=True)
        return decoded.decode('utf-8', 'strict')
    except Exception:
        return ""


def base64_encode(s):
    return base64.b64encode(s.encode('utf-8')).decode('ascii')


def is_base64(s):
    s = re.sub(r'\s+', '', s)
    if not s:
        return False
    if not re.match(r'^[A-Za-z0-9+/_-]*={0,2}$', s):
        return False
    try:
        s_std = s.replace('-', '+').replace('_', '/')
        missing_padding = len(s_std) % 4
        if missing_padding:
            s_std += '=' * (4 - missing_padding)
        decoded = base64.b64decode(s_std, validate=True)
        decoded.decode('utf-8', 'strict')
        return bool(decoded)
    except Exception:
        return False


class merge:
    def __init__(self, file_dir, format_config):
        self.list_dir = file_dir['list_dir']
        self.list_file = file_dir['list_file']
        self.merge_dir = file_dir['merge_dir']
        self.readme_file = file_dir.get('readme_file')
        self.format_config = format_config
        self.url_list = self.read_list()
        self.merge_succeeded = self.sub_merge()
        if self.readme_file and self.merge_succeeded:
            self.readme_update()

    def read_list(self):
        with open(self.list_file, 'r', encoding='utf-8') as f:
            source_list = [item for item in json.load(f) if item.get('enabled')]

        # Clash Profile 只作为 Provider 来源索引，不作为普通节点订阅解析。
        expanded_list = []
        for item in source_list:
            if item.get('type') != 'clash_profile':
                expanded_list.append(item)
                continue

            providers = item.get('providers') or []
            print(f"Clash Profile [ID: {item.get('id')}] discovered {len(providers)} providers.")
            for provider in providers:
                if not isinstance(provider, dict) or not provider.get('url'):
                    continue
                expanded_item = {
                    'id': item.get('id'),
                    'remarks': f"{item.get('remarks', 'Clash Profile')} / {provider.get('name', 'Provider')}",
                    'url': provider['url'],
                    'enabled': True,
                    '_provider': provider
                }
                expanded_list.append(expanded_item)

        return expanded_list

    @staticmethod
    def _normalize_mislabeled_vless_share_link(link):
        """Correct only strongly identifiable VLESS URIs incorrectly tagged as ss://."""
        try:
            if not isinstance(link, str) or not link.lower().startswith('ss://'):
                return link
            parsed = urllib.parse.urlsplit(link)
            username = urllib.parse.unquote(parsed.username or '')
            if parsed.password is not None or not re.fullmatch(
                r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
                username
            ):
                return link
            if not parsed.hostname or parsed.port is None:
                return link
            query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
            transport = str(query.get('type') or '').strip().lower()
            security = str(query.get('security') or '').strip().lower()
            if transport not in ('tcp', 'ws', 'grpc', 'http', 'h2', 'xhttp', 'splithttp', 'httpupgrade'):
                return link

            # An empty security value is seen in some malformed VLESS subscriptions.
            # Accept it only with explicit VLESS encryption=none; do not infer VLESS
            # from a UUID-shaped SS credential alone.
            if security:
                if security not in ('none', 'tls', 'reality'):
                    return link
            elif str(query.get('encryption') or '').strip().lower() != 'none':
                return link

            if not ({'encryption', 'sni', 'pbk', 'flow', 'fp'} & set(query)):
                return link
            return 'vless://' + link[len('ss://'):]
        except (TypeError, ValueError):
            return link

    @staticmethod
    def _suspected_mislabeled_vless_transport(link):
        """Return a safe transport label for ambiguous UUID-based ss:// VLESS candidates.

        These links are diagnostic-only: unlike high-confidence signatures, they
        are deliberately not rewritten because their VLESS identity is not certain.
        """
        try:
            if not isinstance(link, str) or not link.lower().startswith('ss://'):
                return None
            parsed = urllib.parse.urlsplit(link)
            username = urllib.parse.unquote(parsed.username or '')
            if parsed.password is not None or not re.fullmatch(
                r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
                username
            ):
                return None
            if not parsed.hostname or parsed.port is None:
                return None

            query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
            transport = str(query.get('type') or '').strip().lower()
            if transport not in ('tcp', 'ws', 'grpc', 'http', 'h2', 'xhttp', 'splithttp', 'httpupgrade'):
                return None

            # Transport-specific VLESS-style fields raise suspicion, but are not
            # sufficient to rewrite a link whose encryption/security markers are absent.
            transport_markers = {
                'path', 'host', 'mode', 'extra', 'serviceName',
                'headerType', 'packetEncoding'
            }
            if not (transport_markers & set(query)):
                return None
            return transport
        except (TypeError, ValueError):
            return None

    def parse_share_link(self, link):
        """将常见分享链接解析为包含核心指纹的字典"""
        try:
            protocol, rest = link.split("://", 1)
            protocol = protocol.lower()
            if protocol == 'hy2':
                protocol = 'hysteria2'

            main_part = rest.split('#', 1)[0].strip()
            fingerprint_parts = {'protocol': protocol}

            if protocol == 'vmess':
                config = json.loads(base64_decode(main_part.split('?', 1)[0]))
                server = str(config.get('add', '')).strip().lower()
                port = str(config.get('port', '')).strip()
                uuid = str(config.get('id', '')).strip().lower()
                if not all([server, port, uuid]):
                    return None
                fingerprint_parts['server'] = server
                fingerprint_parts['port'] = port
                fingerprint_parts['id'] = uuid

            elif protocol == 'vless':
                user_info, server_info = main_part.split('@', 1)
                host_port = server_info.split('?', 1)[0].rstrip('/')
                server, port = host_port.rsplit(':', 1)
                fingerprint_parts['id'] = urllib.parse.unquote(user_info).strip().lower()
                fingerprint_parts['server'] = server.strip().lower()
                fingerprint_parts['port'] = port.strip()

            elif protocol in ['trojan', 'hysteria2']:
                user_info, server_info = main_part.split('@', 1)
                host_port = server_info.split('?', 1)[0].rstrip('/')
                server, port = host_port.rsplit(':', 1)
                # Trojan / Hysteria2 认证信息为密码，保留大小写敏感
                fingerprint_parts['id'] = urllib.parse.unquote(user_info).strip()
                fingerprint_parts['server'] = server.strip().lower()
                fingerprint_parts['port'] = port.strip()

            elif protocol == 'ss':
                if '@' in main_part:
                    credentials_part, server_part = main_part.split('@', 1)
                    host_port = server_part.split('?', 1)[0].rstrip('/')
                    server, port = host_port.rsplit(':', 1)
                    creds_unquoted = urllib.parse.unquote(credentials_part)
                    if ':' in creds_unquoted:
                        creds = creds_unquoted
                    else:
                        creds = base64_decode(credentials_part)
                        if not creds or ':' not in creds:
                            return None
                else:
                    decoded = base64_decode(main_part.split('?', 1)[0])
                    if '@' in decoded:
                        creds, host_port = decoded.split('@', 1)
                        server, port = host_port.rstrip('/').rsplit(':', 1)
                    else:
                        # 兼容旧版 base64(method:password:server:port)
                        parts = decoded.rsplit(':', 2)
                        if len(parts) != 3 or ':' not in parts[0]:
                            return None
                        creds, server, port = parts[0], parts[1], parts[2]
                if not all([creds, server, port]):
                    return None
                fingerprint_parts['id'] = creds.strip()
                fingerprint_parts['server'] = server.strip().lower()
                fingerprint_parts['port'] = port.strip()

            elif protocol == 'ssr':
                # ssr://base64(server:port:protocol:method:obfs:base64(password)/?params)
                decoded = base64_decode(main_part)
                ssr_main = decoded.split('/?', 1)[0]
                parts = ssr_main.rsplit(':', 5)
                if len(parts) != 6:
                    return None
                server, port, ssr_proto, method, obfs, pwd_b64 = parts
                password = base64_decode(pwd_b64)
                fingerprint_parts['server'] = server.strip().lower()
                fingerprint_parts['port'] = port.strip()
                fingerprint_parts['id'] = f"{ssr_proto}:{method}:{obfs}:{password}"

            else:
                return None

            return fingerprint_parts
        except Exception:
            return None

    def node_fingerprint(self, link):
        """完整连接参数指纹；忽略节点备注，保留传输/TLS/Reality 等差异。"""
        try:
            protocol, rest = link.strip().split("://", 1)
            protocol = protocol.lower()
            if protocol in ("naive+https", "naive+http", "naive+quic"):
                protocol = "naive"
                raw = link.strip().split("#", 1)[0]
            else:
                raw = rest.split("#", 1)[0]
            if protocol == "hy2":
                protocol = "hysteria2"
            elif protocol == "hy":
                protocol = "hysteria"
            elif protocol == "wg":
                protocol = "wireguard"
            if protocol == "vmess":
                payload = json.loads(base64_decode(raw.split("?", 1)[0]))
                if not isinstance(payload, dict):
                    return None
                payload = {str(k).lower(): v for k, v in payload.items() if str(k).lower() not in ("ps", "remark", "remarks", "name")}
                canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                return protocol + "|" + canonical
            if protocol == "ssr":
                decoded = base64_decode(raw)
                if not decoded:
                    return None
                if "/?" in decoded:
                    config, query_string = decoded.split("/?", 1)
                    query = urllib.parse.parse_qsl(query_string, keep_blank_values=True)
                else:
                    config, query = decoded, []
                # SSR remarks 通常藏在外层 Base64 的 remarks 参数中，也不应影响节点身份。
                query = sorted((str(k), str(v)) for k, v in query if str(k).lower() != "remarks")
                return json.dumps({
                    "protocol": protocol,
                    "config": config,
                    "query": query
                }, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            if protocol not in ("vless", "trojan", "hysteria", "hysteria2", "tuic", "anytls", "wireguard", "http", "https", "socks5", "socks", "ss", "naive", "mieru", "mierus", "ssh", "snell"):
                return None
            if protocol == "naive":
                parsed_naive = urllib.parse.urlsplit(raw if raw.startswith("naive+") else "naive+" + raw)
                if not parsed_naive.hostname:
                    return None
                return json.dumps({
                    "protocol": "naive",
                    "scheme": parsed_naive.scheme.lower(),
                    "server": parsed_naive.hostname.lower(),
                    "port": parsed_naive.port if parsed_naive.port is not None else (443 if parsed_naive.scheme.endswith(("https", "quic")) else 80),
                    "username": urllib.parse.unquote(parsed_naive.username or ""),
                    "password": urllib.parse.unquote(parsed_naive.password or ""),
                    "query": sorted(urllib.parse.parse_qsl(parsed_naive.query, keep_blank_values=True))
                }, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            if protocol == "hysteria2":
                parsed_hy2 = urllib.parse.urlsplit("hysteria2://" + raw)
                if not parsed_hy2.hostname:
                    return None
                authority = parsed_hy2.netloc.rsplit("@", 1)[-1]
                if authority.startswith('['):
                    closing = authority.find(']')
                    if closing < 0:
                        return None
                    port_text = authority[closing + 2:] if authority[closing + 1:closing + 2] == ':' else '443'
                else:
                    port_text = authority.rsplit(':', 1)[-1] if ':' in authority else '443'
                if not port_text or not self._valid_port_list(port_text):
                    return None
                return json.dumps({
                    "protocol": protocol,
                    "server": parsed_hy2.hostname.lower(),
                    "port": port_text,
                    "username": urllib.parse.unquote(parsed_hy2.username or ""),
                    "password": urllib.parse.unquote(parsed_hy2.password or ""),
                    "path": parsed_hy2.path or "",
                    "query": sorted((str(k), str(v)) for k, v in urllib.parse.parse_qsl(parsed_hy2.query, keep_blank_values=True))
                }, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            parsed = urllib.parse.urlsplit(protocol + "://" + raw)
            if protocol == "ss":
                if not parsed.hostname or parsed.port is None:
                    # 兼容旧式 ss://base64(method:password@server:port) 链接。
                    legacy = self.parse_share_link(link)
                    if not legacy:
                        return None
                    return json.dumps({
                        "protocol": protocol,
                        "server": legacy.get("server", "").lower(),
                        "port": legacy.get("port", ""),
                        "credentials": legacy.get("id", "")
                    }, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

                encoded_or_plain_user = urllib.parse.unquote(parsed.username or "")
                decoded_user = base64_decode(encoded_or_plain_user)
                if not parsed.password and decoded_user and ":" in decoded_user:
                    cipher, ss_password = decoded_user.split(":", 1)
                else:
                    cipher = encoded_or_plain_user
                    ss_password = urllib.parse.unquote(parsed.password or "")
                if not cipher:
                    return None
                ss_query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
                return json.dumps({
                    "protocol": protocol,
                    "server": parsed.hostname.lower(),
                    "port": parsed.port,
                    "cipher": cipher,
                    "password": ss_password,
                    "path": parsed.path or "",
                    "query": sorted((str(k), str(v)) for k, v in ss_query)
                }, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            if protocol == "mierus":
                # Official Mieru simple links carry the server port and transport in
                # repeated query parameters rather than the URL authority.
                if not parsed.hostname or not parsed.username or not parsed.password:
                    return None
                query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
                normalized_query = sorted((str(k), str(v)) for k, v in query)
                return json.dumps({
                    "protocol": "mieru",
                    "server": parsed.hostname.lower(),
                    "username": urllib.parse.unquote(parsed.username),
                    "password": urllib.parse.unquote(parsed.password),
                    "path": parsed.path or "",
                    "query": normalized_query
                }, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            if not parsed.hostname:
                return None
            default_ports = {"http": 80, "https": 443, "socks": 1080, "socks5": 1080, "anytls": 443, "hysteria": 443, "tuic": 443, "wireguard": 443}
            port = parsed.port if parsed.port is not None else default_ports.get(protocol)
            if port is None:
                return None
            username = urllib.parse.unquote(parsed.username or "")
            password = urllib.parse.unquote(parsed.password or "")
            query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            # 排序参数但保留重复项；URI fragment 中的名称不参与指纹。
            normalized_query = sorted((str(k), str(v)) for k, v in query)
            if protocol in ("socks", "socks5"):
                protocol = "socks5"
            payload = {
                "protocol": protocol,
                "server": (parsed.hostname or "").lower(),
                "port": port,
                "username": username,
                "password": password,
                # 路径可能承载协议配置（例如 SSH/Mieru/custom URI），必须参与指纹。
                "path": parsed.path or "",
                "query": normalized_query
            }
            return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return None

    def deduplicate_nodes(self, nodes):
        """基于完整连接参数去重，避免误删传输或安全配置不同的节点。"""
        print(f"\n--- Step 2: Performing advanced deduplication on {len(nodes)} nodes ---")
        unique_nodes_dict = {}
        unparseable_preserved = 0

        for node_link in nodes:
            raw_link = str(node_link).strip()
            if not raw_link:
                continue
            fingerprint = self.node_fingerprint(raw_link)
            if not fingerprint:
                # 未知协议或暂不支持的 URI 不应因指纹解析失败而被丢弃。
                # 对无法安全规范化的链接采用完整原文精确去重，避免误合并。
                fingerprint = "raw|" + raw_link
                if fingerprint not in unique_nodes_dict:
                    unparseable_preserved += 1
            if fingerprint not in unique_nodes_dict:
                unique_nodes_dict[fingerprint] = raw_link

        final_nodes = list(unique_nodes_dict.values())
        removed_count = len(nodes) - len(final_nodes)
        print(
            f"Deduplication complete. Removed {removed_count} duplicate nodes; "
            f"preserved {unparseable_preserved} unique unparseable/unknown links "
            f"using exact-text deduplication."
        )
        return final_nodes

    @staticmethod
    def _uri_host(server):
        host = str(server).strip()
        if ':' in host and not (host.startswith('[') and host.endswith(']')):
            return f'[{host}]'
        return host

    @staticmethod
    def _as_bool(value):
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return value != 0
        return str(value).strip().lower() in ('1', 'true', 'yes', 'on', 'enabled')

    @staticmethod
    def _valid_port(value):
        """验证单端口是否为 1-65535 的十进制整数，不接受 bool/浮点/空白混淆值。"""
        if isinstance(value, bool) or value is None:
            return False
        if isinstance(value, int):
            return 1 <= value <= 65535
        if not isinstance(value, str):
            return False
        # 不自动清理首尾空白，避免校验通过后仍把带空格的原值写入分享 URI。
        return bool(re.fullmatch(r'\d{1,5}', value)) and 1 <= int(value) <= 65535

    @staticmethod
    def _hysteria_mbps(value):
        """将 Mihomo 带单位的速率规范为 Hysteria v1 URI 所需的整数 Mbps。"""
        if isinstance(value, bool) or value is None:
            return None
        match = re.fullmatch(
            r'\s*(\d+(?:\.\d+)?)\s*(bps|Bps|Kbps|KBps|Mbps|MBps|Gbps|GBps)?\s*',
            str(value)
        )
        if not match:
            return None
        amount = float(match.group(1))
        unit = match.group(2) or 'Mbps'
        factors = {
            'bps': 0.000001, 'Bps': 0.000008,
            'Kbps': 0.001, 'KBps': 0.008,
            'Mbps': 1, 'MBps': 8,
            'Gbps': 1000, 'GBps': 8000
        }
        mbps = amount * factors[unit]
        if mbps <= 0 or not mbps.is_integer():
            return None
        return str(int(mbps))

    @staticmethod
    def _valid_port_list(value):
        """验证 Hysteria 2 多端口地址：逗号分隔的端口或闭区间。"""
        if isinstance(value, bool) or value is None:
            return False
        text = str(value)
        if not text or text != text.strip():
            return False
        for item in text.split(','):
            if re.fullmatch(r'\d{1,5}', item):
                port = int(item)
                if not 1 <= port <= 65535:
                    return False
            elif re.fullmatch(r'\d{1,5}-\d{1,5}', item):
                start, end = (int(part) for part in item.split('-', 1))
                if not 1 <= start <= end <= 65535:
                    return False
            else:
                return False
        return True

    @staticmethod
    def _safe_network_diagnostic_bucket(value):
        """Bound network diagnostic buckets; never emit malformed/raw values."""
        if value is None:
            return 'other'
        network = str(value).strip().lower()
        if not re.fullmatch(r'[a-z0-9_-]{1,32}', network):
            return 'malformed'
        known = {
            'tcp', 'raw', 'none', 'ws', 'http', 'h2', 'grpc', 'xhttp',
            'splithttp', 'httpupgrade', 'mkcp', 'kcp', 'quic', 'hysteria',
            'udp', 'tls', 'reality', 'ssh', 'wireguard'
        }
        return network if network in known else 'other'

    @staticmethod
    def _network_malformed_diagnostic_kind(value):
        """Classify malformed network values without exposing their contents."""
        if not isinstance(value, str):
            return 'non_string'
        network = value.strip()
        if not network:
            return 'empty'
        if len(network) > 32:
            return 'too_long'
        if re.search(r'[^\x00-\x7f]', network):
            return 'unicode'
        if '%' in network:
            return 'url_encoded'
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', network):
            return 'punctuation'
        return 'other'

    @staticmethod
    def _tls_mismatch_diagnostic_bucket(proxy):
        """Describe inactive TLS options using field names only, never values."""
        if 'tls' not in proxy:
            tls_state = 'missing'
        elif proxy.get('tls') is None or proxy.get('tls') == '':
            tls_state = 'empty'
        elif merge._as_bool(proxy.get('tls')):
            tls_state = 'enabled'
        else:
            tls_state = 'disabled'
        fields = [
            key for key in ('servername', 'sni', 'alpn', 'client-fingerprint',
                            'fingerprint', 'name-cert-verify')
            if proxy.get(key) not in (None, '', [], {})
        ]
        if merge._as_bool(proxy.get('skip-cert-verify')):
            fields.append('skip-cert-verify')
        return tls_state + ':' + ('+'.join(fields) if fields else 'no_options')

    @staticmethod
    def _normalize_vless_network(proxy):
        """Normalize aliases and recover contaminated TCP only with complete Reality evidence."""
        network = str(proxy.get('network') or 'tcp').strip().lower()
        if network in ('raw', 'none'):
            return 'tcp'
        if network == 'h2':
            return 'http'
        if network == 'splithttp':
            return 'xhttp'
        supported = ('tcp', 'ws', 'http', 'grpc', 'xhttp', 'httpupgrade')
        if network in supported:
            return network
        if re.fullmatch(r'tcp(?:[#?%¬].*)', network, flags=re.DOTALL):
            reality_opts = proxy.get('reality-opts')
            uuid_value = proxy.get('uuid')
            has_valid_identity = (
                isinstance(proxy.get('server'), str)
                and bool(proxy.get('server').strip())
                and merge._valid_port(proxy.get('port'))
                and isinstance(uuid_value, str)
                and bool(re.fullmatch(
                    r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
                    uuid_value
                ))
            )
            has_reality_parameters = (
                isinstance(reality_opts, dict)
                and isinstance(reality_opts.get('public-key'), str)
                and bool(reality_opts.get('public-key').strip())
                and isinstance(reality_opts.get('short-id'), str)
            )
            non_tcp_option_keys = (
                'ws-opts', 'grpc-opts', 'http-opts', 'h2-opts',
                'xhttp-opts', 'httpupgrade-opts', 'http-upgrade-opts',
                'splithttp-opts', 'kcp-opts', 'quic-opts'
            )
            has_conflicting_transport_options = any(
                proxy.get(key) not in (None, '', {}, [])
                for key in non_tcp_option_keys
            )
            security_enabled = merge._as_bool(proxy.get('tls')) or bool(reality_opts)
            if (
                has_valid_identity
                and has_reality_parameters
                and security_enabled
                and not has_conflicting_transport_options
            ):
                return 'tcp'
        return network

    @staticmethod
    def _vless_conversion_failure_reason(proxy):
        """诊断 VLESS 转换失败原因；与实际 URI 生成逻辑保持同一组约束。"""
        if proxy.get('uuid') in (None, ''):
            return 'vless_missing_uuid'

        network = merge._normalize_vless_network(proxy)
        supported_networks = ('tcp', 'ws', 'http', 'grpc', 'xhttp', 'httpupgrade')
        if network not in supported_networks:
            return 'vless_unsupported_network'

        reality_opts = proxy.get('reality-opts')
        if reality_opts not in (None, '', {}) and not isinstance(reality_opts, dict):
            return 'vless_invalid_reality_options'
        reality_enabled = isinstance(reality_opts, dict) and bool(reality_opts)
        if reality_enabled and not reality_opts.get('public-key'):
            return 'vless_missing_reality_public_key'

        if 'encryption' in proxy and not isinstance(proxy.get('encryption'), str):
            return 'vless_invalid_encryption'
        packet_encoding = proxy.get('packet-encoding')
        if packet_encoding not in (None, '') and packet_encoding not in ('xudp', 'packetaddr'):
            return 'vless_unsupported_packet_encoding'

        tls_enabled = merge._as_bool(proxy.get('tls')) or reality_enabled
        tls_options = ('servername', 'sni', 'alpn', 'client-fingerprint')

        def mapping(value):
            return isinstance(value, dict)

        if network == 'tcp':
            # TCP is the default transport; the URI builder does not need extra TCP options.
            return None
        if network == 'ws':
            options = proxy.get('ws-opts') or {}
            if not mapping(options) or not mapping(options.get('headers') or {}):
                return 'vless_invalid_ws_options'
            headers = options.get('headers') or {}
            if merge._as_bool(options.get('v2ray-http-upgrade-fast-open')):
                return 'vless_unrepresentable_httpupgrade_fast_open'
            if merge._as_bool(options.get('v2ray-http-upgrade')) and (
                any(str(key).lower() != 'host' for key in headers) or
                options.get('max-early-data') not in (None, '', 0, '0') or
                options.get('early-data-header-name') not in (None, '')
            ):
                return 'vless_unrepresentable_httpupgrade_options'
            host = headers.get('Host') or headers.get('host')
            if isinstance(host, (list, tuple)) and len(host) > 1:
                return 'vless_multiple_transport_hosts'
            if host not in (None, '') and not isinstance(host, (str, list, tuple)):
                return 'vless_invalid_transport_host'
        elif network == 'httpupgrade':
            options = proxy.get('http-upgrade-opts') or proxy.get('httpupgrade-opts') or {}
            if not mapping(options):
                return 'vless_invalid_httpupgrade_options'
            headers = options.get('headers') or {}
            if not mapping(headers) or any(str(key).lower() != 'host' for key in headers):
                return 'vless_unrepresentable_httpupgrade_headers'
            host = headers.get('Host') or headers.get('host') or options.get('host')
            if isinstance(host, (list, tuple)) and len(host) > 1:
                return 'vless_multiple_transport_hosts'
            if host not in (None, '') and not isinstance(host, (str, list, tuple)):
                return 'vless_invalid_transport_host'
            path = options.get('path', '/')
            if not isinstance(path, str) or not path:
                return 'vless_invalid_httpupgrade_path'
        elif network == 'grpc':
            options = proxy.get('grpc-opts') or {}
            if not mapping(options):
                return 'vless_invalid_grpc_options'
        elif network == 'http':
            options = proxy.get('http-opts') or proxy.get('h2-opts') or {}
            if not mapping(options):
                return 'vless_invalid_http_options'
            headers = options.get('headers') or {}
            if not mapping(headers):
                return 'vless_invalid_http_headers'
            hosts = headers.get('Host') or headers.get('host') or options.get('host') or []
            paths = options.get('path') or ['/']
            if isinstance(hosts, str):
                hosts = [hosts]
            if isinstance(paths, str):
                paths = [paths]
            if not isinstance(hosts, (list, tuple)) or not isinstance(paths, (list, tuple)):
                return 'vless_invalid_http_host_or_path'
            if len(hosts) > 1 or len(paths) > 1:
                return 'vless_multiple_transport_hosts_or_paths'
            if any(not isinstance(value, str) for value in list(hosts) + list(paths)):
                return 'vless_invalid_http_host_or_path'
        elif network == 'xhttp':
            options = proxy.get('xhttp-opts') or proxy.get('splithttp-opts') or {}
            if not mapping(options):
                return 'vless_invalid_xhttp_options'
            for key in ('path', 'host', 'mode', 'x-padding-bytes'):
                value = options.get(key)
                if value not in (None, '') and not isinstance(value, str):
                    return 'vless_invalid_xhttp_' + key.replace('-', '_')
            if options.get('extra') not in (None, '') and not mapping(options.get('extra')):
                return 'vless_invalid_xhttp_extra'

        return 'vless_conversion_failed'

    @staticmethod
    def _vmess_conversion_failure_reason(proxy):
        """仅诊断 VMess 转换失败原因；不参与或改变实际转换规则。"""
        if proxy.get('uuid') in (None, ''):
            return 'vmess_missing_uuid'

        network = str(proxy.get('network') or 'tcp').strip().lower()
        if network in ('raw', 'none'):
            network = 'tcp'
        supported_networks = ('tcp', 'ws', 'http', 'h2', 'grpc', 'httpupgrade')
        if network not in supported_networks:
            safe_network = network[:32]
            if not re.fullmatch(r'[a-z0-9_-]{1,32}', safe_network):
                safe_network = 'other'
            return 'vmess_unsupported_network', safe_network

        def is_mapping(value):
            return isinstance(value, dict)

        def single_value_failure(*values):
            for value in values:
                if isinstance(value, str):
                    continue
                if isinstance(value, (list, tuple)):
                    if len(value) > 1:
                        return 'vmess_multiple_transport_hosts_or_paths'
                    continue
                return 'vmess_invalid_transport_options'
            return None

        if network == 'ws':
            options = proxy.get('ws-opts') or {}
            if not is_mapping(options) or not is_mapping(options.get('headers') or {}):
                return 'vmess_invalid_transport_options'
            if merge._as_bool(options.get('v2ray-http-upgrade-fast-open')):
                return 'vmess_unrepresentable_httpupgrade_fast_open'
            if merge._as_bool(options.get('v2ray-http-upgrade')) and (
                    options.get('max-early-data') not in (None, '', 0, '0') or
                    options.get('early-data-header-name') not in (None, '')):
                return 'vmess_unrepresentable_httpupgrade_early_data'
        elif network == 'http':
            options = proxy.get('http-opts') or {}
            if not is_mapping(options):
                return 'vmess_invalid_transport_options'
            if str(options.get('method') or 'GET').upper() != 'GET':
                return 'vmess_unrepresentable_http_method'
            headers = options.get('headers') or {}
            if not is_mapping(headers):
                return 'vmess_invalid_transport_options'
            if any(str(key).lower() != 'host' for key in headers):
                return 'vmess_unrepresentable_http_headers'
            hosts = headers.get('Host') or headers.get('host') or []
            paths = options.get('path') or ['/']
            failure = single_value_failure(hosts, paths)
            if failure:
                return failure
        elif network == 'h2':
            options = proxy.get('h2-opts') or proxy.get('http-opts') or {}
            if not is_mapping(options):
                return 'vmess_invalid_transport_options'
            headers = options.get('headers') or {}
            if not is_mapping(headers):
                return 'vmess_invalid_transport_options'
            hosts = headers.get('Host') or headers.get('host') or options.get('host') or []
            paths = options.get('path') or ['/']
            failure = single_value_failure(hosts, paths)
            if failure:
                return failure
        elif network == 'grpc':
            options = proxy.get('grpc-opts') or {}
            if not is_mapping(options):
                return 'vmess_invalid_transport_options'
            if not options.get('grpc-service-name'):
                return 'vmess_missing_grpc_service_name'
        elif network == 'httpupgrade':
            options = proxy.get('http-upgrade-opts') or proxy.get('httpupgrade-opts') or {}
            if not is_mapping(options) or not is_mapping(options.get('headers') or {}):
                return 'vmess_invalid_transport_options'
        else:
            options = proxy.get('tcp-opts') or {}
            if not is_mapping(options):
                return 'vmess_invalid_transport_options'
            header = options.get('header') or {}
            if not is_mapping(header):
                return 'vmess_invalid_transport_options'
            header_type = str(header.get('type') or 'none').lower()
            if header_type not in ('none', 'http'):
                return 'vmess_unsupported_tcp_header'
            if header_type == 'http':
                request = header.get('request') or {}
                if not is_mapping(request):
                    return 'vmess_invalid_transport_options'
                headers = request.get('headers') or {}
                if not is_mapping(headers):
                    return 'vmess_invalid_transport_options'
                hosts = headers.get('Host') or headers.get('host') or []
                paths = request.get('path') or ['/']
                failure = single_value_failure(hosts, paths)
                if failure:
                    return failure

        tls_enabled = merge._as_bool(proxy.get('tls'))
        tls_options = ('servername', 'sni', 'alpn', 'client-fingerprint',
                       'fingerprint', 'name-cert-verify')
        has_tls_options = (
            any(proxy.get(key) not in (None, '', [], {}) for key in tls_options) or
            merge._as_bool(proxy.get('skip-cert-verify'))
        )
        if proxy.get('certificate') or proxy.get('private-key'):
            return 'vmess_unrepresentable_tls_credentials'
        return 'vmess_conversion_failed'

    def clash_to_share_link(self, proxy):
        """转换节点，并记录无法转换的具体原因。"""
        self._last_conversion_failure_reason = None
        self._last_conversion_failure_network = None
        link = self._clash_to_share_link_impl(proxy)
        if link:
            return link
        if not isinstance(proxy, dict):
            reason = 'invalid_proxy'
        else:
            protocol = str(proxy.get('type', '')).lower()
            server, port = proxy.get('server'), proxy.get('port')
            if protocol == 'wireguard':
                peers = proxy.get('peers') or []
                peer = peers[0] if isinstance(peers, list) and peers and isinstance(peers[0], dict) else {}
                server = peer.get('server') or server
                port = peer.get('port') or port
            if not protocol:
                reason = 'missing_protocol'
            elif not server:
                reason = 'missing_server'
            elif port in (None, '') and not (
                (protocol == 'mieru' and proxy.get('port-range')) or
                (protocol in ('hysteria2', 'hy2') and proxy.get('ports'))
            ) and protocol != 'hysteria':
                reason = 'missing_port'
            elif protocol not in ('hysteria', 'mieru', 'hysteria2', 'hy2') and not self._valid_port(port):
                reason = 'invalid_port'
            elif protocol in ('hysteria2', 'hy2') and (
                (proxy.get('ports') not in (None, '') and not self._valid_port_list(proxy.get('ports'))) or
                (proxy.get('ports') in (None, '') and not self._valid_port(port))
            ):
                reason = 'invalid_hysteria2_ports'
            elif protocol == 'hysteria' and port not in (None, '') and not self._valid_port(port):
                reason = 'invalid_port'
            elif protocol == 'vless':
                reason = self._vless_conversion_failure_reason(proxy)
            elif protocol == 'vmess':
                diagnostic = self._vmess_conversion_failure_reason(proxy)
                if isinstance(diagnostic, tuple):
                    reason, self._last_conversion_failure_network = diagnostic
                else:
                    reason = diagnostic
            elif protocol in ('http', 'socks5', 'socks'):
                username, password = proxy.get('username'), proxy.get('password')
                if proxy.get('headers'):
                    reason = 'unsupported_headers'
                elif proxy.get('alpn'):
                    reason = 'unsupported_alpn'
                elif protocol in ('socks5', 'socks') and ((username not in (None, '')) != (password not in (None, ''))):
                    reason = 'incomplete_socks5_auth'
                elif protocol in ('socks5', 'socks') and (proxy.get('sni') or proxy.get('servername')):
                    reason = 'unsupported_sni'
                else:
                    reason = 'unsupported_option_or_invalid_value'
            elif protocol == 'snell':
                obfs_opts = proxy.get('obfs-opts') or {}
                version = proxy.get('version', 1)
                try:
                    version = int(version)
                except (TypeError, ValueError):
                    version = 0
                if proxy.get('psk') in (None, ''):
                    reason = 'missing_snell_psk'
                elif version not in range(1, 7):
                    reason = 'invalid_snell_version'
                elif not isinstance(obfs_opts, dict):
                    reason = 'invalid_snell_obfs_options'
                elif str(obfs_opts.get('mode') or '').lower() not in ('', 'http', 'tls'):
                    reason = 'unsupported_snell_obfs_mode'
                elif any(key not in ('mode', 'host') for key in obfs_opts):
                    reason = 'unsupported_snell_obfs_option'
                elif (self._as_bool(proxy.get('udp')) or self._as_bool(proxy.get('reuse'))
                      or proxy.get('userkey') or str(proxy.get('mode') or '').lower() not in ('', 'default')
                      or proxy.get('client-fingerprint') not in (None, '', 'chrome')):
                    reason = 'unsupported_snell_uri_option'
                else:
                    reason = 'snell_conversion_failed'
            elif protocol == 'ssh':
                reason = 'ssh_share_link_not_portable'
            elif protocol == 'ssr':
                required = ('password', 'cipher', 'protocol', 'obfs')
                missing = [key for key in required if proxy.get(key) in (None, '')]
                reason = 'missing_required_field' if missing else 'unsupported_protocol'
            elif protocol == 'mieru':
                username, password = proxy.get('username'), proxy.get('password')
                port_range = proxy.get('port-range')
                transport = str(proxy.get('transport') or 'TCP').upper()
                if username in (None, '') or password in (None, ''):
                    reason = 'missing_mieru_auth'
                elif bool(port) == bool(port_range):
                    reason = 'invalid_mieru_port_configuration'
                elif transport not in ('TCP', 'UDP'):
                    reason = 'unsupported_mieru_transport'
                elif port_range and not re.fullmatch(r'\d{1,5}-\d{1,5}', str(port_range)):
                    reason = 'invalid_mieru_port_range'
                elif port_range and not (
                    1 <= int(str(port_range).split('-', 1)[0]) <=
                    int(str(port_range).split('-', 1)[1]) <= 65535
                ):
                    reason = 'invalid_mieru_port_range'
                elif not port_range and (
                    not str(port).isdigit() or not 1 <= int(port) <= 65535
                ):
                    reason = 'invalid_mieru_port'
                else:
                    reason = 'mieru_conversion_failed'
            else:
                reason = 'missing_required_field_or_unsupported_option'
        self._last_conversion_failure_reason = reason
        return None

    @staticmethod
    def _record_conversion_failure(protocol, reason, protocol_reason_counts, reason_counts):
        protocol = str(protocol or 'unknown').lower()
        protocol_reasons = protocol_reason_counts.setdefault(protocol, {})
        protocol_reasons[reason] = protocol_reasons.get(reason, 0) + 1
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    @staticmethod
    def _sanitize_conversion_failure_value(value, key=None):
        """Redact credentials and endpoint identifiers while preserving network verbatim."""
        normalized_key = str(key or '').strip().lower().replace('_', '-')
        if normalized_key == 'network':
            if not isinstance(value, str):
                return value
            # Preserve the malformed prefix, but redact embedded share URIs and UUIDs.
            value = re.sub(
                r'(?i)(vless|vmess|trojan|ssr?|hysteria2?|hy2|tuic|socks5?)(?:://|%3a%2f%2f).*',
                lambda match: match.group(1) + '://[REDACTED_URI]',
                value
            )
            value = re.sub(
                r'(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
                '[REDACTED_UUID]', value
            )
            return value
        if normalized_key in {
            'uuid', 'password', 'passwd', 'username', 'user', 'auth', 'auth-str',
            'token', 'secret', 'private-key', 'privatekey', 'client-key',
            'certificate', 'server', 'server-name', 'address'
        }:
            return '[REDACTED]'
        if isinstance(value, dict):
            return {
                item_key: merge._sanitize_conversion_failure_value(item_value, item_key)
                for item_key, item_value in value.items()
            }
        if isinstance(value, list):
            return [merge._sanitize_conversion_failure_value(item) for item in value]
        if isinstance(value, tuple):
            return [merge._sanitize_conversion_failure_value(item) for item in value]
        return value

    @staticmethod
    def _write_conversion_failure_report(report_path, failures):
        """Write a local, redacted YAML-node report without exposing raw credentials."""
        lines = [
            'Clash proxy conversion failure report',
            f'Total failures: {len(failures)}',
            'Privacy: credentials, UUIDs, private keys, certificates and endpoint addresses are redacted.',
            'Network values are retained for diagnosis; embedded share URIs and UUIDs are redacted.',
            'Original share URI: unavailable for Clash YAML input; the source node is shown below.',
            ''
        ]
        for index, failure in enumerate(failures, 1):
            proxy = failure.get('proxy') if isinstance(failure.get('proxy'), dict) else {}
            safe_proxy = merge._sanitize_conversion_failure_value(proxy)
            lines.extend([
                '=' * 72,
                f'[{index}] Protocol: {failure.get("protocol") or "unknown"}',
                f'Reason: {failure.get("reason") or "conversion_failed"}',
                f'Source ID: {failure.get("source_id") if failure.get("source_id") is not None else "unknown"}',
                f'Source remarks: {failure.get("source_remarks") or "unknown"}',
                f'Node name: {proxy.get("name") or "unknown"}',
                'Original YAML proxy (sensitive values redacted; network preserved):',
                yaml.safe_dump(
                    safe_proxy, allow_unicode=True, sort_keys=False,
                    default_flow_style=False
                ).rstrip(),
                ''
            ])
        temp_path = report_path + '.tmp'
        try:
            with open(temp_path, 'w', encoding='utf-8', newline='\n') as report_file:
                report_file.write('\n'.join(lines).rstrip() + '\n')
                report_file.flush()
                os.fsync(report_file.fileno())
            os.replace(temp_path, report_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def _clash_to_share_link_impl(self, proxy):
        """将 Clash/Mihomo 节点转换为 Clash Verge Rev 可识别的分享 URI。"""
        try:
            if not isinstance(proxy, dict):
                return None
            protocol = str(proxy.get('type', '')).lower()
            if not protocol:
                return None

            # Hysteria 允许省略端口；Mieru 使用 port 或 port-range；
            # WireGuard 的端点通常定义在第一个 peer 中，其余协议使用顶层 port。
            port = proxy.get('port')
            if protocol == 'wireguard':
                peers = proxy.get('peers') or []
                peer = peers[0] if isinstance(peers, list) and peers and isinstance(peers[0], dict) else {}
                port = peer.get('port') or port
            elif protocol not in ('hysteria', 'mieru', 'hysteria2', 'hy2') and not self._valid_port(port):
                return None
            if protocol == 'wireguard' and not self._valid_port(port):
                return None
            if protocol == 'hysteria' and port not in (None, '') and not self._valid_port(port):
                return None
            if protocol in ('hysteria2', 'hy2'):
                if proxy.get('ports') not in (None, ''):
                    if not self._valid_port_list(proxy.get('ports')):
                        return None
                elif not self._valid_port(port):
                    return None

            remarks = str(proxy.get('name', ''))
            remarks_encoded = urllib.parse.quote(remarks)

            if protocol == 'vmess':
                server, port, uuid = proxy.get('server'), proxy.get('port'), proxy.get('uuid')
                if not all([server, port, uuid]):
                    return None
                network = str(proxy.get('network') or 'tcp').strip().lower()
                if network in ('raw', 'none'):
                    network = 'tcp'
                if network not in ('tcp', 'ws', 'http', 'h2', 'grpc', 'httpupgrade'):
                    return None
                vmess_config = {
                    "v": "2", "ps": remarks, "add": server, "port": str(port),
                    "id": uuid, "aid": str(proxy.get('alterId', 0)),
                    "scy": proxy.get('cipher') or 'auto',
                    "net": 'tcp' if network == 'http' else network,
                    "type": "none", "host": "", "path": "", "tls": "", "sni": ""
                }
                if network == 'ws':
                    ws_opts = proxy.get('ws-opts') or {}
                    if not isinstance(ws_opts, dict):
                        return None
                    headers = ws_opts.get('headers') or {}
                    if not isinstance(headers, dict):
                        return None
                    if self._as_bool(ws_opts.get('v2ray-http-upgrade-fast-open')):
                        return None
                    if self._as_bool(ws_opts.get('v2ray-http-upgrade')):
                        if (any(str(key).lower() != 'host' for key in headers) or
                                ws_opts.get('max-early-data') not in (None, '', 0, '0') or
                                ws_opts.get('early-data-header-name') not in (None, '')):
                            return None
                        # Mihomo's legacy VMess QR parser recognizes net=httpupgrade
                        # and reconstructs ws-opts.v2ray-http-upgrade from that value.
                        vmess_config['net'] = 'httpupgrade'
                    host = headers.get('Host') or headers.get('host') or ''
                    if isinstance(host, (list, tuple)):
                        if len(host) > 1:
                            return None
                        host = host[0] if host else ''
                    if not isinstance(host, str):
                        return None
                    vmess_config['host'] = host
                    vmess_config['path'] = ws_opts.get('path', '/')
                elif network == 'http':
                    http_opts = proxy.get('http-opts') or {}
                    if not isinstance(http_opts, dict):
                        return None
                    method = str(http_opts.get('method') or 'GET').upper()
                    if method != 'GET':
                        return None
                    headers = http_opts.get('headers') or {}
                    if not isinstance(headers, dict):
                        return None
                    if any(str(key).lower() != 'host' for key in headers):
                        return None
                    hosts = headers.get('Host') or headers.get('host') or []
                    paths = http_opts.get('path') or ['/']
                    if isinstance(hosts, str):
                        hosts = [hosts]
                    if isinstance(paths, str):
                        paths = [paths]
                    if (not isinstance(hosts, (list, tuple)) or
                            not isinstance(paths, (list, tuple)) or
                            len(hosts) > 1 or len(paths) > 1):
                        return None
                    if hosts and not isinstance(hosts[0], str):
                        return None
                    if paths and not isinstance(paths[0], str):
                        return None
                    vmess_config['type'] = 'http'
                    vmess_config['host'] = hosts[0] if hosts else ''
                    vmess_config['path'] = paths[0] if paths else '/'
                elif network == 'h2':
                    h2_opts = proxy.get('h2-opts') or proxy.get('http-opts') or {}
                    headers = h2_opts.get('headers') or {}
                    hosts = headers.get('Host') or headers.get('host') or h2_opts.get('host') or []
                    paths = h2_opts.get('path') or ['/']
                    if isinstance(hosts, str): hosts = [hosts]
                    if isinstance(paths, str): paths = [paths]
                    if len(hosts) > 1 or len(paths) > 1: return None
                    vmess_config['host'] = hosts[0] if hosts else ''
                    vmess_config['path'] = paths[0] if paths else '/'
                elif network == 'grpc':
                    grpc_opts = proxy.get('grpc-opts') or {}
                    service_name = grpc_opts.get('grpc-service-name')
                    if not service_name: return None
                    vmess_config['path'] = service_name
                elif network == 'httpupgrade':
                    upgrade_opts = proxy.get('http-upgrade-opts') or proxy.get('httpupgrade-opts') or {}
                    headers = upgrade_opts.get('headers') or {}
                    vmess_config['host'] = headers.get('Host', '')
                    vmess_config['path'] = upgrade_opts.get('path', '/')
                else:
                    tcp_opts = proxy.get('tcp-opts') or {}
                    header = tcp_opts.get('header') or {}
                    header_type = str(header.get('type') or 'none').lower()
                    if header_type not in ('none', 'http'): return None
                    if header_type == 'http':
                        request = header.get('request') or {}
                        headers = request.get('headers') or {}
                        hosts = headers.get('Host') or headers.get('host') or []
                        paths = request.get('path') or ['/']
                        if isinstance(hosts, str): hosts = [hosts]
                        if isinstance(paths, str): paths = [paths]
                        if len(hosts) > 1 or len(paths) > 1: return None
                        vmess_config['type'] = 'http'
                        vmess_config['host'] = ','.join(map(str, hosts))
                        vmess_config['path'] = paths[0] if paths else '/'
                tls_enabled = self._as_bool(proxy.get('tls'))
                tls_options = ('servername', 'sni', 'alpn', 'client-fingerprint',
                               'fingerprint', 'name-cert-verify')
                if tls_enabled:
                    vmess_config['tls'] = 'tls'
                    vmess_config['sni'] = proxy.get('servername') or proxy.get('sni') or vmess_config['host']
                    alpn = proxy.get('alpn')
                    if alpn not in (None, ''):
                        vmess_config['alpn'] = ','.join(map(str, alpn)) if isinstance(alpn, (list, tuple)) else str(alpn)
                    if proxy.get('client-fingerprint'):
                        vmess_config['fp'] = proxy.get('client-fingerprint')
                    if self._as_bool(proxy.get('skip-cert-verify')):
                        vmess_config['insecure'] = '1'
                    if proxy.get('fingerprint'):
                        vmess_config['pcs'] = proxy.get('fingerprint')
                    if proxy.get('name-cert-verify'):
                        vmess_config['vcn'] = proxy.get('name-cert-verify')
                if proxy.get('certificate') or proxy.get('private-key'): return None
                return f"vmess://{base64_encode(json.dumps(vmess_config, separators=(',', ':')))}"

            elif protocol == 'vless':
                server, port, uuid = proxy.get('server'), proxy.get('port'), proxy.get('uuid')
                if not all([server, port, uuid]):
                    return None
                network = self._normalize_vless_network(proxy)
                if network not in ('tcp', 'ws', 'http', 'grpc', 'xhttp', 'httpupgrade'):
                    return None
                reality_opts = proxy.get('reality-opts')
                if reality_opts not in (None, '', {}) and not isinstance(reality_opts, dict):
                    return None
                reality_enabled = isinstance(reality_opts, dict) and bool(reality_opts)
                tls_enabled = self._as_bool(proxy.get('tls')) or reality_enabled
                tls_options = ('servername', 'sni', 'alpn', 'client-fingerprint')
                params = {
                    'type': network,
                    'security': 'reality' if reality_enabled else ('tls' if tls_enabled else 'none')
                }
                if proxy.get('flow'):
                    params['flow'] = proxy.get('flow')
                if 'encryption' in proxy:
                    encryption = proxy.get('encryption')
                    if not isinstance(encryption, str):
                        return None
                    # Empty encryption is Mihomo's default and need not be encoded.
                    if encryption:
                        params['encryption'] = encryption

                if 'packet-encoding' in proxy:
                    packet_encoding = proxy.get('packet-encoding')
                    if packet_encoding == '':
                        params['packetEncoding'] = 'none'
                    elif packet_encoding == 'xudp':
                        params['packetEncoding'] = 'xudp'
                    elif packet_encoding == 'packetaddr':
                        # Mihomo's V-share parser maps "packet" to packet-addr.
                        params['packetEncoding'] = 'packet'
                    elif packet_encoding is not None:
                        return None
                if tls_enabled:
                    sni = proxy.get('servername') or proxy.get('sni', '')
                    if sni:
                        params['sni'] = sni
                    if proxy.get('client-fingerprint'):
                        params['fp'] = proxy.get('client-fingerprint')
                    alpn = proxy.get('alpn')
                    if alpn not in (None, ''):
                        params['alpn'] = ','.join(map(str, alpn)) if isinstance(alpn, (list, tuple)) else str(alpn)
                    if self._as_bool(proxy.get('skip-cert-verify')):
                        params['allowInsecure'] = 1
                if reality_enabled:
                    public_key = reality_opts.get('public-key')
                    if not public_key:
                        return None
                    params['pbk'] = public_key
                    if reality_opts.get('short-id'):
                        params['sid'] = reality_opts.get('short-id')
                    if reality_opts.get('spider-x'):
                        params['spx'] = reality_opts.get('spider-x')

                if network == 'ws':
                    ws_opts = proxy.get('ws-opts') or {}
                    if not isinstance(ws_opts, dict):
                        return None
                    headers = ws_opts.get('headers') or {}
                    if not isinstance(headers, dict):
                        return None
                    if self._as_bool(ws_opts.get('v2ray-http-upgrade-fast-open')):
                        return None
                    if self._as_bool(ws_opts.get('v2ray-http-upgrade')):
                        if (any(str(key).lower() != 'host' for key in headers) or
                                ws_opts.get('max-early-data') not in (None, '', 0, '0') or
                                ws_opts.get('early-data-header-name') not in (None, '')):
                            return None
                        params['type'] = 'httpupgrade'
                    host = headers.get('Host') or headers.get('host')
                    if isinstance(host, (list, tuple)):
                        if len(host) > 1:
                            return None
                        host = host[0] if host else ''
                    if host not in (None, ''):
                        if not isinstance(host, str):
                            return None
                        params['host'] = host
                    params['path'] = ws_opts.get('path', '/')
                    max_early_data = ws_opts.get('max-early-data')
                    if max_early_data not in (None, '', 0, '0'):
                        try:
                            early_data_size = int(max_early_data)
                        except (TypeError, ValueError):
                            return None
                        if early_data_size <= 0:
                            return None
                        params['ed'] = str(early_data_size)
                    early_data_header = ws_opts.get('early-data-header-name')
                    if early_data_header not in (None, ''):
                        if not isinstance(early_data_header, str):
                            return None
                        params['eh'] = early_data_header
                elif network == 'httpupgrade':
                    upgrade_opts = proxy.get('http-upgrade-opts') or proxy.get('httpupgrade-opts') or {}
                    if not isinstance(upgrade_opts, dict):
                        return None
                    headers = upgrade_opts.get('headers') or {}
                    if not isinstance(headers, dict) or any(str(key).lower() != 'host' for key in headers):
                        return None
                    host = headers.get('Host') or headers.get('host') or upgrade_opts.get('host')
                    if isinstance(host, (list, tuple)):
                        if len(host) > 1:
                            return None
                        host = host[0] if host else ''
                    if host not in (None, ''):
                        if not isinstance(host, str):
                            return None
                        params['host'] = host
                    path = upgrade_opts.get('path', '/')
                    if not isinstance(path, str) or not path:
                        return None
                    params['path'] = path
                elif network == 'grpc':
                    grpc_opts = proxy.get('grpc-opts') or {}
                    if grpc_opts.get('grpc-service-name'):
                        params['serviceName'] = grpc_opts.get('grpc-service-name')
                elif network in ('http', 'h2'):
                    http_opts = proxy.get('http-opts') or proxy.get('h2-opts') or {}
                    headers = http_opts.get('headers') or {}
                    hosts = headers.get('Host') or headers.get('host') or http_opts.get('host') or []
                    paths = http_opts.get('path') or ['/']
                    if isinstance(hosts, str):
                        hosts = [hosts]
                    if isinstance(paths, str):
                        paths = [paths]
                    if len(hosts) > 1 or len(paths) > 1:
                        return None
                    if hosts:
                        params['host'] = hosts[0]
                    if paths:
                        params['path'] = paths[0]
                    if http_opts.get('method'):
                        params['method'] = http_opts['method']
                elif network in ('xhttp', 'splithttp'):
                    xhttp_opts = proxy.get('xhttp-opts') or proxy.get('splithttp-opts') or {}
                    if not isinstance(xhttp_opts, dict):
                        return None
                    for key in ('path', 'host', 'mode'):
                        value = xhttp_opts.get(key)
                        if value not in (None, ''):
                            if not isinstance(value, str):
                                return None
                            params[key] = value
                    extra = xhttp_opts.get('extra')
                    if extra not in (None, ''):
                        if not isinstance(extra, dict):
                            return None
                        params['extra'] = json.dumps(extra, ensure_ascii=False, separators=(',', ':'))
                    if xhttp_opts.get('x-padding-bytes') not in (None, ''):
                        params['x_padding_bytes'] = xhttp_opts['x-padding-bytes']
                query_string = urllib.parse.urlencode(params)
                return f"vless://{uuid}@{self._uri_host(server)}:{port}?{query_string}#{remarks_encoded}"

            elif protocol == 'trojan':
                server, port, password = proxy.get('server'), proxy.get('port'), proxy.get('password')
                if not all([server, port, password]):
                    return None
                params = {'sni': proxy.get('sni') or proxy.get('servername') or server}
                if self._as_bool(proxy.get('skip-cert-verify')):
                    params['allowInsecure'] = 1
                network = str(proxy.get('network') or 'tcp').strip().lower()
                if network == 'ws':
                    ws_opts = proxy.get('ws-opts') or {}
                    if not isinstance(ws_opts, dict):
                        return None
                    ws_headers = ws_opts.get('headers') or {}
                    if not isinstance(ws_headers, dict):
                        return None
                    if self._as_bool(ws_opts.get('v2ray-http-upgrade-fast-open')):
                        return None
                    params['type'] = 'httpupgrade' if self._as_bool(ws_opts.get('v2ray-http-upgrade')) else 'ws'
                    if self._as_bool(ws_opts.get('v2ray-http-upgrade')) and (
                            any(str(key).lower() != 'host' for key in ws_headers) or
                            ws_opts.get('max-early-data') not in (None, '', 0, '0') or
                            ws_opts.get('early-data-header-name') not in (None, '')):
                        return None
                    host = ws_headers.get('Host') or ws_headers.get('host')
                    if isinstance(host, (list, tuple)):
                        if len(host) > 1:
                            return None
                        host = host[0] if host else ''
                    if host not in (None, ''):
                        if not isinstance(host, str):
                            return None
                        params['host'] = host
                    params['path'] = ws_opts.get('path', '/')
                elif network == 'httpupgrade':
                    params['type'] = 'httpupgrade'
                    upgrade_opts = proxy.get('http-upgrade-opts') or proxy.get('httpupgrade-opts') or {}
                    if not isinstance(upgrade_opts, dict):
                        return None
                    headers = upgrade_opts.get('headers') or {}
                    if not isinstance(headers, dict) or any(str(key).lower() != 'host' for key in headers):
                        return None
                    host = headers.get('Host') or headers.get('host') or upgrade_opts.get('host')
                    if isinstance(host, (list, tuple)):
                        if len(host) > 1:
                            return None
                        host = host[0] if host else ''
                    if host not in (None, ''):
                        if not isinstance(host, str):
                            return None
                        params['host'] = host
                    path = upgrade_opts.get('path', '/')
                    if not isinstance(path, str) or not path:
                        return None
                    params['path'] = path
                elif network == 'grpc':
                    params['type'] = 'grpc'
                    grpc_opts = proxy.get('grpc-opts') or {}
                    if grpc_opts.get('grpc-service-name'):
                        params['serviceName'] = grpc_opts.get('grpc-service-name')
                elif network not in ('tcp', 'none', ''):
                    print(f"  -> Unsupported Trojan transport: {network}")
                    return None
                query_string = urllib.parse.urlencode(params)
                return f"trojan://{urllib.parse.quote(str(password), safe='')}@{self._uri_host(server)}:{port}?{query_string}#{remarks_encoded}"

            elif protocol == 'ss':
                server, port = proxy.get('server'), proxy.get('port')
                password, cipher = proxy.get('password'), proxy.get('cipher')
                if not all([server, port, password, cipher]):
                    return None
                cipher = str(cipher).strip()
                if not re.fullmatch(r'[A-Za-z0-9._-]{2,64}', cipher):
                    return None
                creds = f"{cipher}:{password}"
                params = {}
                plugin = proxy.get('plugin')
                plugin_opts = proxy.get('plugin-opts') or {}
                if plugin_opts and not plugin:
                    return None
                if plugin:
                    if not isinstance(plugin_opts, dict):
                        return None
                    opts = []
                    for key, value in plugin_opts.items():
                        if isinstance(value, bool):
                            if value:
                                opts.append(str(key))
                        elif value not in (None, ''):
                            opts.append(f'{key}={value}')
                    params['plugin'] = str(plugin) + (';' + ';'.join(opts) if opts else '')
                query = urllib.parse.urlencode(params)
                query_part = ('?' + query) if query else ''
                ss_userinfo = base64.urlsafe_b64encode(creds.encode('utf-8')).decode('ascii').rstrip('=')
                return f"ss://{ss_userinfo}@{self._uri_host(server)}:{port}{query_part}#{remarks_encoded}"

            elif protocol == 'ssr':
                server, port = proxy.get('server'), proxy.get('port')
                password = proxy.get('password')
                cipher = proxy.get('cipher') or proxy.get('method')
                ssr_protocol = proxy.get('protocol')
                obfs = proxy.get('obfs')
                if not all([server, port, password is not None, cipher, ssr_protocol, obfs]):
                    return None
                try:
                    port_number = int(port)
                except (TypeError, ValueError):
                    return None
                if not 1 <= port_number <= 65535:
                    return None

                def ssr_b64(value):
                    return base64.urlsafe_b64encode(str(value).encode('utf-8')).decode('ascii').rstrip('=')

                ssr_main = (
                    f"{self._uri_host(server)}:{port_number}:{ssr_protocol}:"
                    f"{cipher}:{obfs}:{ssr_b64(password)}"
                )
                ssr_params = []
                obfs_param = proxy.get('obfs-param')
                protocol_param = proxy.get('protocol-param')
                if obfs_param not in (None, ''):
                    ssr_params.append(('obfsparam', ssr_b64(obfs_param)))
                if protocol_param not in (None, ''):
                    ssr_params.append(('protoparam', ssr_b64(protocol_param)))
                if remarks:
                    ssr_params.append(('remarks', ssr_b64(remarks)))
                ssr_payload = ssr_main
                if ssr_params:
                    ssr_payload += '/?' + urllib.parse.urlencode(ssr_params)
                return 'ssr://' + ssr_b64(ssr_payload)

            elif protocol in ['hysteria2', 'hy2']:
                server, port = proxy.get('server'), proxy.get('port')
                password = proxy.get('password') or proxy.get('auth-str') or proxy.get('auth')
                ports = proxy.get('ports')
                if not server or not password:
                    return None
                if ports not in (None, ''):
                    if not self._valid_port_list(ports):
                        return None
                    port_text = str(ports)
                else:
                    if not self._valid_port(port):
                        return None
                    port_text = str(port)

                # The standard Hysteria 2 URI has no fields for these client-only
                # tuning / custom certificate options. Refuse rather than lose them.
                if any(proxy.get(key) not in (None, '', False, [], {})
                       for key in ('up', 'down', 'bbr-profile', 'name-cert-verify',
                                   'ca', 'ca-str', 'certificate', 'private-key',
                                   'obfs-min-packet-size', 'obfs-max-packet-size',
                                   'realm-opts', 'handshake-timeout')):
                    return None
                hop_interval = proxy.get('hop-interval')
                if hop_interval not in (None, '', 30, '30', '30s'):
                    return None
                alpn = proxy.get('alpn')
                if alpn not in (None, '', ['h3'], 'h3'):
                    return None

                params = {}
                if proxy.get('sni'):
                    params['sni'] = proxy.get('sni')
                if self._as_bool(proxy.get('insecure')) or self._as_bool(proxy.get('skip-cert-verify')):
                    params['insecure'] = 1
                if proxy.get('obfs'):
                    obfs = str(proxy.get('obfs')).lower()
                    if obfs not in ('salamander', 'gecko'):
                        return None
                    params['obfs'] = obfs
                if proxy.get('obfs-password'):
                    params['obfs-password'] = proxy.get('obfs-password')
                if proxy.get('fingerprint'):
                    params['pinSHA256'] = proxy.get('fingerprint')
                ech_opts = proxy.get('ech-opts') or {}
                if ech_opts:
                    if not isinstance(ech_opts, dict) or not self._as_bool(ech_opts.get('enable')):
                        return None
                    ech_config = ech_opts.get('config')
                    if not ech_config:
                        return None
                    params['ech'] = ech_config
                query_string = urllib.parse.urlencode(params)
                query_part = f"?{query_string}" if query_string else ""
                return f"hysteria2://{urllib.parse.quote(str(password), safe='')}@{self._uri_host(server)}:{port_text}/{query_part}#{remarks_encoded}"

            elif protocol == 'hysteria':
                server, port = proxy.get('server'), proxy.get('port')
                if not server:
                    return None
                params = {}
                auth = proxy.get('auth-str') or proxy.get('auth')
                if auth:
                    params['auth'] = auth
                params['protocol'] = proxy.get('protocol') or 'udp'
                up = self._hysteria_mbps(proxy.get('up'))
                down = self._hysteria_mbps(proxy.get('down'))
                if up is None or down is None:
                    return None
                if str(proxy.get('protocol') or 'udp').lower() not in ('udp', 'wechat-video', 'faketcp'):
                    return None
                unsupported_options = (
                    'ports', 'recv-window-conn', 'recv-window', 'ca', 'ca-str',
                    'fingerprint', 'fast-open', 'disable-mtu-discovery', 'obfs-protocol',
                    'name-cert-verify', 'certificate', 'private-key'
                )
                if any(proxy.get(key) not in (None, '', False, [], {}) for key in unsupported_options):
                    return None
                params['upmbps'] = up
                params['downmbps'] = down
                sni = proxy.get('sni') or proxy.get('servername')
                if sni: params['peer'] = sni
                if proxy.get('alpn') not in (None, ''):
                    alpn = proxy.get('alpn')
                    params['alpn'] = ','.join(map(str, alpn)) if isinstance(alpn, (list, tuple)) else alpn
                obfs_password = proxy.get('obfs')
                if obfs_password not in (None, ''):
                    params['obfs'] = 'xplus'
                    params['obfsParam'] = obfs_password
                if self._as_bool(proxy.get('insecure')) or self._as_bool(proxy.get('skip-cert-verify')):
                    params['insecure'] = 1
                query_string = urllib.parse.urlencode(params)
                query_part = f"?{query_string}" if query_string else ""
                port_part = f":{port}" if port else ""
                return f"hysteria://{self._uri_host(server)}{port_part}/{query_part}#{remarks_encoded}"

            elif protocol == 'anytls':
                server, port, password = proxy.get('server'), proxy.get('port'), proxy.get('password')
                if not all([server, port, password]):
                    return None
                params = {}
                for key in ('sni', 'alpn', 'idle-session-check-interval',
                            'idle-session-timeout', 'min-idle-session'):
                    value = proxy.get(key)
                    if value not in (None, ''):
                        params[key] = ','.join(map(str, value)) if isinstance(value, (list, tuple)) else value
                if proxy.get('client-fingerprint'):
                    params['fp'] = proxy.get('client-fingerprint')
                if proxy.get('fingerprint'):
                    params['hpkp'] = proxy.get('fingerprint')
                if self._as_bool(proxy.get('insecure')) or self._as_bool(proxy.get('skip-cert-verify')):
                    params['insecure'] = 1
                if 'udp' in proxy:
                    params['udp'] = str(self._as_bool(proxy.get('udp'))).lower()
                query_string = urllib.parse.urlencode(params)
                query_part = f"?{query_string}" if query_string else ""
                return f"anytls://{urllib.parse.quote(str(password), safe='')}@{self._uri_host(server)}:{port}/{query_part}#{remarks_encoded}"

            elif protocol == 'tuic':
                server, port = proxy.get('server'), proxy.get('port')
                token = proxy.get('token')
                uuid, password = proxy.get('uuid'), proxy.get('password')
                if not server or not self._valid_port(port):
                    return None
                if token not in (None, ''):
                    if uuid not in (None, '') or password not in (None, ''):
                        return None
                    auth = urllib.parse.quote(str(token), safe='')
                else:
                    if not uuid or password in (None, ''):
                        return None
                    auth = urllib.parse.quote(str(uuid), safe='') + ':' + urllib.parse.quote(str(password), safe='')

                # DNS override and custom certificate identity/material cannot be
                # represented by the portable TUIC share-link convention.
                if any(proxy.get(key) not in (None, '', False)
                       for key in ('ip', 'name-cert-verify', 'fingerprint',
                                   'client-fingerprint', 'certificate', 'private-key',
                                   'bbr-profile')):
                    return None

                params = {}
                uri_names = {
                    'sni': 'sni',
                    'alpn': 'alpn',
                    'heartbeat-interval': 'heartbeat_interval',
                    'disable-sni': 'disable_sni',
                    'reduce-rtt': 'reduce_rtt',
                    'request-timeout': 'request_timeout',
                    'udp-relay-mode': 'udp_relay_mode',
                    'congestion-controller': 'congestion_control',
                    'max-udp-relay-packet-size': 'max_udp_relay_packet_size',
                    'max-open-streams': 'max_open_streams',
                    'fast-open': 'fast_open'
                }
                for source, target in uri_names.items():
                    value = proxy.get(source)
                    if value not in (None, ''):
                        if isinstance(value, bool):
                            value = str(value).lower()
                        params[target] = ','.join(map(str, value)) if isinstance(value, (list, tuple)) else value
                if self._as_bool(proxy.get('skip-cert-verify')) or self._as_bool(proxy.get('allow-insecure')):
                    params['allow_insecure'] = 1
                query_string = urllib.parse.urlencode(params)
                query_part = f"?{query_string}" if query_string else ""
                return f"tuic://{auth}@{self._uri_host(server)}:{port}{query_part}#{remarks_encoded}"

            elif protocol == 'http':
                server, port = proxy.get('server'), proxy.get('port')
                if not all([server, port]):
                    return None
                # 当前分享 URI 不承载自定义 HTTP headers / ALPN，遇到时不静默丢失。
                if proxy.get('headers') or proxy.get('alpn'):
                    return None
                params = {}
                sni = proxy.get('sni') or proxy.get('servername')
                tls_enabled = self._as_bool(proxy.get('tls')) or bool(sni)
                if sni:
                    params['sni'] = str(sni)
                if self._as_bool(proxy.get('skip-cert-verify')) or self._as_bool(proxy.get('insecure')):
                    params['skip-cert-verify'] = 'true'
                for key in ('fingerprint', 'ip-version'):
                    if proxy.get(key) not in (None, ''):
                        params[key] = proxy[key]
                username, password = proxy.get('username'), proxy.get('password')
                auth = ''
                if username is not None or password is not None:
                    # HTTP Basic 可表达空用户名；保留 password-only 凭据，不虚构用户名。
                    auth = urllib.parse.quote(str(username or ''), safe='')
                    auth += ':' + urllib.parse.quote(str(password or ''), safe='')
                    auth += '@'
                query_string = urllib.parse.urlencode(params)
                query_part = f"?{query_string}" if query_string else ""
                scheme = 'https' if tls_enabled else 'http'
                return f"{scheme}://{auth}{self._uri_host(server)}:{port}/{query_part}#{remarks_encoded}"

            elif protocol in ('socks5', 'socks'):
                server, port = proxy.get('server'), proxy.get('port')
                if not all([server, port]):
                    return None
                if proxy.get('headers') or proxy.get('alpn') or proxy.get('sni') or proxy.get('servername'):
                    return None
                username, password = proxy.get('username'), proxy.get('password')
                # Treat two absent/blank credentials as unauthenticated SOCKS5.
                # RFC 1929 authentication is only emitted when both fields are non-empty.
                has_username = username not in (None, '')
                has_password = password not in (None, '')
                if has_username != has_password:
                    return None
                params = {}
                if 'udp' in proxy:
                    params['udp'] = str(self._as_bool(proxy.get('udp'))).lower()
                auth = ''
                if has_username and has_password:
                    auth = urllib.parse.quote(str(username), safe='')
                    auth += ':' + urllib.parse.quote(str(password), safe='')
                    auth += '@'
                query_string = urllib.parse.urlencode(params)
                query_part = f"?{query_string}" if query_string else ""
                return f"socks5://{auth}{self._uri_host(server)}:{port}/{query_part}#{remarks_encoded}"

            elif protocol == 'mieru':
                server = proxy.get('server')
                username, password = proxy.get('username'), proxy.get('password')
                if not all([server, username, password]):
                    return None

                # Mieru simple links require a profile and one or more port/protocol
                # pairs. Mihomo's single port/port-range plus transport maps to one pair.
                port = proxy.get('port')
                port_range = proxy.get('port-range')
                if bool(port) == bool(port_range):
                    return None
                transport = str(proxy.get('transport') or 'TCP').upper()
                if transport not in ('TCP', 'UDP'):
                    return None

                multiplexing = str(proxy.get('multiplexing') or '').upper()
                if multiplexing and multiplexing not in (
                        'MULTIPLEXING_OFF', 'MULTIPLEXING_LOW',
                        'MULTIPLEXING_MIDDLE', 'MULTIPLEXING_HIGH'):
                    return None
                handshake_mode = str(proxy.get('handshake-mode') or '').upper()
                if handshake_mode and handshake_mode not in (
                        'HANDSHAKE_STANDARD', 'HANDSHAKE_NO_WAIT'):
                    return None
                mtu = proxy.get('mtu')
                if mtu not in (None, ''):
                    try:
                        mtu = int(mtu)
                    except (TypeError, ValueError):
                        return None
                    if not 1280 <= mtu <= 1400:
                        return None

                port_value = port_range if port_range else port
                if port_range:
                    if not re.fullmatch(r'\d{1,5}-\d{1,5}', str(port_range)):
                        return None
                    start_port, end_port = (int(part) for part in str(port_range).split('-', 1))
                    if not (1 <= start_port <= end_port <= 65535):
                        return None
                else:
                    try:
                        port_value = int(port)
                    except (TypeError, ValueError):
                        return None
                    if not 1 <= port_value <= 65535:
                        return None

                params = [('profile', str(proxy.get('profile') or 'default'))]
                for source, target in (
                    ('mtu', 'mtu'),
                    ('multiplexing', 'multiplexing'),
                    ('handshake-mode', 'handshake-mode'),
                    ('traffic-pattern', 'traffic-pattern')
                ):
                    value = proxy.get(source)
                    if value not in (None, ''):
                        params.append((target, str(value)))
                params.append(('port', str(port_value)))
                params.append(('protocol', transport))

                auth = (
                    urllib.parse.quote(str(username), safe='') + ':' +
                    urllib.parse.quote(str(password), safe='')
                )
                query_string = urllib.parse.urlencode(params)
                return f"mierus://{auth}@{self._uri_host(server)}?{query_string}#{remarks_encoded}"

            elif protocol == 'snell':
                server, port, psk = proxy.get('server'), proxy.get('port'), proxy.get('psk')
                if not all([server, port, psk]):
                    return None
                raw_version = proxy.get('version', 1)
                if isinstance(raw_version, bool):
                    return None
                try:
                    version = int(raw_version)
                except (TypeError, ValueError):
                    return None
                if version not in range(1, 7):
                    return None

                obfs_opts = proxy.get('obfs-opts') or {}
                if not isinstance(obfs_opts, dict):
                    return None
                obfs_mode = str(obfs_opts.get('mode') or '').lower()
                obfs_host = obfs_opts.get('host')
                if obfs_mode not in ('', 'http', 'tls'):
                    return None
                if obfs_mode == 'tls' and version != 3:
                    return None
                if obfs_mode == 'http' and version not in (3, 4, 5):
                    return None
                if not obfs_mode and obfs_host not in (None, ''):
                    return None
                if any(key not in ('mode', 'host') for key in obfs_opts):
                    return None

                # These Mihomo settings have no portable representation in the
                # commonly used snell:// URI format; never silently discard them.
                mode = str(proxy.get('mode') or '').lower()
                if (self._as_bool(proxy.get('udp')) or self._as_bool(proxy.get('reuse'))
                        or proxy.get('userkey') or mode not in ('', 'default')
                        or proxy.get('client-fingerprint') not in (None, '', 'chrome')):
                    return None

                params = [('version', str(version))]
                if obfs_mode:
                    params.append(('obfs', obfs_mode))
                if obfs_host not in (None, ''):
                    params.append(('obfs-host', str(obfs_host)))
                query = urllib.parse.urlencode(params)
                return (
                    f"snell://{urllib.parse.quote(str(psk), safe='')}@"
                    f"{self._uri_host(server)}:{port}?{query}#{remarks_encoded}"
                )

            elif protocol == 'naive':
                server, port = proxy.get('server'), proxy.get('port')
                username, password = proxy.get('username'), proxy.get('password')
                if not server or not self._valid_port(port):
                    return None
                has_username = username not in (None, '')
                has_password = password not in (None, '')
                if has_username != has_password:
                    return None

                # Naive's portable URI supports HTTPS/QUIC, Basic auth,
                # padding and extra-headers. It has no standard SNI/insecure field.
                if (proxy.get('servername') or proxy.get('sni') or
                        self._as_bool(proxy.get('insecure')) or self._as_bool(proxy.get('skip-cert-verify')) or
                        proxy.get('headers')):
                    return None
                params = {}
                if 'padding' in proxy:
                    params['padding'] = str(self._as_bool(proxy.get('padding'))).lower()
                extra_headers = proxy.get('extra-headers')
                if extra_headers not in (None, ''):
                    if not isinstance(extra_headers, str) or any(ch in extra_headers for ch in ('\x00', '\r', '\n')):
                        return None
                    params['extra-headers'] = extra_headers
                query = urllib.parse.urlencode(params)

                auth = ''
                if has_username and has_password:
                    auth = (
                        urllib.parse.quote(str(username), safe='') + ':' +
                        urllib.parse.quote(str(password), safe='') + '@'
                    )
                scheme = 'naive+quic' if self._as_bool(proxy.get('quic')) else 'naive+https'
                return f"{scheme}://{auth}{self._uri_host(server)}:{port}{('?' + query) if query else ''}#{remarks_encoded}"

            elif protocol == 'wireguard':
                private_key = proxy.get('private-key') or proxy.get('private_key')
                peers = proxy.get('peers') or []
                if isinstance(peers, list) and len(peers) > 1:
                    return None
                peer = peers[0] if isinstance(peers, list) and peers else {}
                if not isinstance(peer, dict):
                    return None
                server = peer.get('server') or proxy.get('server')
                port = peer.get('port') or proxy.get('port')
                public_key = peer.get('public-key') or peer.get('public_key') or proxy.get('public-key') or proxy.get('public_key')
                if not all([private_key, server, port, public_key]):
                    return None
                params = {}
                for key, value in (
                    ('publickey', public_key),
                    ('address', proxy.get('ip') or proxy.get('address')),
                    ('allowed-ips', peer.get('allowed-ips') or proxy.get('allowed-ips')),
                    ('pre-shared-key', peer.get('pre-shared-key') or proxy.get('pre-shared-key')),
                    ('reserved', peer.get('reserved') or proxy.get('reserved')),
                    ('mtu', proxy.get('mtu')),
                    ('dns', proxy.get('dns')),
                    ('udp', proxy.get('udp')),
                    ('remote-dns-resolve', proxy.get('remote-dns-resolve'))
                ):
                    if value not in (None, ''):
                        if isinstance(value, bool):
                            value = str(value).lower()
                        params[key] = ','.join(map(str, value)) if isinstance(value, (list, tuple)) else value
                if proxy.get('ipv6'):
                    params['address'] = ','.join(filter(None, [str(params.get('address', '')), str(proxy['ipv6'])]))
                query_string = urllib.parse.urlencode(params)
                return f"wireguard://{urllib.parse.quote(str(private_key), safe='')}@{self._uri_host(server)}:{port}/?{query_string}#{remarks_encoded}"

            return None
        except Exception:
            return None

    @staticmethod
    def _provider_headers(provider):
        raw = provider.get('header') or {}
        if not isinstance(raw, dict):
            return {}
        headers = {}
        for key, value in raw.items():
            if isinstance(value, list):
                value = value[0] if value else ''
            if value is not None and str(value):
                headers[str(key)] = str(value)
        return headers

    @staticmethod
    def _provider_name_matches(pattern, name):
        if not pattern:
            return True
        try:
            return re.search(str(pattern), name) is not None
        except re.error as exc:
            print(f"  -> Invalid Provider filter ignored: {exc}")
            return None

    def _provider_proxy_allowed(self, proxy, provider):
        """按 Provider 的名称、协议包含/排除规则判断节点是否保留。"""
        name = str(proxy.get('name') or '')
        proxy_type = str(proxy.get('type') or '').lower()

        exclude_types = provider.get('exclude_type') or []
        if isinstance(exclude_types, (list, tuple, set)):
            if proxy_type in {str(item).lower() for item in exclude_types}:
                return False
        elif exclude_types and self._provider_name_matches(exclude_types, proxy_type) is True:
            return False

        include_filter = provider.get('filter')
        if include_filter and self._provider_name_matches(include_filter, name) is False:
            return False

        exclude_filter = provider.get('exclude_filter')
        if exclude_filter and self._provider_name_matches(exclude_filter, name) is True:
            return False
        return True

    @staticmethod
    def _provider_node_name(name, provider):
        """先执行正则改名，再添加前后缀，避免前缀破坏 ^ 锚点规则。"""
        result = str(name or '')
        rules = provider.get('proxy_name') or {}

        def replacement_text(value):
            return re.sub(
                r'\$(\d+)',
                lambda match: r'\g<' + match.group(1) + '>',
                str(value)
            )

        if isinstance(rules, list):
            for rule in rules:
                if not isinstance(rule, dict) or 'pattern' not in rule:
                    continue
                try:
                    result = re.sub(
                        str(rule.get('pattern', '')),
                        replacement_text(rule.get('target', '')),
                        result
                    )
                except re.error as exc:
                    print(f"  -> Invalid Provider proxy-name rule ignored: {exc}")
        elif isinstance(rules, dict):
            for pattern, target in rules.items():
                try:
                    result = re.sub(str(pattern), replacement_text(target), result)
                except re.error as exc:
                    print(f"  -> Invalid Provider proxy-name rule ignored: {exc}")

        prefix = str(provider.get('additional_prefix') or '')
        suffix = str(provider.get('additional_suffix') or '')
        return prefix + result + suffix

    def sub_merge(self):
        url_list = self.url_list
        list_dir, merge_dir = self.list_dir, self.merge_dir

        # 仅清理本程序专用的临时目录；不再删除目录中的未知文件。
        os.makedirs(list_dir, exist_ok=True)
        os.makedirs(merge_dir, exist_ok=True)

        all_nodes_raw = []
        VALID_PROTOCOLS = ('vless://', 'vmess://', 'trojan://', 'ss://', 'ssr://', 'hy2://', 'hysteria2://', 'hysteria://', 'hy://', 'tuic://', 'anytls://', 'wireguard://', 'wg://', 'http://', 'https://', 'socks5://', 'socks://', 'naive+https://', 'naive+http://', 'naive+quic://', 'mieru://', 'mierus://', 'ssh://', 'snell://')
        headers = {'User-Agent': 'v2rayN/6.0'}
        session = requests.Session()
        unsupported_types = {}
        conversion_failures = 0
        conversion_failure_reasons = {}
        conversion_failures_by_protocol = {}
        vmess_unsupported_networks = {}
        vless_unsupported_networks = {}
        malformed_network_details = {}
        tls_mismatch_details = {}
        conversion_failure_details = []

        for item in url_list:
            item_url, item_id, item_remarks = item.get('url'), item.get('id'), item.get('remarks')
            if not item_url:
                continue
            print(f"Processing [ID: {item_id}] {item_remarks} from {item_url}")
            try:
                request_headers = dict(headers)
                provider_meta = item.get('_provider') or {}
                request_headers.update(self._provider_headers(provider_meta))
                response = session.get(item_url, headers=request_headers, timeout=(5, 25))
                response.raise_for_status()
                raw_content = response.content.decode('utf-8-sig', errors='replace').strip()
                if not raw_content:
                    raise ValueError("Downloaded content is empty.")

                found_nodes = []
                if is_base64(raw_content):
                    print("  -> Detected Base64 format, decoding...")
                    plain_text = base64_decode(raw_content)
                else:
                    print("  -> Detected Plain Text / YAML format.")
                    plain_text = raw_content

                yaml_parsed = False
                try:
                    data = yaml.safe_load(plain_text)
                    if isinstance(data, dict) and isinstance(data.get('proxies'), list):
                        print("  -> Content parsed as YAML, converting proxies...")
                        yaml_parsed = True
                        provider_meta = item.get('_provider') or {}
                        for proxy_dict in data['proxies']:
                            if not isinstance(proxy_dict, dict):
                                continue

                            proxy_data = dict(proxy_dict)
                            proxy_type = str(proxy_data.get('type') or '').lower()
                            if not self._provider_proxy_allowed(proxy_data, provider_meta):
                                continue
                            proxy_data['name'] = self._provider_node_name(
                                proxy_data.get('name'), provider_meta
                            )
                            share_link = self.clash_to_share_link(proxy_data)
                            if share_link:
                                expected_schemes = {
                                    'hy2': {'hysteria2'}, 'hysteria2': {'hysteria2'},
                                    'wg': {'wireguard'}, 'wireguard': {'wireguard'},
                                    'socks': {'socks5'}, 'http': {'http', 'https'},
                                    'naive': {'naive+https', 'naive+quic', 'naive+http'},
                                    'mieru': {'mierus'}
                                }
                                actual_scheme = share_link.split('://', 1)[0].lower()
                                allowed_schemes = expected_schemes.get(proxy_type, {proxy_type})
                                if actual_scheme not in allowed_schemes:
                                    conversion_failures += 1
                                    unsupported_types[proxy_type] = unsupported_types.get(proxy_type, 0) + 1
                                    self._record_conversion_failure(proxy_type, 'output_protocol_mismatch', conversion_failures_by_protocol, conversion_failure_reasons)
                                    conversion_failure_details.append({
                                        'protocol': proxy_type,
                                        'reason': 'output_protocol_mismatch',
                                        'source_id': item_id,
                                        'source_remarks': item_remarks,
                                        'proxy': dict(proxy_dict),
                                    })
                                    continue
                                found_nodes.append(share_link)
                            else:
                                conversion_failures += 1
                                unsupported_types[proxy_type] = unsupported_types.get(proxy_type, 0) + 1
                                reason = getattr(self, '_last_conversion_failure_reason', None) or 'conversion_failed'
                                self._record_conversion_failure(
                                    proxy_type, reason,
                                    conversion_failures_by_protocol,
                                    conversion_failure_reasons
                                )
                                conversion_failure_details.append({
                                    'protocol': proxy_type,
                                    'reason': reason,
                                    'source_id': item_id,
                                    'source_remarks': item_remarks,
                                    'proxy': dict(proxy_dict),
                                })
                                if reason in ('vless_tls_options_without_tls', 'vmess_tls_options_without_tls'):
                                    detail = proxy_type + ':' + self._tls_mismatch_diagnostic_bucket(proxy_data)
                                    tls_mismatch_details[detail] = tls_mismatch_details.get(detail, 0) + 1
                                if proxy_type == 'vmess' and reason == 'vmess_unsupported_network':
                                    network = getattr(self, '_last_conversion_failure_network', None) or 'other'
                                    vmess_unsupported_networks[network] = vmess_unsupported_networks.get(network, 0) + 1
                                elif proxy_type == 'vless' and reason == 'vless_unsupported_network':
                                    raw_network = proxy_data.get('network')
                                    network = 'tcp' if raw_network in (None, '') else str(raw_network).strip().lower()
                                    if network == 'h2':
                                        network = 'http'
                                    elif network == 'splithttp':
                                        network = 'xhttp'
                                    bucket = self._safe_network_diagnostic_bucket(network)
                                    vless_unsupported_networks[bucket] = vless_unsupported_networks.get(bucket, 0) + 1
                                    if bucket == 'malformed':
                                        detail = self._network_malformed_diagnostic_kind(proxy_data.get('network'))
                                        malformed_network_details[detail] = malformed_network_details.get(detail, 0) + 1
                except yaml.YAMLError as yaml_error:
                    if plain_text.lstrip().startswith(('proxies:', '---', 'proxy-providers:')):
                        print(f"  -> YAML parse failed: {yaml_error}")

                if not yaml_parsed:
                    raw_links = [
                        line.strip()
                        for line in plain_text.splitlines()
                        if line.strip().lower().startswith(VALID_PROTOCOLS)
                    ]
                    found_nodes = []
                    corrected_mislabeled_vless = 0
                    suspected_mislabeled_vless = {}
                    for raw_link in raw_links:
                        normalized_link = self._normalize_mislabeled_vless_share_link(raw_link)
                        if normalized_link != raw_link:
                            corrected_mislabeled_vless += 1
                        else:
                            suspected_transport = self._suspected_mislabeled_vless_transport(raw_link)
                            if suspected_transport:
                                suspected_mislabeled_vless[suspected_transport] = (
                                    suspected_mislabeled_vless.get(suspected_transport, 0) + 1
                                )
                        found_nodes.append(normalized_link)
                    if corrected_mislabeled_vless:
                        print(
                            f"Corrected mislabeled SS links with VLESS signatures: "
                            f"{corrected_mislabeled_vless}"
                        )
                    if suspected_mislabeled_vless:
                        print(
                            "Potential mislabeled SS links retained unchanged "
                            "(UUID + VLESS-style transport fields; review required): "
                            + ", ".join(
                                f"{transport}={count}"
                                for transport, count in sorted(suspected_mislabeled_vless.items())
                            )
                        )

                if found_nodes:
                    all_nodes_raw.extend(found_nodes)
                    print(f'  -> Success! Extracted {len(found_nodes)} valid node links.')
                else:
                    print("  -> 🔴🔴🔴🔴 Warning: No valid node links found.")
            except Exception as e:
                print(f"  -> 🔴🔴🔴🔴 Failed! Reason: {e}")
            finally:
                print()

        failure_report_path = os.path.join(self.merge_dir, 'conversion_failures.txt')
        if conversion_failure_details:
            try:
                self._write_conversion_failure_report(
                    failure_report_path, conversion_failure_details
                )
                print(
                    f'Conversion failure details saved to {failure_report_path} '
                    f'({len(conversion_failure_details)} records; sensitive fields redacted).'
                )
            except Exception as report_error:
                print(f'Warning: Could not write conversion failure report: {report_error}')

        if not all_nodes_raw:
            print('🔴🔴🔴🔴 Merging failed: No nodes collected; preserving previous output.')
            return False

        unique_nodes = self.deduplicate_nodes(all_nodes_raw)
        final_node_count = len(unique_nodes)
        print(f'\nTotal unique node links after deduplication: {final_node_count}')
        if final_node_count == 0:
            print('🔴🔴🔴🔴 Merging failed: All collected nodes were invalid; preserving previous output.')
            return False
        if unsupported_types:
            print("Unsupported/failed Clash proxy conversions: " + ", ".join(f"{k}={v}" for k, v in sorted(unsupported_types.items())))
        if conversion_failures:
            print(f"Clash conversion failures: {conversion_failures}")
            print("Clash conversion failure reasons: " + ", ".join(
                f"{reason}={count}" for reason, count in sorted(conversion_failure_reasons.items())
            ))
            if vmess_unsupported_networks:
                print("VMess unsupported network types: " + ", ".join(
                    f"{network}={count}" for network, count in sorted(vmess_unsupported_networks.items())
                ))
            if vless_unsupported_networks:
                print("VLESS unsupported network types: " + ", ".join(
                    f"{network}={count}" for network, count in sorted(vless_unsupported_networks.items())
                ))
            if malformed_network_details:
                print("VLESS malformed network detail (value hidden): " + ", ".join(
                    f"{kind}={count}" for kind, count in sorted(malformed_network_details.items())
                ))
            if tls_mismatch_details:
                print("TLS options without TLS detail (values hidden): " + ", ".join(
                    f"{detail}={count}" for detail, count in sorted(tls_mismatch_details.items())
                ))
            print("Clash conversion failures by protocol and reason:")
            for protocol, reasons in sorted(conversion_failures_by_protocol.items()):
                print("  " + protocol + ": " + ", ".join(
                    f"{reason}={count}" for reason, count in sorted(reasons.items())
                ))

        print('Packaging all collected nodes into a Base64 subscription...')
        final_plain_text = '\n'.join(sorted(unique_nodes))
        final_b64_content = base64_encode(final_plain_text)
        print("  -> Packaging successful.")

        merge_path_final = os.path.join(self.merge_dir, 'sub_merge_base64.txt')
        temp_path = merge_path_final + '.tmp'
        try:
            with open(temp_path, 'w', encoding='utf-8', newline='') as file:
                file.write(final_b64_content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, merge_path_final)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        if not conversion_failure_details and os.path.exists(failure_report_path):
            try:
                os.remove(failure_report_path)
            except OSError as report_error:
                print(f'Warning: Could not remove stale conversion failure report: {report_error}')
        print(f'\nDone! Output merged nodes to {merge_path_final}.')
        return True

    def readme_update(self):
        print('Updating README...')
        merge_path_final = os.path.join(self.merge_dir, 'sub_merge_base64.txt')
        if not os.path.exists(merge_path_final):
            print("Warning: Merged file not found. Skipping README update.")
            return

        with open(merge_path_final, 'r', encoding='utf-8') as f_merge:
            proxies_base64 = f_merge.read().strip()
            if proxies_base64:
                proxies = base64_decode(proxies_base64)
                top_amount = len([p for p in proxies.splitlines() if p.strip()])
            else:
                top_amount = 0

        sub_url = 'https://raw.githubusercontent.com/rzhy1/11/master/sub/sub_merge_base64.txt'
        with open(self.readme_file, 'w', encoding='utf-8') as f:
            f.write(f'[{top_amount}]({sub_url})\n')
        print('完成!\n')


if __name__ == '__main__':
    file_dir = {
        'list_dir': './sub/list/',
        'list_file': './sub/sub_list.json',
        'merge_dir': './sub/',
        'update_dir': './sub/update/',
        'readme_file': './README.md',
        'share_file': './sub/share.txt'
    }
    format_config = {}
    merge(file_dir, format_config)