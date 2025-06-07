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
    # 改进正则，更宽容
    if not re.match(r'^[A-Za-z0-9+/=\s]+$', s): return False
    s_no_ws = "".join(s.split())
    if len(s_no_ws) % 4 != 0: return False
    try:
        base64.b64decode(s_no_ws, validate=True)
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

    def clash_to_share_link(self, proxy):
        try:
            protocol = proxy.get('type')
            if not protocol: return None
            remarks = proxy.get('name', '')
            remarks_encoded = urllib.parse.quote(remarks)

            # (此处省略其他协议的转换逻辑，保持和你之前版本一致)
            if protocol == 'vmess':
                # ...
                vmess_config = {"v": "2", "ps": remarks, "add": proxy.get('server', ''), "port": proxy.get('port', ''), "id": proxy.get('uuid', ''), "aid": proxy.get('alterId', 0), "scy": proxy.get('cipher', 'auto'), "net": proxy.get('network', 'tcp'), "type": "none", "host": "", "path": "", "tls": "", "sni": ""}
                if vmess_config['net'] == 'ws':
                    ws_opts = proxy.get('ws-opts', {})
                    vmess_config['host'] = ws_opts.get('headers', {}).get('Host', '')
                    vmess_config['path'] = ws_opts.get('path', '/')
                if proxy.get('tls'):
                    vmess_config['tls'] = 'tls'
                    vmess_config['sni'] = proxy.get('sni', vmess_config['host'])
                return f"vmess://{base64_encode(json.dumps(vmess_config, separators=(',', ':')))}"
            elif protocol in ['hysteria2', 'hy2']:
                server, port, password = proxy.get('server'), proxy.get('port'), proxy.get('password') or proxy.get('auth-str')
                if not all([server, port, password]): return None
                params = {}
                if proxy.get('sni'): params['sni'] = proxy.get('sni')
                if proxy.get('insecure') or proxy.get('skip-cert-verify'): params['insecure'] = 1
                if proxy.get('obfs'): params['obfs'] = proxy.get('obfs')
                if proxy.get('obfs-password'): params['obfs-password'] = proxy.get('obfs-password')
                query_string = urllib.parse.urlencode(params)
                # 统一输出为 hysteria2://
                return f"hysteria2://{password}@{server}:{port}?{query_string}#{remarks_encoded}"
            # ... (添加其他协议如 vless, trojan, ss 的逻辑)

            return None
        except Exception as e:
            print(f"  -> Error building share link for node {proxy.get('name')}: {e}")
            return None

    def sub_merge(self):
        url_list = self.url_list
        list_dir, merge_dir = self.list_dir, self.merge_dir
        if os.path.exists(list_dir):
            for f in os.listdir(list_dir): os.remove(os.path.join(list_dir, f))
        else:
            os.makedirs(list_dir)

        content_set = set()
        # 【最终修复】同时接受 hysteria2:// 和 hy2://
        VALID_PROTOCOLS = ('vless://', 'vmess://', 'trojan://', 'ss://', 'ssr://', 'hy2://', 'hysteria2://')

        for item in url_list:
            item_url, item_id, item_remarks = item.get('url'), item.get('id'), item.get('remarks')
            if not item_url:
                print(f"Skipping [ID: {item_id:0>2d}] {item_remarks} because URL is empty.")
                continue

            print(f"Processing [ID: {item_id}] {item_remarks} from {item_url}")
            try:
                response = requests.get(item_url, timeout=15)
                response.raise_for_status()
                raw_content = response.text.strip()
                if not raw_content: raise ValueError("Downloaded content is empty.")
                found_nodes = []

                if is_base64(raw_content):
                    print("  -> Detected Base64 format, decoding...")
                    plain_text = base64_decode(raw_content)
                else:
                    print("  -> Detected Plain Text / YAML format.")
                    plain_text = raw_content
                
                # 【核心逻辑修复】统一处理解码后或原始的明文
                # 1. 优先检查是否是 YAML
                if 'proxies:' in plain_text:
                    print("  -> Content is YAML, parsing...")
                    try:
                        data = yaml.safe_load(plain_text)
                        proxies_in_yaml = data.get('proxies', [])
                        if proxies_in_yaml:
                            for proxy_dict in proxies_in_yaml:
                                share_link = self.clash_to_share_link(proxy_dict)
                                if share_link: found_nodes.append(share_link)
                    except yaml.YAMLError as e:
                        print(f"  -> ⭐⭐ YAML parsing error: {e}")
                
                # 2. 如果不是 YAML，则按行处理纯文本链接
                else:
                    found_nodes = [line.strip() for line in plain_text.splitlines() if line.strip().lower().startswith(VALID_PROTOCOLS)]
                
                if found_nodes:
                    content_set.update(found_nodes)
                    print(f'  -> Success! Extracted {len(found_nodes)} valid node links.')
                else:
                    print(f"  -> ⭐⭐ Warning: No valid node links found.")
            except Exception as e:
                print(f"  -> ⭐⭐ Failed! Reason: {e}")
            finally:
                print()

        if not content_set:
            print('⭐⭐ Merging failed: No nodes collected from any source.')
            return
        
        final_node_count = len(content_set)
        print(f'\nTotal unique node links collected: {final_node_count}')
        print('Packaging all collected nodes into a Base64 subscription...')
        final_plain_text = '\n'.join(sorted(list(content_set)))
        final_b64_content = base64_encode(final_plain_text)
        print(f"  -> Packaging successful. Final node count: {final_node_count}")
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
