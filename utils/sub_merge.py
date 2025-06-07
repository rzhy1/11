#!/usr/bin/env python3

import json, os, base64, time, requests, re
from subconverter import convert, base64_decode
import sys
from contextlib import contextmanager
from urllib.parse import unquote, quote

@contextmanager
def suppress_stderr():
    original_stderr = sys.stderr
    devnull_path = '/dev/null' if sys.platform != 'win32' else 'NUL'
    with open(devnull_path, 'w') as devnull:
        try:
            sys.stderr = devnull
            yield
        finally:
            sys.stderr = original_stderr

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

    def process_and_filter_nodes(self, node_links_set):
        """
        自己动手进行去重、过滤和重命名。
        """
        final_links = []
        seen_proxies = set()

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
                # 1. 精确去重
                # 尝试从链接中提取关键信息作为唯一ID
                protocol = link.split('://')[0]
                at_parts = link.split('@')
                if len(at_parts) < 2: continue # 格式不正确的链接
                
                server_part = at_parts[1].split('#')[0].split('?')[0]
                host, port = server_part.rsplit(':', 1) if ':' in server_part else (server_part, '')
                
                proxy_id = f"{protocol}-{host}-{port}"
                if proxy_id in seen_proxies:
                    continue
                seen_proxies.add(proxy_id)

                # 2. 过滤和重命名
                node_name = ''
                if '#' in link:
                    node_name = unquote(link.split('#', 1)[1])

                if self.exclude_remarks and any(f in node_name for f in exclude_filters):
                    continue
                if self.include_remarks and not any(f in node_name for f in include_filters):
                    continue

                for old, new in rename_map.items():
                    node_name = node_name.replace(old, new)

                # 重新构建链接
                base_link = link.split('#')[0]
                final_link = f"{base_link}#{quote(node_name)}"
                final_links.append(final_link)

            except Exception:
                # 忽略处理失败的链接
                continue
        
        return final_links


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

        # 自己动手进行过滤和重命名
        final_node_links = self.process_and_filter_nodes(content_set)
        final_node_count = len(final_node_links)
        print(f"Processing complete. Final node count after filtering/renaming: {final_node_count}")

        print('Starting final conversion to Base64...')

        final_input_content = '\n'.join(final_node_links)
        
        # 使用一个最简单的配置，只让 subconverter 做打包和它自己内置的最终去重
        final_convert_config = {
            'deduplicate': True,
        }

        final_b64_content = ''
        with suppress_stderr():
            final_b64_content = convert(final_input_content, 'base64', final_convert_config)

        if not final_b64_content:
            print("Error: Final conversion to Base64 failed.")
            return

        final_b64_decoded = base64_decode(final_b64_content)
        final_written_count = len([line for line in final_b64_decoded.splitlines() if line.strip()])

        print(f"\nFinal conversion successful.")
        print(f"  -> Nodes before final conversion: {final_node_count}")
        print(f"  -> Final nodes written to file: {final_written_count}")

        merge_path_final = f'{self.merge_dir}/sub_merge_base64.txt'
        with open(merge_path_final, 'wb') as file:
            file.write(final_b64_content.encode('utf-8'))
        print(f'\nDone! Output merged nodes to {merge_path_final}.')


    def readme_update(self):
        # ... (readme_update 方法保持不变) ...
        print('Updating README...')
        merge_file_path = f'{self.merge_dir}/sub_merge_base64.txt'
        if not os.path.exists(merge_file_path):
            print(f"Warning: Merged file not found. Skipping README update.")
            return

        with open(self.readme_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        try:
            for index, line in enumerate(lines):
                if '### 所有节点' in line:
                    if index + 1 < len(lines) and '合并节点总数' in lines[index+1]:
                        lines.pop(index+1) 

                    with open(merge_file_path, 'r', encoding='utf-8') as f_merge:
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
    
    # 从 config.ini 读取的配置会在这里传入
    format_config = {
        'deduplicate': True, 
        'rename': '',
        'include_remarks': '',
        'exclude_remarks': '',
        'config': ''
    }
    
    merge(file_dir, format_config)
