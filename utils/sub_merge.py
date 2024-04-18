#!/usr/bin/env python3

import json, os, base64, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from subconverter import convert, base64_decode

merge_path = './sub/sub_merge_base64.txt'

class merge():
    def __init__(self,file_dir,format_config):
        self.list_dir = file_dir['list_dir']
        self.list_file = file_dir['list_file']
        self.merge_dir = file_dir['merge_dir']
        self.update_dir = file_dir['update_dir']
        self.readme_file = file_dir['readme_file']
        self.share_file = file_dir['share_file']

        self.format_config = {
            'deduplicate': bool(format_config['deduplicate']), 
            'rename': format_config['rename'],
            'include': format_config['include_remarks'], 
            'exclude': format_config['exclude_remarks'], 
            'config': format_config['config']
            }

        self.url_list = self.read_list()
        self.sub_merge()
        if self.readme_file != '':
            self.readme_update()

    def read_list(self): # 将 sub_list.json Url 内容读取为列表
        with open(self.list_file, 'r', encoding='utf-8') as f:
            raw_list = json.load(f)
        return [item for item in raw_list if item['enabled'] and not item['remarks'].startswith('trojan')]

    def sub_merge(self): # 将转换后的所有 Url 链接内容合并转换 YAML or Base64, ，并输出文件，输入订阅列表。
        url_list = self.url_list
        list_dir = self.list_dir
        merge_dir = self.merge_dir

        for dirpath, dirnames, filenames in os.walk(list_dir):
            for filename in filenames:
                os.remove(os.path.join(dirpath, filename))

        content_set = set()
        for url in url_list:
            content = convert(url['url'], 'url', {'keep_encode': True, 'raw_format': True, 'escape_special_chars': False})
            print(f"Content: {content}")  # 打印 convert 函数的返回值
            if content:
                content_set.update(content.splitlines())
                print(f'Writing content of {url["remarks"]} to {url["id"]:0>2d}.txt')
            else:
                content = 'No nodes were found in url.'
                print(f'Writing error of {url["remarks"]} to {url["id"]:0>2d}.txt')
            if self.list_dir:
                with open(f'{list_dir}{url["id"]:0>2d}.txt', 'w', encoding='utf-8') as file:
                    file.write(content)

        print('Merging nodes...')
        content = '\n'.join(content_set)
        content = convert(content, 'base64', self.format_config)
        merge_path = f'{merge_dir}/sub_merge_base64.txt'
        with open(merge_path, 'wb') as file:
            file.write(content.encode('utf-8'))
        print(f'Done! Output merged nodes to {merge_path}.')

        
    def readme_update(self): # 更新 README 节点信息
        print('Updating README...')
        with open(self.readme_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            f.close()

        # 所有节点打印
        for index in range(len(lines)):
            if lines[index] == '### 所有节点\n': # 目标行内容
                # 清除旧内容
                lines.pop(index+1) # 删除节点数量

                with open(f'{self.merge_dir}sub_merge_base64.txt', 'r', encoding='utf-8') as f:
                    proxies_base64 = f.read()
                    proxies = base64_decode(proxies_base64)
                    proxies = proxies.split('\n')
                    top_amount = len(proxies) - 1
                    f.close()
                lines.insert(index+1, f'合并节点总数: `{top_amount}`\n')
                break
        
        # 写入 README 内容
        with open(self.readme_file, 'w', encoding='utf-8') as f:
             data = ''.join(lines)
             print('完成!\n')
             f.write(data)
    # 读取并解码 Base64 编码的节点信息
    with open(merge_path, 'rb') as file:
        encoded_content = file.read().strip()
        decoded_content = base64.b64decode(encoded_content).decode('utf-8')

    # 进行 Trojan 节点过滤
    filtered_content = ''
    for line in decoded_content.splitlines():
        if 'trojan' not in line.lower():
            filtered_content += line + '\n'

    # 将过滤后的节点信息保存到文件
    filtered_path = './sub/sub_merge_filtered.txt'
    with open(filtered_path, 'w', encoding='utf-8') as file:
        file.write(filtered_content)

    print(f'Trojan nodes filtered. Filtered nodes saved to {filtered_path}.')
        
if __name__ == '__main__':
    merge()
