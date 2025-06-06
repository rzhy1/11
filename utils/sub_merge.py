#!/usr/bin/env python3

import json, os, base64, time, requests, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from subconverter import convert, base64_decode

# 不再需要静音工具，所以相关的 import 和函数都已移除

class merge():
    def __init__(self,file_dir,format_config):
        self.list_dir = file_dir['list_dir']
        self.list_file = file_dir['list_file']
        self.merge_dir = file_dir['merge_dir']
        self.update_dir = file_dir['update_dir']
        self.readme_file = file_dir['readme_file']
        self.share_file = file_dir['share_file']

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

    def read_list(self): # 将 sub_list.json Url 内容读取为列表
        with open(self.list_file, 'r', encoding='utf-8') as f:
            raw_list = json.load(f)
        return [item for item in raw_list if item['enabled']]
    
    def cleanup_yaml_content(self, content):
        """使用正则表达式清洗可能导致 YAML 解析错误的行。"""
        pattern = re.compile(r"(server\s*:\s*)([^,'\"\s{}[\]]+:[^,'\"\s{}[\]]+)")
        def add_quotes(match):
            return f"{match.group(1)}'{match.group(2)}'"
        cleaned_content = pattern.sub(add_quotes, content)
        return cleaned_content

    def sub_merge(self): # 将转换后的所有 Url 链接内容合并转换 YAML or Base64
        url_list = self.url_list
        list_dir = self.list_dir
        merge_dir = self.merge_dir

        # 【已修复】正确清理旧的单个订阅缓存文件
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
            item_type = item.get('type', 'subscription')
            
            # 如果 URL 为空，打印信息并跳过
            if not item_url:
                print(f"Skipping [ID: {item_id:0>2d}] {item_remarks} because URL is empty.\n")
                continue

            # 打印处理信息
            print(f'Processing [ID: {item_id}] {item_remarks} with type [{item_type}]...')
            content = ''
            
            try:
                # 【关键逻辑】根据 type 执行不同策略
                if item_type == 'subscription':
                    # 直接调用 convert，让它打印自己的日志
                    content = convert(item_url, 'url', {'keep_encode': True, 'raw_format': True, 'escape_special_chars': False})
                
                elif item_type == 'raw_text_url':
                    # 对于明文节点，我们自己下载，不会有 subconverter 日志
                    response = requests.get(item_url, timeout=15)
                    response.raise_for_status()
                    content = response.text
                
                else:
                    content = f"Error: Unknown subscription type '{item_type}'"
            
            except requests.exceptions.RequestException as e:
                content = f"Error downloading URL: {e}"
            except Exception as e:
                content = f"Error processing subscription: {e}"
            
            # 在拿到 content 后，进行后续处理和打印总结信息
            if content and not content.startswith('Error:'):
                cleaned_content = self.cleanup_yaml_content(content)
                nodes = [line for line in cleaned_content.splitlines() if line.strip()]
                
                if nodes:
                    content_set.update(nodes)
                    print(f'Writing content of {item_remarks} to {item_id:0>2d}.txt ({len(nodes)} nodes found)\n')
                    file_content = '\n'.join(nodes)
                else:
                    print(f'Writing error of {item_remarks} to {item_id:0>2d}.txt (Source is empty)\n')
                    file_content = "No nodes were found in the content."
            else:
                print(f"Writing error of {item_remarks} to {item_id:0>2d}.txt ({content or 'Failed to process'})\n")
                file_content = content or 'Failed to process'

            if self.list_dir:
                with open(f'{list_dir}{item_id:0>2d}.txt', 'w', encoding='utf-8') as file:
                    file.write(file_content)

        if not content_set:
            print('Merging failed: No nodes collected from any source.')
            return

        print(f'\nMerging {len(content_set)} unique nodes...')
        content = '\n'.join(content_set)
        
        # 最终合并时，不静音，让 subconverter 打印可能的信息
        final_content = convert(content, 'base64', self.format_config)

        merge_path_final = f'{merge_dir}/sub_merge_base64.txt'
        with open(merge_path_final, 'wb') as file:
            file.write(final_content.encode('utf-8'))
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
        'update_dir': './sub/update/',
        'readme_file': './README.md',
        'share_file': './sub/share.txt'
    }
    
    format_config = {
        'deduplicate': True,
        'rename': '',
        'include_remarks': '',
        'exclude_remarks': '',
        'config': ''
    }
    
    merge(file_dir, format_config)
