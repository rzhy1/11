#!/usr/bin/env python3

import json, os, base64, time, requests, re
from subconverter import convert, base64_decode
import sys
from contextlib import contextmanager

@contextmanager
def suppress_stderr():
    """一个上下文管理器，可以临时屏蔽 stderr 输出。"""
    original_stderr = sys.stderr
    # 在 GitHub Actions 等环境中，使用 /dev/null
    devnull_path = '/dev/null' if sys.platform != 'win32' else 'NUL'
    with open(devnull_path, 'w') as devnull:
        try:
            sys.stderr = devnull
            yield
        finally:
            sys.stderr = original_stderr

# 辅助函数：判断字符串是否可能是 Base64
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

        self.format_config = {
            'deduplicate': bool(format_config.get('deduplicate', True)), 
            'rename': format_config.get('rename', ''),
            'include': format_config.get('include_remarks', ''), 
            'exclude': format_config.get('exclude_remarks', ''), 
            'config': format_config.get('config', '')
        }

        self.url_list = self.read_list()
        self.sub_merge()
        if self.readme_file:
            self.readme_update()

    def read_list(self):
        with open(self.list_file, 'r', encoding='utf-8') as f:
            raw_list = json.load(f)
        return [item for item in raw_list if item.get('enabled')]

    def fix_node_links(self, node_links):
        """
        接收一个节点链接的集合，修复其中已知的问题。
        """
        fixed_links = set()
        # 修复 vless server 地址中 ::ffff: 的问题
        vless_pattern = re.compile(r"(vless://[^@]+@)::ffff:([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)(:[0-9]+.*)")
        
        for link in node_links:
            match = vless_pattern.match(link)
            if match:
                # 重组链接: part1(vless://uuid@) + part2(ipv4) + part3(:port...)
                fixed_link = f"{match.group(1)}{match.group(2)}{match.group(3)}"
                fixed_links.add(fixed_link)
            else:
                fixed_links.add(link)
        return fixed_links

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
                
                found_nodes_count = 0
                for line in plain_text_nodes.splitlines():
                    clean_line = line.strip()
                    if clean_line.startswith(VALID_PROTOCOLS):
                        content_set.add(clean_line)
                        found_nodes_count += 1
                
                if found_nodes_count > 0:
                    print(f'  -> Success! Extracted {found_nodes_count} valid node links.')
                else:
                    print(f"  -> Warning: No valid node links found.")

            except Exception as e:
                print(f"  -> Failed! Reason: {e}")
            
            print()

        if not content_set:
            print('Merging failed: No nodes collected from any source.')
            return

        print(f'\nTotal unique node links collected: {len(content_set)}')
        
        # 【核心修复步骤】
        print("Fixing known issues in node links (e.g., VLESS IPv6 mapping)...")
        fixed_content_set = self.fix_node_links(content_set)
        print(f"  -> Link fixing complete. Nodes after fixing: {len(fixed_content_set)}")

        print('Starting final conversion to Base64...')

        final_input_content = '\n'.join(fixed_content_set)
        
        final_b64_content = ''
        # 在调用 convert 时，屏蔽其 stderr 输出，以隐藏任何非致命的解析错误
        with suppress_stderr():
            final_b64_content = convert(final_input_content, 'base64', self.format_config)

        if not final_b64_content:
            print("Error: Final conversion to Base64 failed, subconverter may have critical issues.")
            return

        final_b64_decoded = base64_decode(final_b64_content)
        final_written_count = len([line for line in final_b64_decoded.splitlines() if line.strip()])

        print(f"\nFinal conversion successful.")
        print(f"  -> Total unique links before final conversion: {len(fixed_content_set)}")
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
    
    format_config = {
        'deduplicate': True, 
        'rename': '',
        'include_remarks': '',
        'exclude_remarks': '',
        'config': ''
    }
    
    merge(file_dir, format_config)
