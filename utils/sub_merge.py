#!/usr/bin/env python3

import json, os, base64, time, requests, re
from subconverter import convert, base64_decode
import yaml  # 导入PyYAML库

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

        all_proxies = [] # 存储所有解析出的 Clash 格式的代理字典
        seen_proxies = set() # 用于精确去重

        for item in url_list:
            item_url = item.get('url')
            item_id = item.get('id')
            item_remarks = item.get('remarks')
            
            if not item_url:
                print(f"Skipping [ID: {item_id:0>2d}] {item_remarks} because URL is empty.\n")
                continue

            print(f"Processing [ID: {item_id}] {item_remarks}...")
            
            try:
                # 步骤 1: 永远由我们自己下载内容
                response = requests.get(item_url, timeout=15)
                response.raise_for_status()
                raw_content = response.text.strip()

                if not raw_content:
                    raise ValueError("Downloaded content is empty.")

                # 步骤 2: 将原始文本（无论格式）直接交给 subconverter 转换为 Clash YAML
                # subconverter 能自动识别输入是 base64 还是纯文本节点列表
                clash_yaml_content = convert(raw_content, 'clash')

                if not clash_yaml_content:
                    raise ValueError("subconverter returned empty content when converting to Clash format.")

                # 步骤 3: 解析 YAML 并提取 proxies
                clash_config = yaml.safe_load(clash_yaml_content)
                proxies = clash_config.get('proxies', [])
                
                if proxies:
                    print(f'  -> Success! Found and converted {len(proxies)} nodes.')
                    # 步骤 4: 精确去重并添加到总列表
                    new_nodes_count = 0
                    for proxy in proxies:
                        # 创建一个唯一的标识符用于去重，例如：类型-服务器-端口
                        proxy_id_parts = [
                            proxy.get('type'),
                            proxy.get('server'),
                            str(proxy.get('port')),
                            proxy.get('uuid', '') # vless/trojan/vmess
                        ]
                        proxy_id = '-'.join(filter(None, proxy_id_parts))

                        if proxy_id not in seen_proxies:
                            seen_proxies.add(proxy_id)
                            all_proxies.append(proxy)
                            new_nodes_count += 1
                    
                    if new_nodes_count > 0:
                        print(f'  -> Added {new_nodes_count} new unique nodes.')
                    
                    # 写入缓存文件（Clash YAML 格式，便于调试）
                    with open(f'{list_dir}{item_id:0>2d}.yml', 'w', encoding='utf-8') as f:
                        yaml.dump({'proxies': proxies}, f, allow_unicode=True, sort_keys=False)

                else:
                    print(f'  -> Warning: Source converted, but no proxies found inside.')
                
                print() # 每个条目处理完后加一个空行

            except Exception as e:
                print(f"  -> Failed! Reason: {e}\n")
                with open(f'{list_dir}{item_id:0>2d}.err', 'w', encoding='utf-8') as f:
                    f.write(f"Error processing subscription: {e}")

        if not all_proxies:
            print('Merging failed: No nodes collected from any source.')
            return

        print(f'\nTotal unique nodes collected: {len(all_proxies)}')
        print('Starting final merge and conversion to Base64...')

        # 步骤 5: 将去重后的代理列表重新构造成一个最终的 Clash 配置
        final_clash_config = {
            'proxies': all_proxies
        }
        
        # 将这个 Python 字典转换回 YAML 字符串
        final_yaml_str = yaml.dump(final_clash_config, allow_unicode=True, sort_keys=False)
        
        # 步骤 6: 最后，将这个最终的、干净的 Clash 配置交给 subconverter 转换成 Base64
        # 这里的 format_config 包含了 include/exclude/rename 等规则
        final_b64_content = convert(final_yaml_str, 'base64', self.format_config)

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
                            # 解码并计算节点数
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
    # 这里需要提供实际的 file_dir 和 format_config 参数
    file_dir = {
        'list_dir': './sub/list/',
        'list_file': './sub/sub_list.json',
        'merge_dir': './sub/',
        'readme_file': './README.md'
    }
    
    format_config = {
        'deduplicate': True, # 注意：去重已在脚本内实现，此项作用不大
        'rename': '',
        'include_remarks': '',
        'exclude_remarks': '',
        'config': ''
    }
    
    merge(file_dir, format_config)
