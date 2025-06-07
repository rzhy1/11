#!/usr/bin/env python3

import json, os, base64, time, requests, re
from subconverter import convert, base64_decode
import yaml # 确保已安装 pyyaml

# 辅助函数：判断字符串是否可能是 Base64
def is_base64(s):
    if len(s.strip()) % 4 != 0: return False
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
                
                found_nodes = []
                for line in plain_text_nodes.splitlines():
                    clean_line = line.strip()
                    if clean_line.startswith(VALID_PROTOCOLS):
                        found_nodes.append(clean_line)
                
                if found_nodes:
                    content_set.update(found_nodes)
                    print(f'  -> Success! Extracted {len(found_nodes)} valid node links.')
                else:
                    print(f"  -> Warning: No valid node links found.")

            except Exception as e:
                print(f"  -> Failed! Reason: {e}")
            
            print() # 分隔条目

        if not content_set:
            print('Merging failed: No nodes collected from any source.')
            return

        print(f'\nTotal unique node links collected: {len(content_set)}')
        print('Step 1: Converting all links to a unified Clash format...')

        # 步骤 1: 将所有纯链接转换为 Clash YAML，这会产生非致命错误，但我们只取其成功转换的部分
        all_links_content = '\n'.join(content_set)
        # 这里 subconverter 会打印非致命错误，这是正常的
        clash_yaml_from_links = convert(all_links_content, 'clash')
        
        if not clash_yaml_from_links:
            print("Fatal Error: subconverter failed to convert any links to Clash format.")
            return

        print("\nStep 2: Parsing the unified Clash format and cleaning up...")
        
        # 步骤 2: 使用 PyYAML 安全地解析，它会忽略掉 subconverter 报错的那些行
        try:
            clash_config = yaml.safe_load(clash_yaml_from_links)
            # 确保解析结果是字典且包含 proxies
            if isinstance(clash_config, dict) and 'proxies' in clash_config:
                clean_proxies = clash_config['proxies']
                final_node_count = len(clean_proxies)
                print(f"  -> Successfully parsed {final_node_count} nodes.")
            else:
                # 如果解析失败或格式不对，则认为没有节点
                clean_proxies = []
                final_node_count = 0
                print("  -> Warning: Could not find 'proxies' in the converted Clash config.")
        except yaml.YAMLError as e:
            print(f"Fatal Error: Failed to parse YAML from subconverter: {e}")
            return
        
        if final_node_count == 0:
            print("Merging aborted as no nodes were successfully parsed.")
            return

        # 步骤 3: 构建最终的、干净的 Clash 配置
        final_clash_config = {'proxies': clean_proxies}
        final_yaml_str = yaml.dump(final_clash_config, allow_unicode=True, sort_keys=False)
        
        print("\nStep 3: Converting the final clean Clash config to Base64...")
        
        # 步骤 4: 进行最终转换，这一步的输入是完美的，不会再有错误
        final_b64_content = convert(final_yaml_str, 'base64', self.format_config)
        
        # 验证最终数量
        final_b64_decoded = base64_decode(final_b64_content)
        final_written_count = len([line for line in final_b64_decoded.splitlines() if line.strip()])

        print(f"  -> Final conversion successful. Node count to be written: {final_written_count}")

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
