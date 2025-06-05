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

    def read_list(self):
        with open(self.list_file, 'r', encoding='utf-8') as f:
            raw_list = json.load(f)
        
        supported_protocols = ['vmess', 'vless', 'trojan', 'ss', 'ssr']
        return [item for item in raw_list 
                if item['enabled'] 
                and any(p in item['url'].lower() for p in supported_protocols)]

    def sub_merge(self):
        url_list = self.url_list
        list_dir = self.list_dir
        merge_dir = self.merge_dir

        # 清空目录
        for f in os.listdir(list_dir):
            os.remove(os.path.join(list_dir, f))

        content_set = set()
        for url in url_list:
            max_retries = 3
            content = None
            for attempt in range(max_retries):
                try:
                    content = convert(url['url'], 'url', {
                        'keep_encode': True,
                        'raw_format': True,
                        'escape_special_chars': False,
                        'strict_mode': False,
                        'enable_advanced_conversion': True
                    })
                    if content:
                        break
                except Exception as e:
                    print(f'转换失败({attempt+1}/{max_retries}): {url["remarks"]}, 错误: {str(e)}')
                    time.sleep(2)

            if content:
                content_set.update(content.splitlines())
                print(f'成功获取: {url["remarks"]}')
            else:
                print(f'无法获取: {url["remarks"]}')
                
            # 保存原始内容
            with open(f'{list_dir}{url["id"]:0>2d}.txt', 'w', encoding='utf-8') as f:
                f.write(content if content else 'No nodes were found')

        # 合并处理
        print('合并节点中...')
        content = '\n'.join(content_set)
        content = convert(content, 'base64', self.format_config)
        
        with open(f'{merge_dir}/sub_merge_base64.txt', 'wb') as f:
            f.write(content.encode('utf-8'))
        print(f'合并完成: {merge_dir}/sub_merge_base64.txt')

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

if __name__ == '__main__':
    # 示例配置
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
