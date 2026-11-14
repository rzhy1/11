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
        return base64.b64decode(s).decode('utf-8', 'ignore')
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
        base64.b64decode(s_std, validate=True)
        return True
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
        self.sub_merge()
        if self.readme_file:
            self.readme_update()

    def read_list(self):
        with open(self.list_file, 'r', encoding='utf-8') as f:
            return [item for item in json.load(f) if item.get('enabled')]

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

    def deduplicate_nodes(self, nodes):
        """基于核心指纹的智能去重"""
        print(f"\n--- Step 2: Performing advanced deduplication on {len(nodes)} nodes ---")
        unique_nodes_dict = {}
        invalid_count = 0

        for node_link in nodes:
            parsed = self.parse_share_link(node_link)
            if not parsed:
                invalid_count += 1
                continue

            fingerprint = f"{parsed['protocol']}-{parsed['server']}-{parsed['port']}-{parsed['id']}"
            if fingerprint not in unique_nodes_dict:
                unique_nodes_dict[fingerprint] = node_link

        final_nodes = list(unique_nodes_dict.values())
        removed_count = len(nodes) - len(final_nodes) - invalid_count
        print(
            f"Deduplication complete. Removed {removed_count} duplicate nodes, "
            f"skipped {invalid_count} invalid/unparseable nodes."
        )
        return final_nodes

    def clash_to_share_link(self, proxy):
        """将 Clash 节点字典转换为标准分享链接"""
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
                query_string = urllib.parse.urlencode(params)
                return f"vless://{uuid}@{server}:{port}?{query_string}#{remarks_encoded}"

            elif protocol == 'trojan':
                server, port, password = proxy.get('server'), proxy.get('port'), proxy.get('password')
                if not all([server, port, password]):
                    return None
                params = {'sni': proxy.get('sni') or proxy.get('servername') or server}
                if proxy.get('skip-cert-verify'):
                    params['allowInsecure'] = 1
                if proxy.get('network') == 'ws':
                    params['type'] = 'ws'
                    ws_opts = proxy.get('ws-opts') or {}
                    headers = ws_opts.get('headers') or {}
                    if headers.get('Host'):
                        params['host'] = headers.get('Host')
                    params['path'] = ws_opts.get('path', '/')
                query_string = urllib.parse.urlencode(params)
                return f"trojan://{urllib.parse.quote(str(password))}@{server}:{port}?{query_string}#{remarks_encoded}"

            elif protocol == 'ss':
                server, port = proxy.get('server'), proxy.get('port')
                password, cipher = proxy.get('password'), proxy.get('cipher')
                if not all([server, port, password, cipher]):
                    return None
                creds = f"{cipher}:{password}"
                return f"ss://{base64_encode(creds)}@{server}:{port}#{remarks_encoded}"

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
                return f"hysteria2://{urllib.parse.quote(str(password))}@{server}:{port}{query_part}#{remarks_encoded}"

            return None
        except Exception:
            return None

    def sub_merge(self):
        url_list = self.url_list
        list_dir, merge_dir = self.list_dir, self.merge_dir

        os.makedirs(list_dir, exist_ok=True)
        for f in os.listdir(list_dir):
            file_path = os.path.join(list_dir, f)
            if os.path.isfile(file_path):
                os.remove(file_path)
        os.makedirs(merge_dir, exist_ok=True)

        all_nodes_raw = []
        VALID_PROTOCOLS = ('vless://', 'vmess://', 'trojan://', 'ss://', 'ssr://', 'hy2://', 'hysteria2://')
        headers = {'User-Agent': 'v2rayN/6.0'}

        for item in url_list:
            item_url, item_id, item_remarks = item.get('url'), item.get('id'), item.get('remarks')
            if not item_url:
                continue
            print(f"Processing [ID: {item_id}] {item_remarks} from {item_url}")
            try:
                response = requests.get(item_url, headers=headers, timeout=15)
                response.raise_for_status()
                raw_content = response.content.decode('utf-8', errors='ignore').strip()
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
                if 'proxies:' in plain_text:
                    try:
                        data = yaml.safe_load(plain_text)
                        if isinstance(data, dict) and isinstance(data.get('proxies'), list):
                            print("  -> Content parsed as YAML, converting proxies...")
                            yaml_parsed = True
                            for proxy_dict in data['proxies']:
                                share_link = self.clash_to_share_link(proxy_dict)
                                if share_link:
                                    found_nodes.append(share_link)
                    except yaml.YAMLError:
                        pass

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
            print('🔴🔴🔴🔴 Merging failed: No nodes collected.')
            return

        unique_nodes = self.deduplicate_nodes(all_nodes_raw)
        final_node_count = len(unique_nodes)
        print(f'\nTotal unique node links after deduplication: {final_node_count}')

        print('Packaging all collected nodes into a Base64 subscription...')
        final_plain_text = '\n'.join(sorted(unique_nodes))
        final_b64_content = base64_encode(final_plain_text)
        print("  -> Packaging successful.")

        merge_path_final = os.path.join(self.merge_dir, 'sub_merge_base64.txt')
        with open(merge_path_final, 'w', encoding='utf-8') as file:
            file.write(final_b64_content)
        print(f'\nDone! Output merged nodes to {merge_path_final}.')

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
