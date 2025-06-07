# utils/sub_merge.py 最终高效版

import json, os, base64, time, requests, re, yaml
from subconverter import convert, base64_decode

class merge():
    def __init__(self, file_dir, format_config):
        self.list_dir = file_dir['list_dir']
        self.list_file = file_dir['list_file']
        self.merge_dir = file_dir['merge_dir']
        self.readme_file = file_dir.get('readme_file')
        self.format_config = format_config
        self.url_list = self.read_list()
        self.sub_merge()
        if self.readme_file:
            self.readme_update()

    def read_list(self):
        with open(self.list_file, 'r', encoding='utf-8') as f:
            return [item for item in json.load(f) if item.get('enabled')]

    def sub_merge(self):
        url_list = self.url_list
        list_dir, merge_dir = self.list_dir, self.merge_dir

        if os.path.exists(list_dir):
            for f in os.listdir(list_dir): os.remove(os.path.join(list_dir, f))
        else:
            os.makedirs(list_dir)

        all_proxies_list = [] # 用于收集所有 YAML 格式的节点

        for item in url_list:
            item_url, item_id, item_remarks = item.get('url'), item.get('id'), item.get('remarks')
            if not item_url: continue
            
            print(f"Processing [ID: {item_id:0>2d}] {item_remarks}")
            
            # 【核心改变】立即将每个订阅源转换为 Clash Provider 格式
            # 我们不关心过滤规则，只做格式统一
            clash_provider_str = convert(item_url, 'url', 'clash', {})
            
            if clash_provider_str:
                try:
                    # 解析 YAML，提取 'proxies' 列表
                    data = yaml.safe_load(clash_provider_str)
                    proxies = data.get('proxies')
                    if proxies and isinstance(proxies, list):
                        all_proxies_list.extend(proxies)
                        print(f"  -> Success! Converted and added {len(proxies)} nodes.")
                    else:
                        print("  -> Warning: Converted, but no 'proxies' list found in YAML.")
                except yaml.YAMLError as e:
                    print(f"  -> Failed to parse YAML: {e}")
            else:
                print(f"  -> Failed to convert this subscription.")
            print()

        if not all_proxies_list:
            print('Merging failed: No nodes collected from any source.')
            return

        print(f'\nTotal nodes collected (before final processing): {len(all_proxies_list)}')
        
        # 【去重】在合并的 YAML 层面进行高效去重
        unique_proxies_dict = {}
        for proxy in all_proxies_list:
            # 使用 server:port 作为节点的唯一标识
            fingerprint = f"{proxy.get('server', '')}:{proxy.get('port', '')}"
            if fingerprint not in unique_proxies_dict:
                unique_proxies_dict[fingerprint] = proxy
        
        final_proxies = list(unique_proxies_dict.values())
        removed_count = len(all_proxies_list) - len(final_proxies)
        print(f'Deduplication complete. Removed {removed_count} duplicate nodes.')
        print(f'Final unique node count: {len(final_proxies)}')

        # 将最终的、去重后的节点列表打包成一个大的 Clash Provider YAML
        final_clash_provider = {'proxies': final_proxies}
        final_clash_provider_str = yaml.dump(final_clash_provider, allow_unicode=True)
        
        # 将这个巨大的 YAML 内容编码成 Base64
        final_clash_provider_b64 = base64.b64encode(final_clash_provider_str.encode('utf-8')).decode('utf-8')

        print('\nHanding over final merged provider to subconverter for packaging...')
        
        # 【最终打包】最后一次调用 subconverter，应用所有规则
        # 这次输入类型是 'base64'
        final_b64_content = convert(final_clash_provider_b64, 'base64', 'base64', self.format_config)

        if not final_b64_content:
            print("Final packaging failed. Subconverter returned empty content.")
            return

        print("Final packaging successful.")
        merge_path_final = os.path.join(self.merge_dir, 'sub_merge_base64.txt')
        with open(merge_path_final, 'w', encoding='utf-8') as f:
            f.write(final_b64_content)
        print(f'\nDone! Output merged nodes to {merge_path_final}.')


    def readme_update(self):
        # ... (readme_update 保持不变)
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
    # ... (__main__ 保持不变)
    file_dir = {
        'list_dir': './sub/list/',
        'list_file': './sub/sub_list.json',
        'merge_dir': './sub/',
        'readme_file': './README.md',
    }
    format_config = {
        'deduplicate': False, # 我们自己去重，这里可以关掉
        'rename': '',
        'include_remarks': '',
        'exclude_remarks': '',
        'config': ''
    }
    merge(file_dir, format_config)
