#!/usr/bin/env python3

import json, os, base64, time, requests, re
from subconverter import convert, base64_decode
import sys
from contextlib import contextmanager
pip install v2ray_util
# 导入 V2Ray 链接解析库
try:
    import v2ray_util.v2ray_util as v2ray_util
except ImportError:
    print("Error: v2ray_util library not found. Please install it using 'pip install v2ray_util'")
    sys.exit(1)

# ... (suppress_stderr 和 is_base64 辅助函数保持不变) ...
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

        self.format_config = {
            'deduplicate': bool(format_config.get('deduplicate', True)), 
            'rename': format_config.get('rename', ''),
            'include': format_config.get('include_remarks', ''), 
            'exclude': format_config.get('exclude_remarks', ''), 
            'config': '' # 强制清空 config，确保完全控制
        }

        self.url_list = self.read_list()
        self.sub_merge()
        if self.readme_file:
            self.readme_update()

    def read_list(self):
        with open(self.list_file, 'r', encoding='utf-8') as f:
            raw_list = json.load(f)
        return [item for item in raw_list if item.get('enabled')]

    def fix_node_links(self, node_links_set):
        """
        使用 v2ray_util 库来解析、修复并重构节点链接。
        """
        fixed_links = set()
        for link in node_links_set:
            try:
                if link.startswith('vless://'):
                    # 解析 VLESS 链接
                    node = v2ray_util.parse_vless(link)
                    server = node.get('add', '')
                    # 如果 server 地址是 IPv6 映射地址，修复它
                    if server.startswith('::ffff:'):
                        node['add'] = server.replace('::ffff:', '')
                    # 重构链接
                    fixed_link = v2ray_util.build_vless(node)
                    fixed_links.add(fixed_link)
                else:
                    # 对于其他类型的链接，暂时不做处理，直接添加
                    fixed_links.add(link)
            except Exception:
                # 如果解析失败，说明链接格式有问题，直接添加原始链接
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
        
        # 【终极核心修复】
        print("Fixing VLESS links before final conversion...")
        fixed_content_set = self.fix_node_links(content_set)
        fixed_count = len(fixed_content_set)
        print(f"  -> Link fixing complete. Total nodes to be converted: {fixed_count}")

        print('Starting final conversion to Base64...')

        final_input_content = '\n'.join(fixed_content_set)
        
        final_b64_content = ''
        # 在调用 convert 时，屏蔽其 stderr 输出
        with suppress_stderr():
            final_b64_content = convert(final_input_content, 'base64', self.format_config)

        if not final_b64_content:
            print("Error: Final conversion to Base64 failed.")
            return

        final_b64_decoded = base64_decode(final_b64_content)
        final_written_count = len([line for line in final_b64_decoded.splitlines() if line.strip()])

        print(f"\nFinal conversion successful.")
        print(f"  -> Nodes before conversion: {fixed_count}")
        print(f"  -> Final nodes written to file: {final_written_count}")

        if fixed_count > final_written_count:
            diff = fixed_count - final_written_count
            print(f"  -> NOTE: {diff} nodes were removed by subconverter's deduplication/filtering.")

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
