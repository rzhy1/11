#!/usr/bin/env python3

import json, os, base64, time, requests, re
from subconverter import convert, base64_decode
import sys
from urllib.parse import unquote

# 导入 V2Ray 链接解析库
try:
    import v2ray_util.v2ray_util as v2ray_util
except ImportError:
    print("FATAL ERROR: v2ray_util library is required but not found.")
    print("Please add 'v2ray_util' to your requirements.txt and ensure it is installed.")
    sys.exit(1)

def is_base64(s):
    s = s.strip()
    if len(s) % 4 != 0: return False
    if not re.match(r'^[A-Za-z0-9+/]*=?=?$', s): return False
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

        # 我们现在自己处理所有逻辑，只从外部获取最基本的规则
        self.include_remarks = format_config.get('include_remarks', '').strip()
        self.exclude_remarks = format_config.get('exclude_remarks', '').strip()
        self.rename_rules = format_config.get('rename', '').strip()

        self.url_list = self.read_list()
        self.sub_merge()
        if self.readme_file:
            self.readme_update()

    def read_list(self):
        with open(self.list_file, 'r', encoding='utf-8') as f:
            raw_list = json.load(f)
        return [item for item in raw_list if item.get('enabled')]

    def parse_and_clean_nodes(self, node_links_set):
        """
        使用 v2ray_util 解析所有节点，进行去重、过滤和重命名。
        返回一个最终的、干净的节点链接列表。
        """
        all_nodes = []
        seen_proxies = set()

        # 准备过滤和重命名规则
        include_filters = [f.strip() for f in self.include_remarks.split('|') if f.strip()]
        exclude_filters = [f.strip() for f in self.exclude_remarks.split('|') if f.strip()]
        
        rename_map = {}
        if self.rename_rules:
            for rule in self.rename_rules.split(';'):
                if '@' in rule:
                    old, new = rule.split('@')
                    rename_map[old.strip()] = new.strip()

        for link in node_links_set:
            try:
                node_dict = None
                node_type = ''

                # 解析不同类型的链接
                if link.startswith('vless://'):
                    node_dict = v2ray_util.parse_vless(link)
                    node_type = 'vless'
                elif link.startswith('vmess://'):
                    # v2ray_util 的 vmess 解析返回的是 base64 编码的 json
                    vmess_json = base64.b64decode(link[8:]).decode('utf-8')
                    node_dict = json.loads(vmess_json)
                    node_type = 'vmess'
                elif link.startswith('trojan://'):
                    node_dict = v2ray_util.parse_trojan(link)
                    node_type = 'trojan'
                elif link.startswith('ss://'):
                    node_dict = v2ray_util.parse_ss(link)
                    node_type = 'ss'
                
                if not node_dict:
                    continue

                # 1. 精确去重
                proxy_id_parts = [
                    node_type,
                    str(node_dict.get('add', '')),
                    str(node_dict.get('port', '')),
                    str(node_dict.get('id', '')) # for vmess/vless/trojan
                ]
                proxy_id = '-'.join(proxy_id_parts)
                if proxy_id in seen_proxies:
                    continue
                seen_proxies.add(proxy_id)

                # 2. 过滤
                node_name = unquote(node_dict.get('ps', '') or node_dict.get('remarks', ''))
                
                # 应用 exclude 规则
                if self.exclude_remarks and any(f in node_name for f in exclude_filters):
                    continue
                
                # 应用 include 规则
                if self.include_remarks and not any(f in node_name for f in include_filters):
                    continue

                # 3. 重命名
                for old, new in rename_map.items():
                    node_name = node_name.replace(old, new)
                
                if 'ps' in node_dict: node_dict['ps'] = node_name
                if 'remarks' in node_dict: node_dict['remarks'] = node_name

                # 4. 重新构建链接
                final_link = ''
                if node_type == 'vless':
                    final_link = v2ray_util.build_vless(node_dict)
                elif node_type == 'vmess':
                    vmess_json_str = json.dumps(node_dict, separators=(',', ':'))
                    final_link = 'vmess://' + base64.b64encode(vmess_json_str.encode('utf-8')).decode('utf-8')
                elif node_type == 'trojan':
                    final_link = v2ray_util.build_trojan(node_dict)
                elif node_type == 'ss':
                    final_link = v2ray_util.build_ss(node_dict)
                
                if final_link:
                    all_nodes.append(final_link)

            except Exception as e:
                # 忽略解析或处理失败的链接
                # print(f"  -> Warning: Failed to process link '{link[:30]}...': {e}")
                pass
        
        return all_nodes

    def sub_merge(self):
        url_list = self.url_list
        list_dir = self.list_dir
        merge_dir = self.merge_dir

        if os.path.exists(list_dir):
            for dirpath, dirnames, filenames in os.walk(list_dir):
                for filename in filenames:
                    os.remove(os.path.join(dirpath, filename))
        else:
            os.makedirs(list_dir)

        content_set = set()
        VALID_PROTOCOLS = ('vless://', 'vmess://', 'trojan://', 'ss://', 'ssr://')

        for item in url_list:
            item_url = item.get('url')
            item_id = item.get('id')
            item_remarks = item.get('remarks')
            
            if not item_url:
                print(f"Skipping [ID: {item_id:0>2d}] {item_remarks} because URL is empty.")
                continue

            print(f"Processing [ID: {item_id}] {item_remarks}...")
            
            try:
                response = requests.get(item_url, timeout=15)
                response.raise_for_status()
                raw_content = response.text.strip()
                if not raw_content: raise ValueError("Downloaded content is empty.")

                plain_text_nodes = ''
                if is_base64(raw_content):
                    plain_text_nodes = base64.b64decode(raw_content).decode('utf-8', errors='ignore')
                else:
                    plain_text_nodes = raw_content
                
                found_nodes = [line.strip() for line in plain_text_nodes.splitlines() if line.strip().startswith(VALID_PROTOCOLS)]
                
                if found_nodes:
                    content_set.update(found_nodes)
                    print(f'  -> Success! Extracted {len(found_nodes)} valid node links.')
                else:
                    print(f"  -> Warning: No valid node links found.")

            except Exception as e:
                print(f"  -> Failed! Reason: {e}")
            
            print()

        if not content_set:
            print('Merging failed: No nodes collected from any source.')
            return
        
        print(f'\nTotal unique node links collected: {len(content_set)}')
        
        print("Starting nodes processing (deduplication, filtering, renaming)...")
        final_node_links = self.parse_and_clean_nodes(content_set)
        final_node_count = len(final_node_links)
        print(f"  -> Processing complete. Final node count: {final_node_count}")

        print('Starting final conversion to Base64...')

        final_input_content = '\n'.join(final_node_links)
        
        # 【终极核心】使用一个绝对空的配置，只做打包
        final_convert_config = {}

        final_b64_content = convert(final_input_content, 'base64', final_convert_config)

        if not final_b64_content:
            print("Error: Final conversion to Base64 failed.")
            return

        print(f"\nFinal conversion successful.")

        merge_path_final = f'{self.merge_dir}/sub_merge_base64.txt'
        with open(merge_path_final, 'wb') as file:
            file.write(final_b64_content.encode('utf-8'))
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
                            proxies = base64_decode(proxies_base64)
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
        'readme_file': './README.md'
    }
    
    # 模拟从 config.ini 读取的配置
    format_config = {
        'deduplicate': True, 
        'rename': '',
        'include_remarks': '',
        'exclude_remarks': '',
        'config': ''
    }
    
    merge(file_dir, format_config)
