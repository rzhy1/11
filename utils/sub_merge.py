#!/usr/bin/env python3

import json, os, base64, time, requests, re
import yaml
import urllib.parse

def base64_decode(s):
    try:
        s = s.strip()
        missing_padding = len(s) % 4
        if missing_padding: s += '=' * (4 - missing_padding)
        return base64.b64decode(s).decode('utf-8', 'ignore')
    except: return ""

def base64_encode(s):
    return base64.b64encode(s.encode('utf-8')).decode('ascii')

def is_base64(s):
    s = s.strip()
    if not re.match(r'^[A-Za-z0-9+/]*=?=?$', s): return False
    if len(s) % 4 != 0: s += '=' * (4 - (len(s) % 4))
    try:
        base64.b64decode(s, validate=True)
        return True
    except Exception:
        return False

class merge():
    def __init__(self,file_dir,format_config):
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
        """将任何分享链接解析为包含核心指纹的字典"""
        try:
            protocol, rest = link.split("://", 1)
            # 移除 #remarks 部分
            main_part = rest.split('#')[0]
            
            fingerprint_parts = {'protocol': protocol}

            if protocol == 'vmess':
                config = json.loads(base64_decode(main_part))
                fingerprint_parts['server'] = config.get('add', '')
                fingerprint_parts['port'] = config.get('port', '')
                fingerprint_parts['id'] = config.get('id', '')
            elif protocol in ['vless', 'trojan']:
                user_info, server_info = main_part.split('@', 1)
                server, port = server_info.split('?')[0].split(':')
                fingerprint_parts['id'] = user_info
                fingerprint_parts['server'] = server
                fingerprint_parts['port'] = port
            elif protocol == 'ss':
                # ss://BASE64(method:password)@server:port
                if '@' in main_part:
                    credentials_part, server_part = main_part.split('@', 1)
                    server, port = server_part.split(':')
                    fingerprint_parts['creds'] = credentials_part
                    fingerprint_parts['server'] = server
                    fingerprint_parts['port'] = port
                else: # ss://BASE64(method:password:server:port)
                    decoded = base64_decode(main_part)
                    parts = decoded.split(':')
                    fingerprint_parts['creds'] = base64_encode(f"{parts[0]}:{parts[1]}")
                    fingerprint_parts['server'] = parts[2]
                    fingerprint_parts['port'] = parts[3]
            elif protocol in ['hy2', 'hysteria2']:
                password, server_info = main_part.split('@', 1)
                server, port = server_info.split('?')[0].split(':')
                fingerprint_parts['id'] = password
                fingerprint_parts['server'] = server
                fingerprint_parts['port'] = port
            else:
                return None # 不支持的协议

            return fingerprint_parts
        except:
            return None

    def deduplicate_nodes(self, nodes):
        """【核心】基于指纹的智能去重"""
        print(f"\n--- Step 2: Performing advanced deduplication on {len(nodes)} nodes ---")
        unique_nodes_dict = {} # { 'fingerprint': 'node_link' }
        
        for node_link in nodes:
            parsed = self.parse_share_link(node_link)
            if not parsed: continue # 跳过解析失败的

            # 构建一个稳定、唯一的指纹
            fingerprint = f"{parsed.get('protocol')}-{parsed.get('server')}-{parsed.get('port')}-{parsed.get('id')}"

            # 如果指纹还没出现过，就添加这个节点
            if fingerprint not in unique_nodes_dict:
                unique_nodes_dict[fingerprint] = node_link

        final_nodes = list(unique_nodes_dict.values())
        removed_count = len(nodes) - len(final_nodes)
        print(f"Deduplication complete. Removed {removed_count} duplicate nodes.")
        return final_nodes

    def clash_to_share_link(self, proxy):
        # ... (这个函数保持不变)
        try:
            protocol = proxy.get('type')
            if not protocol: return None
            remarks = proxy.get('name', '')
            remarks_encoded = urllib.parse.quote(remarks)
            if protocol == 'vmess':
                vmess_config = {"v": "2", "ps": remarks, "add": proxy.get('server', ''), "port": proxy.get('port', ''), "id": proxy.get('uuid', ''), "aid": proxy.get('alterId', 0), "scy": proxy.get('cipher', 'auto'), "net": proxy.get('network', 'tcp'), "type": "none", "host": "", "path": "", "tls": "", "sni": ""}
                if vmess_config['net'] == 'ws':
                    ws_opts = proxy.get('ws-opts', {})
                    vmess_config['host'] = ws_opts.get('headers', {}).get('Host', '')
                    vmess_config['path'] = ws_opts.get('path', '/')
                if proxy.get('tls'):
                    vmess_config['tls'] = 'tls'
                    vmess_config['sni'] = proxy.get('sni', vmess_config['host'])
                return f"vmess://{base64_encode(json.dumps(vmess_config, separators=(',', ':')))}"
            elif protocol == 'vless':
                server, port, uuid = proxy.get('server'), proxy.get('port'), proxy.get('uuid')
                if not all([server, port, uuid]): return None
                params = {'type': proxy.get('network', 'tcp'), 'security': 'tls' if proxy.get('tls') else 'none'}
                if params['security'] == 'tls':
                    params['sni'] = proxy.get('sni', '')
                    if proxy.get('reality-opts'):
                        params['security'] = 'reality'
                        params['pbk'] = proxy['reality-opts'].get('public-key', '')
                        params['sid'] = proxy['reality-opts'].get('short-id', '')
                if params['type'] == 'ws':
                    ws_opts = proxy.get('ws-opts', {})
                    params['host'] = ws_opts.get('headers', {}).get('Host', '')
                    params['path'] = urllib.parse.quote(ws_opts.get('path', '/'))
                query_string = urllib.parse.urlencode(params)
                return f"vless://{uuid}@{server}:{port}?{query_string}#{remarks_encoded}"
            elif protocol == 'trojan':
                server, port, password = proxy.get('server'), proxy.get('port'), proxy.get('password')
                if not all([server, port, password]): return None
                params = {'sni': proxy.get('sni', server)}
                query_string = urllib.parse.urlencode(params)
                return f"trojan://{password}@{server}:{port}?{query_string}#{remarks_encoded}"
            elif protocol == 'ss':
                server, port, password, cipher = proxy.get('server'), proxy.get('port'), proxy.get('password'), proxy.get('cipher')
                if not all([server, port, password, cipher]): return None
                creds = f"{cipher}:{password}"
                return f"ss://{base64_encode(creds)}@{server}:{port}#{remarks_encoded}"
            elif protocol in ['hysteria2', 'hy2']:
                server, port, password = proxy.get('server'), proxy.get('port'), proxy.get('password') or proxy.get('auth-str')
                if not all([server, port, password]): return None
                params = {}
                if proxy.get('sni'): params['sni'] = proxy.get('sni')
                if proxy.get('insecure') or proxy.get('skip-cert-verify'): params['insecure'] = 1
                if proxy.get('obfs'): params['obfs'] = proxy.get('obfs')
                if proxy.get('obfs-password'): params['obfs-password'] = proxy.get('obfs-password')
                query_string = urllib.parse.urlencode(params)
                return f"hysteria2://{password}@{server}:{port}?{query_string}#{remarks_encoded}"
            return None
        except: return None


    def sub_merge(self):
        # ... (数据收集部分保持不变) ...
        url_list = self.url_list
        list_dir, merge_dir = self.list_dir, self.merge_dir
        if os.path.exists(list_dir):
            for f in os.listdir(list_dir): os.remove(os.path.join(list_dir, f))
        else:
            os.makedirs(list_dir)
        all_nodes_raw = [] # 不再使用 set，直接用 list 收集所有链接
        VALID_PROTOCOLS = ('vless://', 'vmess://', 'trojan://', 'ss://', 'ssr://', 'hy2://', 'hysteria2://')
        for item in url_list:
            item_url, item_id, item_remarks = item.get('url'), item.get('id'), item.get('remarks')
            if not item_url: continue
            print(f"Processing [ID: {item_id}] {item_remarks} from {item_url}")
            try:
                response = requests.get(item_url, timeout=15)
                response.raise_for_status()
                raw_content = response.text.strip()
                if not raw_content: raise ValueError("Downloaded content is empty.")
                found_nodes = []
                plain_text = ""
                if is_base64(raw_content):
                    print("  -> Detected Base64 format, decoding...")
                    plain_text = base64_decode(raw_content)
                else:
                    print("  -> Detected Plain Text / YAML format.")
                    plain_text = raw_content
                if 'proxies:' in plain_text:
                    print("  -> Content appears to be YAML, parsing...")
                    data = yaml.safe_load(plain_text)
                    proxies_in_yaml = data.get('proxies', [])
                    if proxies_in_yaml:
                        for proxy_dict in proxies_in_yaml:
                            share_link = self.clash_to_share_link(proxy_dict)
                            if share_link: found_nodes.append(share_link)
                else:
                    found_nodes = [line.strip() for line in plain_text.splitlines() if line.strip().lower().startswith(VALID_PROTOCOLS)]
                if found_nodes:
                    all_nodes_raw.extend(found_nodes)
                    print(f'  -> Success! Extracted {len(found_nodes)} valid node links.')
                else:
                    print(f"  -> ⭐⭐ Warning: No valid node links found.")
            except Exception as e:
                print(f"  -> ⭐⭐ Failed! Reason: {e}")
            finally:
                print()

        if not all_nodes_raw:
            print('⭐⭐ Merging failed: No nodes collected.')
            return
        
        # 【核心改变】在合并前，调用智能去重函数
        unique_nodes = self.deduplicate_nodes(all_nodes_raw)
        
        final_node_count = len(unique_nodes)
        print(f'\nTotal unique node links after deduplication: {final_node_count}')
        
        print('Packaging all collected nodes into a Base64 subscription...')
        final_plain_text = '\n'.join(sorted(unique_nodes))
        final_b64_content = base64_encode(final_plain_text)
        print(f"  -> Packaging successful.")
        merge_path_final = f'{self.merge_dir}/sub_merge_base64.txt'
        with open(merge_path_final, 'w', encoding='utf-8') as file:
            file.write(final_b64_content)
        print(f'\nDone! Output merged nodes to {merge_path_final}.')


    def readme_update(self):
        # ... (readme_update 保持不变) ...
        print('Updating README...')
        merge_path_final = f'{self.merge_dir}/sub_merge_base64.txt'
        if not os.path.exists(merge_path_final):
            print(f"Warning: Merged file not found. Skipping README update.")
            return
        with open(self.readme_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        try:
            for index, line in enumerate(lines):
                if '### 所有节点' in line:
                    if index + 1 < len(lines) and '合并节点总数' in lines[index+1]:
                        lines.pop(index+1) 
                    with open(merge_path_final, 'r', encoding='utf-8') as f_merge:
                        proxies_base64 = f_merge.read()
                        if proxies_base64:
                            proxies = base64.b64decode(proxies_base64.encode('utf-8')).decode('utf-8')
                            top_amount = len([p for p in proxies.split('\n') if p.strip()])
                        else:
                            top_amount = 0
                    lines.insert(index+1, f'合并节点总数: `{top_amount}`\n')
                    break
        except Exception as e:
            print(f"Error updating README: {e}")
            return
        with open(self.readme_file, 'w', encoding='utf-8') as f:
             data = ''.join(lines)
             print('完成!\n')
             f.write(data)

if __name__ == '__main__':
    # ... (__main__ 保持不变)
    file_dir = { 'list_dir': './sub/list/', 'list_file': './sub/sub_list.json', 'merge_dir': './sub/', 'update_dir': './sub/update/', 'readme_file': './README.md', 'share_file': './sub/share.txt'}
    format_config = {}
    merge(file_dir, format_config)
