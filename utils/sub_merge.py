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
            if protocol in ("naive+https", "naive+http"):
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
            if protocol not in ("vless", "trojan", "hysteria", "hysteria2", "tuic", "anytls", "wireguard", "http", "https", "socks5", "socks", "ss", "naive", "mieru", "ssh"):
                return None
            if protocol == "naive":
                parsed_naive = urllib.parse.urlsplit(raw if raw.startswith("naive+") else "naive+" + raw)
                if not parsed_naive.hostname:
                    return None
                return json.dumps({
                    "protocol": "naive",
                    "scheme": parsed_naive.scheme.lower(),
                    "server": parsed_naive.hostname.lower(),
                    "port": parsed_naive.port or (443 if parsed_naive.scheme.endswith("https") else 80),
                    "username": urllib.parse.unquote(parsed_naive.username or ""),
                    "password": urllib.parse.unquote(parsed_naive.password or ""),
                    "query": sorted(urllib.parse.parse_qsl(parsed_naive.query, keep_blank_values=True))
                }, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            parsed = urllib.parse.urlsplit(protocol + "://" + raw)
            if protocol == "ss" and (not parsed.hostname or not parsed.port or not parsed.username):
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
            if not parsed.hostname:
                return None
            default_ports = {"http": 80, "https": 443, "socks": 1080, "socks5": 1080, "anytls": 443, "hysteria": 443, "tuic": 443, "wireguard": 443}
            port = parsed.port or default_ports.get(protocol)
            if not port:
                return None
            username = urllib.parse.unquote(parsed.username or "")
            password = urllib.parse.unquote(parsed.password or "")
            query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            # 排序参数但保留重复项；URI fragment 中的名称不参与指纹。
            normalized_query = sorted((str(k).lower(), str(v)) for k, v in query)
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

    def clash_to_share_link(self, proxy):
        """转换节点，并记录无法转换的具体原因。"""
        self._last_conversion_failure_reason = None
        link = self._clash_to_share_link_impl(proxy)
        if link:
            return link
        if not isinstance(proxy, dict):
            reason = 'invalid_proxy'
        else:
            protocol = str(proxy.get('type', '')).lower()
            server, port = proxy.get('server'), proxy.get('port')
            if not protocol:
                reason = 'missing_protocol'
            elif not server:
                reason = 'missing_server'
            elif not port:
                reason = 'missing_port'
            elif protocol == 'ss' and (proxy.get('plugin') or proxy.get('plugin-opts')):
                reason = 'unsupported_plugin_options'
            elif protocol in ('http', 'socks5', 'socks'):
                if proxy.get('headers'):
                    reason = 'unsupported_headers'
                elif proxy.get('alpn'):
                    reason = 'unsupported_alpn'
                elif (proxy.get('sni') or proxy.get('servername')) and str(proxy.get('sni') or proxy.get('servername')).lower() != str(server).lower():
                    reason = 'unsupported_sni'
                elif proxy.get('password') is not None and proxy.get('username') is None:
                    reason = 'password_without_username'
                elif proxy.get('username') is not None and ':' in str(proxy.get('username')):
                    reason = 'username_contains_colon'
                else:
                    reason = 'unsupported_option_or_invalid_value'
            elif protocol == 'ssr':
                reason = 'unsupported_protocol'
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

    def _clash_to_share_link_impl(self, proxy):
        """将 Clash/Mihomo 节点转换为 Clash Verge Rev 可识别的分享 URI。"""
        try:
            if not isinstance(proxy, dict):
                return None
            protocol = str(proxy.get('type', '')).lower()
            if not protocol:
                return None

            remarks = str(proxy.get('name', ''))
            remarks_encoded = urllib.parse.quote(remarks)

            if protocol == 'vmess':
                server, port, uuid = proxy.get('server'), proxy.get('port'), proxy.get('uuid')
                if not all([server, port, uuid]):
                    return None
                vmess_config = {
                    "v": "2",
                    "ps": remarks,
                    "add": server,
                    "port": port,
                    "id": uuid,
                    "aid": proxy.get('alterId', 0),
                    "scy": proxy.get('cipher', 'auto'),
                    "net": proxy.get('network', 'tcp'),
                    "type": "none",
                    "host": "",
                    "path": "",
                    "tls": "",
                    "sni": ""
                }
                if vmess_config['net'] == 'ws':
                    ws_opts = proxy.get('ws-opts') or {}
                    headers = ws_opts.get('headers') or {}
                    vmess_config['host'] = headers.get('Host', '')
                    vmess_config['path'] = ws_opts.get('path', '/')
                if proxy.get('tls'):
                    vmess_config['tls'] = 'tls'
                    vmess_config['sni'] = proxy.get('servername') or proxy.get('sni') or vmess_config['host']
                return f"vmess://{base64_encode(json.dumps(vmess_config, separators=(',', ':')))}"

            elif protocol == 'vless':
                server, port, uuid = proxy.get('server'), proxy.get('port'), proxy.get('uuid')
                if not all([server, port, uuid]):
                    return None
                params = {
                    'type': proxy.get('network', 'tcp'),
                    'security': 'tls' if proxy.get('tls') else 'none'
                }
                if proxy.get('flow'):
                    params['flow'] = proxy.get('flow')
                if params['security'] == 'tls':
                    sni = proxy.get('servername') or proxy.get('sni', '')
                    if sni:
                        params['sni'] = sni
                    if proxy.get('client-fingerprint'):
                        params['fp'] = proxy.get('client-fingerprint')
                    reality_opts = proxy.get('reality-opts')
                    if isinstance(reality_opts, dict):
                        params['security'] = 'reality'
                        params['pbk'] = reality_opts.get('public-key', '')
                        if reality_opts.get('short-id'):
                            params['sid'] = reality_opts.get('short-id')
                        if reality_opts.get('spider-x'):
                            params['spx'] = reality_opts.get('spider-x')
                if params['type'] == 'ws':
                    ws_opts = proxy.get('ws-opts') or {}
                    headers = ws_opts.get('headers') or {}
                    if headers.get('Host'):
                        params['host'] = headers.get('Host')
                    params['path'] = ws_opts.get('path', '/')
                elif params['type'] == 'grpc':
                    grpc_opts = proxy.get('grpc-opts') or {}
                    if grpc_opts.get('grpc-service-name'):
                        params['serviceName'] = grpc_opts.get('grpc-service-name')
                elif params['type'] in ('http', 'h2'):
                    http_opts = proxy.get('http-opts') or {}
                    headers = http_opts.get('headers') or {}
                    hosts = headers.get('Host') or headers.get('host') or []
                    paths = http_opts.get('path') or ['/']
                    if isinstance(hosts, str):
                        hosts = [hosts]
                    if isinstance(paths, str):
                        paths = [paths]
                    if hosts:
                        params['host'] = hosts[0]
                    if paths:
                        params['path'] = paths[0]
                elif params['type'] in ('xhttp', 'splithttp'):
                    xhttp_opts = proxy.get('xhttp-opts') or proxy.get('splithttp-opts') or {}                    if xhttp_opts.get('path'):
                        params['path'] = xhttp_opts['path']
                    if xhttp_opts.get('host'):
                        params['host'] = xhttp_opts['host']
                    if xhttp_opts.get('mode'):
                        params['mode'] = xhttp_opts['mode']
                    if xhttp_opts.get('extra'):
                        params['extra'] = json.dumps(xhttp_opts['extra'], ensure_ascii=False, separators=(',', ':'))
                query_string = urllib.parse.urlencode(params)
                return f"vless://{uuid}@{self._uri_host(server)}:{port}?{query_string}#{remarks_encoded}"

            elif protocol == 'trojan':
                server, port, password = proxy.get('server'), proxy.get('port'), proxy.get('password')
                if not all([server, port, password]):
                    return None
                params = {'sni': proxy.get('sni') or proxy.get('servername') or server}
                if proxy.get('skip-cert-verify'):
                    params['allowInsecure'] = 1
                network = str(proxy.get('network') or 'tcp').lower()
                if network == 'ws':
                    params['type'] = 'ws'
                    ws_opts = proxy.get('ws-opts') or {}
                    ws_headers = ws_opts.get('headers') or {}
                    if ws_headers.get('Host'):
                        params['host'] = ws_headers.get('Host')
                    params['path'] = ws_opts.get('path', '/')
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
                return f"ss://{base64_encode(creds)}@{self._uri_host(server)}:{port}{query_part}#{remarks_encoded}"

            elif protocol in ['hysteria2', 'hy2']:
                server, port = proxy.get('server'), proxy.get('port')
                password = proxy.get('password') or proxy.get('auth-str') or proxy.get('auth')
                if not all([server, port, password]):
                    return None
                params = {}
                if proxy.get('sni'):
                    params['sni'] = proxy.get('sni')
                if proxy.get('insecure') or proxy.get('skip-cert-verify'):
                    params['insecure'] = 1
                if proxy.get('obfs'):
                    params['obfs'] = proxy.get('obfs')
                if proxy.get('obfs-password'):
                    params['obfs-password'] = proxy.get('obfs-password')
                query_string = urllib.parse.urlencode(params)
                query_part = f"?{query_string}" if query_string else ""
                return f"hysteria2://{urllib.parse.quote(str(password), safe='')}@{self._uri_host(server)}:{port}{query_part}#{remarks_encoded}"

            elif protocol == 'hysteria':
                server, port = proxy.get('server'), proxy.get('port')
                if not server:
                    return None
                params = {}
                auth = proxy.get('auth-str') or proxy.get('auth')
                if auth:
                    params['auth'] = auth
                params['protocol'] = proxy.get('protocol') or 'udp'
                for source, target in (
                    ('sni', 'sni'), ('alpn', 'alpn'), ('obfs', 'obfs'),
                    ('ports', 'mport'), ('up', 'upmbps'), ('down', 'downmbps'),
                    ('recv-window-conn', 'recv-window-conn'), ('recv-window', 'recv-window'),
                    ('ca', 'ca'), ('ca-str', 'ca-str'), ('fingerprint', 'fingerprint')
                ):
                    value = proxy.get(source)
                    if value not in (None, ''):
                        params[target] = ','.join(map(str, value)) if isinstance(value, (list, tuple)) else value
                if proxy.get('insecure') or proxy.get('skip-cert-verify'):
                    params['insecure'] = 1
                if proxy.get('fast-open'):
                    params['fast-open'] = 1
                if proxy.get('disable-mtu-discovery'):
                    params['disable-mtu-discovery'] = 1
                query_string = urllib.parse.urlencode(params)
                query_part = f"?{query_string}" if query_string else ""
                port_part = f":{port}" if port else ""
                return f"hysteria://{self._uri_host(server)}{port_part}/{query_part}#{remarks_encoded}"

            elif protocol == 'anytls':
                server, port, password = proxy.get('server'), proxy.get('port'), proxy.get('password')
                if not all([server, port, password]):
                    return None
                params = {}
                for key in ('sni', 'alpn', 'fingerprint', 'client-fingerprint',
                            'idle-session-check-interval', 'idle-session-timeout', 'min-idle-session'):
                    value = proxy.get(key)
                    if value not in (None, ''):
                        params[key] = ','.join(map(str, value)) if isinstance(value, (list, tuple)) else value
                if proxy.get('insecure') or proxy.get('skip-cert-verify'):
                    params['insecure'] = 1
                if 'udp' in proxy:
                    params['udp'] = str(self._as_bool(proxy.get('udp'))).lower()
                query_string = urllib.parse.urlencode(params)
                query_part = f"?{query_string}" if query_string else ""
                return f"anytls://{urllib.parse.quote(str(password), safe='')}@{self._uri_host(server)}:{port}/{query_part}#{remarks_encoded}"

            elif protocol == 'tuic':
                server, port = proxy.get('server'), proxy.get('port')
                uuid, password = proxy.get('uuid'), proxy.get('password')
                if not all([server, port, uuid, password]):
                    return None
                params = {}
                for key in ('sni', 'alpn', 'token', 'ip', 'heartbeat-interval',
                            'disable-sni', 'reduce-rtt', 'request-timeout',
                            'udp-relay-mode', 'congestion-controller',
                            'max-udp-relay-packet-size', 'max-open-streams'):
                    value = proxy.get(key)
                    if value not in (None, ''):
                        if isinstance(value, bool):
                            value = str(value).lower()
                        params[key] = ','.join(map(str, value)) if isinstance(value, (list, tuple)) else value
                if proxy.get('skip-cert-verify') or proxy.get('allow-insecure'):
                    params['skip-cert-verify'] = 1
                if proxy.get('fast-open'):
                    params['fast-open'] = 1
                auth = urllib.parse.quote(str(uuid), safe='') + ':' + urllib.parse.quote(str(password), safe='')
                query_string = urllib.parse.urlencode(params)
                query_part = f"?{query_string}" if query_string else ""
                return f"tuic://{auth}@{self._uri_host(server)}:{port}/{query_part}#{remarks_encoded}"

            elif protocol in ('http', 'socks5', 'socks'):
                server, port = proxy.get('server'), proxy.get('port')
                if not all([server, port]):
                    return None
                # Clash Verge Rev 的 URI 解析器不支持这些字段，遇到时不静默丢失。
                if proxy.get('headers') or proxy.get('alpn'):
                    return None
                sni = proxy.get('sni') or proxy.get('servername')
                if sni and str(sni).lower() != str(server).lower():
                    return None
                params = {}
                if proxy.get('tls'):
                    params['tls'] = 'true'
                if proxy.get('skip-cert-verify') or proxy.get('insecure'):
                    params['skip-cert-verify'] = 'true'
                for key in ('fingerprint', 'ip-version'):
                    if proxy.get(key) not in (None, ''):
                        params[key] = proxy[key]
                if protocol in ('socks5', 'socks') and 'udp' in proxy:
                    params['udp'] = str(self._as_bool(proxy.get('udp'))).lower()
                username, password = proxy.get('username'), proxy.get('password')
                if password is not None and username is None:
                    return None
                if username is not None and ':' in str(username):
                    return None
                auth = ''
                if username is not None:
                    auth = urllib.parse.quote(str(username), safe='')
                    if password is not None:
                        auth += ':' + urllib.parse.quote(str(password), safe='')
                    auth += '@'
                scheme = 'socks5' if protocol in ('socks5', 'socks') else 'http'
                query_string = urllib.parse.urlencode(params)
                query_part = f"?{query_string}" if query_string else ""
                return f"{scheme}://{auth}{self._uri_host(server)}:{port}/{query_part}#{remarks_encoded}"

            elif protocol == 'naive':
                server, port = proxy.get('server'), proxy.get('port')
                username, password = proxy.get('username'), proxy.get('password')
                if not all([server, port, username, password]):
                    return None
                params = {}
                sni = proxy.get('servername') or proxy.get('sni')
                if sni:
                    params['sni'] = sni
                if proxy.get('insecure') or proxy.get('skip-cert-verify'):
                    params['insecure'] = '1'
                query = urllib.parse.urlencode(params)
                return f"naive+https://{urllib.parse.quote(str(username), safe='')}:{urllib.parse.quote(str(password), safe='')}@{self._uri_host(server)}:{port}{('?' + query) if query else ''}#{remarks_encoded}"

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
            return re.search(str(pattern), name) is not None        except re.error as exc:
            print(f"  -> Invalid Provider filter ignored: {exc}")
            return None

    def sub_merge(self):
        url_list = self.url_list
        list_dir, merge_dir = self.list_dir, self.merge_dir

        # 仅清理本程序专用的临时目录；不再删除目录中的未知文件。
        os.makedirs(list_dir, exist_ok=True)
        os.makedirs(merge_dir, exist_ok=True)

        all_nodes_raw = []
        VALID_PROTOCOLS = ('vless://', 'vmess://', 'trojan://', 'ss://', 'ssr://', 'hy2://', 'hysteria2://', 'hysteria://', 'hy://', 'tuic://', 'anytls://', 'wireguard://', 'wg://', 'http://', 'https://', 'socks5://', 'socks://', 'naive+https://', 'naive+http://', 'mieru://', 'ssh://')
        headers = {'User-Agent': 'v2rayN/6.0'}
        session = requests.Session()
        unsupported_types = {}
        conversion_failures = 0
        conversion_failure_reasons = {}
        conversion_failures_by_protocol = {}

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
                        exclude_filter = provider_meta.get('exclude_filter')
                        include_filter = provider_meta.get('filter')
                        exclude_types = provider_meta.get('exclude_type') or []
                        additional_prefix = str(provider_meta.get('additional_prefix') or '')
                        additional_suffix = str(provider_meta.get('additional_suffix') or '')
                        proxy_name_rules = provider_meta.get('proxy_name') or {}

                        for proxy_dict in data['proxies']:
                            if not isinstance(proxy_dict, dict):
                                continue

                            proxy_data = dict(proxy_dict)
                            proxy_name = str(proxy_data.get('name') or '')

                            proxy_type = str(proxy_data.get('type') or '').lower()
                            if exclude_types:
                                if isinstance(exclude_types, (list, tuple, set)):
                                    if proxy_type in {str(t).lower() for t in exclude_types}:
                                        continue
                                elif self._provider_name_matches(exclude_types, proxy_type):
                                    continue
                            if include_filter and self._provider_name_matches(include_filter, proxy_name) is False:
                                continue
                            if exclude_filter and self._provider_name_matches(exclude_filter, proxy_name) is True:
                                continue
                            if additional_prefix or additional_suffix:
                                proxy_data['name'] = additional_prefix + proxy_name + additional_suffix
                            if isinstance(proxy_name_rules, list):
                                for rule in proxy_name_rules:
                                    if not isinstance(rule, dict) or 'pattern' not in rule:
                                        continue
                                    try:
                                        replacement = re.sub(
                                            r'\$(\d+)',
                                            lambda match: r'\g<' + match.group(1) + '>',
                                            str(rule.get('target', ''))
                                        )
                                        proxy_data['name'] = re.sub(
                                            str(rule.get('pattern', '')),
                                            replacement,
                                            str(proxy_data.get('name') or '')
                                        )
                                    except re.error as regex_error:
                                        print(f"  -> Invalid Provider proxy-name rule ignored: {regex_error}")
                            elif isinstance(proxy_name_rules, dict):
                                # 兼容旧缓存中以 pattern: target 表示的映射。
                                for pattern, replacement in proxy_name_rules.items():
                                    try:
                                        proxy_data['name'] = re.sub(str(pattern), str(replacement), str(proxy_data.get('name') or ''))
                                    except re.error as regex_error:
                                        print(f"  -> Invalid Provider proxy-name rule ignored: {regex_error}")
                            share_link = self.clash_to_share_link(proxy_data)
                            if share_link:
                                expected_scheme = {'hy2': 'hysteria2', 'hysteria2': 'hysteria2', 'wg': 'wireguard', 'wireguard': 'wireguard', 'socks': 'socks5', 'naive': 'naive+https'}.get(proxy_type, proxy_type)
                                if share_link.split('://', 1)[0].lower() != expected_scheme:
                                    conversion_failures += 1
                                    unsupported_types[proxy_type] = unsupported_types.get(proxy_type, 0) + 1
                                    self._record_conversion_failure(proxy_type, 'output_protocol_mismatch', conversion_failures_by_protocol, conversion_failure_reasons)
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
                except yaml.YAMLError as yaml_error:
                    if plain_text.lstrip().startswith(('proxies:', '---', 'proxy-providers:')):
                        print(f"  -> YAML parse failed: {yaml_error}")

                if not yaml_parsed:
                    found_nodes = [
                        line.strip()
                        for line in plain_text.splitlines()
                        if line.strip().lower().startswith(VALID_PROTOCOLS)
                    ]

                if found_nodes:
                    all_nodes_raw.extend(found_nodes)
                    print(f'  -> Success! Extracted {len(found_nodes)} valid node links.')
                else:
                    print("  -> 🔴🔴🔴🔴 Warning: No valid node links found.")
            except Exception as e:
                print(f"  -> 🔴🔴🔴🔴 Failed! Reason: {e}")
            finally:
                print()

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