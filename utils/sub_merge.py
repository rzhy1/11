#!/usr/bin/env python3

import json, os, base64, time, requests
from subconverter import convert, base64_decode
import sys
from contextlib import contextmanager

@contextmanager
def suppress_stderr():
    """一个上下文管理器，可以临时屏蔽 stderr 输出。"""
    original_stderr = sys.stderr
    devnull_path = '/dev/null' if sys.platform != 'win32' else 'NUL'
    with open(devnull_path, 'w') as devnull:
        try:
            sys.stderr = devnull
            yield
        finally:
            sys.stderr = original_stderr

class merge():
    def __init__(self,file_dir,format_config):
        self.list_dir = file_dir['list_dir']
        self.list_file = file_dir['list_file']
        self.merge_dir = file_dir['merge_dir']
        self.readme_file = file_dir.get('readme_file')

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

        all_nodes_content = set()

        for item in url_list:
            item_url = item.get('url')
            item_id = item.get('id')
            item_remarks = item.get('remarks')
            
            if not item_url:
                print(f"Skipping [ID: {item_id:0>2d}] {item_remarks} because URL is empty.")
                continue

            print(f"Processing [ID: {item_id}] {item_remarks}...")
            
            try:
                # 【核心逻辑】对每个 URL 单独调用 subconverter，直接转为 Base64
                # 我们不再自己下载，让 subconverter 用它最擅长的方式处理单个源
                # 'url' 类型输入能最好地处理各种情况（包括需要 User-Agent 的）
                # 使用一个最简单的配置，只要求它输出原始节点
                config = {'raw_format': True}
                
                with suppress_stderr(): # 屏蔽掉这个过程中的非致命错误
                    base64_content = convert(item_url, 'url', config)

                if base64_content:
                    # 解码得到明文节点
                    plain_text = base64_decode(base64_content)
                    nodes = [line.strip() for line in plain_text.splitlines() if line.strip()]
                    if nodes:
                        all_nodes_content.update(nodes)
                        print(f'  -> Success! Converted and got {len(nodes)} nodes.')
                    else:
                        print("  -> Warning: Converted but got no nodes.")
                else:
                    print("  -> Warning: Subconverter returned empty content for this source.")

            except Exception as e:
                print(f"  -> Failed! Reason: {e}")
            
            print()

        if not all_nodes_content:
            print('Merging failed: No nodes collected from any source.')
            return
        
        # 此时 all_nodes_content 已经包含了所有去重后的节点明文
        final_node_count = len(all_nodes_content)
        print(f'\nTotal unique nodes collected: {final_node_count}')
        print('Starting final packaging to Base64...')

        final_input_content = '\n'.join(all_nodes_content)
        
        # 【核心逻辑】最后一次打包，使用一个绝对空的配置
        # 因为去重已经在 Python 的 set 中完成
        final_convert_config = {}

        final_b64_content = convert(final_input_content, 'base64', final_convert_config)

        if not final_b64_content:
            print("Error: Final packaging to Base64 failed.")
            return

        final_b64_decoded = base64_decode(final_b64_content)
        final_written_count = len([line for line in final_b64_decoded.splitlines() if line.strip()])

        print(f"\nFinal packaging successful.")
        print(f"  -> Total unique nodes collected: {final_node_count}")
        print(f"  -> Final nodes written to file: {final_written_count}")

        merge_path_final = f'{self.merge_dir}/sub_merge_base64.txt'
        with open(merge_path_final, 'wb') as file:
            file.write(final_b64_content.encode('utf-8'))
        print(f'\nDone! Output merged nodes to {merge_path_final}.')


    def readme_update(self):
        # ... (readme_update 方法保持不变) ...
        print('Updating README...')
        merge_path_final = f'{self.merge_dir}/sub_merge_base64.txt'
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
        'update_dir': './sub/update/',
        'readme_file': './README.md',
        'share_file': './sub/share.txt'
    }
    
    format_config = {}
    
    merge(file_dir, format_config)
