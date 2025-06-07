#!/usr/bin/env python3

import json, os, base64, time, requests, re
from subconverter import convert, base64_decode

# 辅助函数：判断字符串是否可能是 Base64
def is_base64(s):
    # Base64 字符串的长度必须是 4 的倍数，且不含非法字符
    if len(s.strip()) % 4 != 0:
        return False
    try:
        # validate=True 会在有非 base64 字符时抛出异常
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
        # 定义我们认可的节点协议
        VALID_PROTOCOLS = ('vless://', 'vmess://', 'trojan://', 'ss://', 'ssr://')

        for item in url_list:
            item_url = item.get('url')
            item_id = item.get('id')
            item_remarks = item.get('remarks')
            
            if not item_url:
                print(f"Skipping [ID: {item_id:0>2d}] {item_remarks} because URL is empty.\n")
                continue

            print(f"Processing [ID: {item_id}] {item_remarks}...")
            
            try:
                # 步骤 1: 下载内容
                response = requests.get(item_url, timeout=15)
                response.raise_for_status()
                raw_content = response.text.strip()

                if not raw_content:
                    raise ValueError("Downloaded content is empty.")

                # 步骤 2: 获取明文节点内容
                plain_text_nodes = ''
                if is_base64(raw_content):
                    print("  -> Detected as Base64. Decoding...")
                    plain_text_nodes = base64.b64decode(raw_content).decode('utf-8', errors='ignore')
                else:
                    print("  -> Detected as plain text.")
                    plain_text_nodes = raw_content
                
                # 步骤 3: 【核心过滤】只提取有效的节点分享链接
                found_nodes = []
                for line in plain_text_nodes.splitlines():
                    clean_line = line.strip()
                    if clean_line.startswith(VALID_PROTOCOLS):
                        found_nodes.append(clean_line)
                
                if found_nodes:
                    content_set.update(found_nodes)
                    print(f'  -> Success! Extracted {len(found_nodes)} valid nodes.\n')
                    # 写入缓存文件（只包含干净的节点）
                    with open(f'{list_dir}{item_id:0>2d}.txt', 'w', encoding='utf-8') as f:
                        f.write('\n'.join(found_nodes))
                else:
                    raise ValueError("No valid node links found in the content.")

            except Exception as e:
                print(f"  -> Failed! Reason: {e}\n")
                with open(f'{list_dir}{item_id:0>2d}.err', 'w', encoding='utf-8') as f:
                    f.write(f"Error processing subscription: {e}")

        if not content_set:
            print('Merging failed: No nodes collected from any source.')
            return

        print(f'\nTotal unique nodes collected: {len(content_set)}')
        print('Starting final merge and conversion to Base64...')

        # 步骤 4: 最终合并
        # 此时的 content_set 只包含纯粹的、干净的节点分享链接
        final_input_content = '\n'.join(content_set)
        final_b64_content = convert(final_input_content, 'base64', self.format_config)

        merge_path_final = f'{self.merge_dir}/sub_merge_base64.txt'
        with open(merge_path_final, 'wb') as file:
            file.write(final_b64_content.encode('utf-8'))
        print(f'Done! Output merged nodes to {merge_path_final}.')

    def readme_update(self):
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
