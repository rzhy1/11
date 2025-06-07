#!/usr/bin/env python3

import json, os, base64, time, requests, re
# 引入 yaml 库
import yaml
# 引入 urllib.parse 用于构建 URL
import urllib.parse

# 保持你原来的导入方式，因为你不希望用 subconverter 的 convert
# from subconverter import base64_decode

# 我们自己实现一个可靠的 base64_decode
def base64_decode(s):
    try:
        s = s.strip()
        missing_padding = len(s) % 4
        if missing_padding: s += '=' * (4 - missing_padding)
        return base64.b64decode(s).decode('utf-8', 'ignore')
    except Exception:
        return ""

def base64_encode(s):
    return base64.b64encode(s.encode('utf-8')).decode('ascii')


def is_base64(s):
    s = s.strip()
    # 改进正则以匹配可能的 Base64 字符串
    if not re.match(r'^[A-Za-z0-9+/]*=?=?$', s):
        return False
    if len(s) % 4 != 0:
        # 有些 base64 没有补全=，我们尝试补全后再判断
        s += '=' * (4 - (len(s) % 4))
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
            raw_list = json.load(f)
        return [item for item in raw_list if item.get('enabled')]

    # 【新功能】将 Clash 的 YAML 节点字典转换为分享链接
    def clash_to_share_link(self, proxy):
        try:
            protocol = proxy.get('type')
            if not protocol: return None

            # 统一 remarks
            remarks = proxy.get('name', '')
            remarks_encoded = urllib.parse.quote(remarks)

            if protocol == 'vmess':
                vmess_config = {
                    "v": "2",
                    "ps": remarks,
                    "add": proxy.get('server', ''),
                    "port": proxy.get('port', ''),
                    "id": proxy.get('uuid', ''),
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
                    ws_opts = proxy.get('ws-opts', {})
                    vmess_config['host'] = ws_opts.get('headers', {}).get('Host', '')
                    vmess_config['path'] = ws_opts.get('path', '/')
                if proxy.get('tls'):
                    vmess_config['tls'] = 'tls'
                    vmess_config['sni'] = proxy.get('sni', vmess_config['host'])
                
                json_str = json.dumps(vmess_config, separators=(',', ':'))
                return f"vmess://{base64_encode(json_str)}"

            elif protocol == 'vless':
                server = proxy.get('server')
                port = proxy.get('port')
                uuid = proxy.get('uuid')
                if not all([server, port, uuid]): return None
                
                params = {
                    'type': proxy.get('network', 'tcp'),
                    'security': 'tls' if proxy.get('tls') else 'none'
                }
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
                server = proxy.get('server')
                port = proxy.get('port')
                password = proxy.get('password')
                if not all([server, port, password]): return None
                
                params = {'sni': proxy.get('sni', server)}
                query_string = urllib.parse.urlencode(params)
                return f"trojan://{password}@{server}:{port}?{query_string}#{remarks_encoded}"

            elif protocol == 'ss':
                server = proxy.get('server')
                port = proxy.get('port')
                password = proxy.get('password')
                cipher = proxy.get('cipher')
                if not all([server, port, password, cipher]): return None
                
                creds = f"{cipher}:{password}"
                return f"ss://{base64_encode(creds)}@{server}:{port}#{remarks_encoded}"

            return None # 不支持的协议
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
        VALID_PROTOCOLS = ('vless://', 'vmess://', 'trojan://', 'ss://', 'ssr://')

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
                # 【核心修改】智能格式判断与处理
                if is_base64(raw_content):
                    print("  -> Detected Base64 format, decoding...")
                    plain_text = base64_decode(raw_content)
                    found_nodes = [line.strip() for line in plain_text.splitlines() if line.strip().lower().startswith(VALID_PROTOCOLS)]
                
                elif 'proxies:' in raw_content or 'proxy-groups:' in raw_content:
                    print("  -> Detected YAML format, parsing...")
                    # 使用 PyYAML 解析
                    try:
                        data = yaml.safe_load(raw_content)
                        proxies_in_yaml = data.get('proxies', [])
                        
                        if proxies_in_yaml and isinstance(proxies_in_yaml, list):
                            # 将 YAML 节点转换为分享链接
                            for proxy_dict in proxies_in_yaml:
                                share_link = self.clash_to_share_link(proxy_dict)
                                if share_link:
                                    found_nodes.append(share_link)
                    except yaml.YAMLError as e:
                        print(f"  -> ⭐⭐ YAML parsing error: {e}")
                
                else:
                    print("  -> Detected Plain Text node list format.")
                    plain_text = raw_content
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
        # ... (readme_update 方法保持不变) ...
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
    # ... (__main__ 方法保持不变) ...
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
