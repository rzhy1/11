#!/usr/bin/env python3

import json, os, base64, time, requests, re
from urllib.parse import unquote

# 我们不再需要 subconverter 和任何外部解析库

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

    def deduplicate_nodes_by_regex(self, node_links_set):
        """
        使用正则表达式提取“地址:端口”作为核心指纹进行去重。
        这是在不引入任何新依赖的情况下的最佳实践。
        """
        unique_nodes = {} # {fingerprint: link}
        
        # 正则表达式，用于匹配 host:port 部分
        # 匹配 @ 和 #/? 之间的内容
        pattern = re.compile(r"@([^?#]+)")

        for link in node_links_set:
            try:
                fingerprint = ''
                protocol = link.split('://')[0].lower()
                
                if protocol == 'vmess':
                    # 对于 VMESS，我们只能去重完全一样的 Base64 部分
                    fingerprint = link.split('://')[1]
                else:
                    # 对于其他协议
                    match = pattern.search(link)
                    if match:
                        # server_part 可能是 user:pass@host:port 中的 host:port
                        # 或者 host:port
                        server_part = match.group(1).split('@')[-1].strip().lower()
                        fingerprint = f"{protocol}-{server_part}"
                    else:
                        # 如果正则匹配失败，使用链接主体作为后备方案
                        fingerprint = link.split('#')[0]

                if fingerprint not in unique_nodes:
                    unique_nodes[fingerprint] = link

            except Exception:
                continue
        
        return list(unique_nodes.values())

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
                try:
                    decoded_content = base64.b64decode(raw_content).decode('utf-8', errors='ignore')
                    plain_text_nodes = decoded_content
                except Exception:
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
        
        initial_node_count = len(content_set)
        print(f'\nTotal node links collected (before deduplication): {initial_node_count}')
        
        print("Performing deduplication using RegEx...")
        final_node_links = self.deduplicate_nodes_by_regex(content_set)
        final_node_count = len(final_node_links)
        removed_count = initial_node_count - final_node_count
        print(f"  -> Deduplication complete. Removed {removed_count} duplicate nodes.")
        print(f"  -> Final unique node count: {final_node_count}")

        print('\nPackaging all unique nodes into a Base64 subscription...')

        final_plain_text = '\n'.join(sorted(final_node_links))
        final_b64_content = base64.b64encode(final_plain_text.encode('utf-8')).decode('utf-8')

        print(f"  -> Packaging successful.")

        merge_path_final = f'{self.merge_dir}/sub_merge_base64.txt'
        with open(merge_path_final, 'w', encoding='utf-8') as file:
            file.write(final_b64_content)
        print(f'\nDone! Output merged nodes to {merge_path_final}.')


    def readme_update(self):
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
