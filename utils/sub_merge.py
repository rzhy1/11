#!/usr/bin/env python3

import json, os, base64, time, requests, re
from subconverter import convert, base64_decode

# 辅助函数：判断字符串是否可能是 Base64
def is_base64(s):
    try:
        # 如果字符串包含非 base64 字符，会抛出异常
        if len(s.strip()) % 4 != 0:
            return False
        base64.b64decode(s, validate=True)
        return True
    except Exception:
        return False

class merge():
    def __init__(self,file_dir,format_config):
        self.list_dir = file_dir['list_dir']
        self.list_file = file_dir['list_file']
        self.merge_dir = file_dir['merge_dir']
        self.readme_file = file_dir.get('readme_file') # 使用 .get 更安全

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
    
    def cleanup_node_list(self, nodes):
        cleaned_nodes = []
        pattern = re.compile(r"(server\s*:\s*)([^,'\"\s{}[\]]+:[^,'\"\s{}[\]]+)")
        def add_quotes(match):
            return f"{match.group(1)}'{match.group(2)}'"
        
        for node in nodes:
            cleaned_node = pattern.sub(add_quotes, node)
            cleaned_nodes.append(cleaned_node)
        return cleaned_nodes

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
        for item in url_list:
            item_url = item.get('url')
            item_id = item.get('id')
            item_remarks = item.get('remarks')
            item_format = item.get('format', 'base64') # 默认为 base64

            if not item_url:
                print(f"Skipping [ID: {item_id:0>2d}] {item_remarks} because URL is empty.\n")
                continue

            print(f'Processing [ID: {item_id}] {item_remarks} (format: {item_format})...')
            
            try:
                # 步骤 1: 永远由我们自己下载内容
                response = requests.get(item_url, timeout=15)
                response.raise_for_status()
                raw_content = response.text.strip()

                plain_text_nodes = ''
                
                # 步骤 2: 根据格式预处理内容
                if item_format == 'base64':
                    if is_base64(raw_content):
                        plain_text_nodes = base64_decode(raw_content)
                    else:
                        raise ValueError("Content format is 'base64', but decoding failed.")
                else: # 'text' format
                    plain_text_nodes = raw_content

                # 步骤 3: 清洗和添加
                if plain_text_nodes:
                    nodes = [line for line in plain_text_nodes.splitlines() if line.strip()]
                    cleaned_nodes = self.cleanup_node_list(nodes)
                    content_set.update(cleaned_nodes)
                    
                    print(f'Success! Found and added {len(cleaned_nodes)} nodes.\n')
                    # 写入缓存文件
                    with open(f'{list_dir}{item_id:0>2d}.txt', 'w', encoding='utf-8') as f:
                        f.write('\n'.join(cleaned_nodes))
                else:
                    raise ValueError("No valid nodes found after processing.")

            except Exception as e:
                print(f"Failed! Reason: {e}\n")
                with open(f'{list_dir}{item_id:0>2d}.txt', 'w', encoding='utf-8') as f:
                    f.write(f"Error processing subscription: {e}")

        if not content_set:
            print('Merging failed: No nodes collected from any source.')
            return

        print(f'\nMerging {len(content_set)} unique nodes...')
        
        final_input_content = '\n'.join(content_set)
        
        # 步骤 4: 最终合并 - 此时所有数据都是干净的
        final_b64_content = convert(final_input_content, 'base64', self.format_config)

        merge_path_final = f'{merge_dir}/sub_merge_base64.txt'
        with open(merge_path_final, 'wb') as file:
            file.write(final_b64_content.encode('utf-8'))
        print(f'Done! Output merged nodes to {merge_path_final}.')

    def readme_update(self): # 更新 README 节点信息
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
