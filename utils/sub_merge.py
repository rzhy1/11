#!/usr/bin/env python3

import json, os, base64, time, requests, re
# 我们不再需要 subconverter 的 convert 函数
from subconverter import base64_decode

def is_base64(s):
    s = s.strip()
    # Base64 字符串的长度必须是 4 的倍数
    if len(s) % 4 != 0:
        return False
    # 检查是否只包含 Base64 字符
    if not re.match(r'^[A-Za-z0-9+/]*=?=?$', s):
        return False
    try:
        # 尝试解码，validate=True 会在有非 base64 字符时抛出异常
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

        # format_config 在这个版本中不再起主要作用，但保留以兼容接口
        self.format_config = format_config

        self.url_list = self.read_list()
        self.sub_merge()
        if self.readme_file:
            self.readme_update()

    def read_list(self):
        with open(self.list_file, 'r', encoding='utf-8') as f:
            raw_list = json.load(f)
        return [item for item in raw_list if item.get('enabled')]

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
        
        final_node_count = len(content_set)
        print(f'\nTotal unique node links collected: {final_node_count}')
        
        # 【终极核心】我们自己拼接和编码
        print('Packaging all collected nodes into a Base64 subscription...')

        # 将所有干净的节点链接用换行符拼接起来
        final_plain_text = '\n'.join(sorted(list(content_set)))
        
        # 自己动手进行 Base64 编码
        final_b64_content = base64.b64encode(final_plain_text.encode('utf-8')).decode('utf-8')

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
                            # 这里的 base64_decode 来自 subconverter，也可以用标准库的
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
