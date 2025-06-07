#!/usr/bin/env python3

import json, os, base64, time, requests, re

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
        【终极版】使用正则表达式提取核心配置作为指纹进行去重。
        不依赖任何外部解析库。
        """
        unique_nodes = {} # {fingerprint: link}
        
        for link in node_links_set:
            try:
                fingerprint = ''
                protocol = link.split('://')[0].lower()
                
                if protocol == 'vmess':
                    try:
                        # 对于 VMESS，解码 Base64 并提取核心信息
                        vmess_json_str = base64.b64decode(link[8:]).decode('utf-8', errors='ignore')
                        node_dict = json.loads(vmess_json_str)
                        # 指纹: 地址:端口:UUID
                        fingerprint = "vmess-{}:{}:{}".format(
                            node_dict.get('add', '').strip().lower(),
                            node_dict.get('port', ''),
                            node_dict.get('id', '')
                        )
                    except Exception:
                        # 如果解码失败，使用整个 Base64 部分作为指纹
                        fingerprint = link.split('#')[0]
                
                elif protocol in ['vless', 'trojan']:
                    # 对于 VLESS/Trojan，指纹是 UUID@地址:端口
                    match = re.search(r"//([^@]+@[\w\.\-:]+)", link)
                    if match:
                        fingerprint = f"{protocol}-{match.group(1).lower()}"
                    else:
                        fingerprint = link.split('?')[0].split('#')[0]

                elif protocol == 'ss':
                    # 对于 SS，指纹是 加密方法:密码@地址:端口
                    match = re.search(r"//(.+?@[\w\.\-:]+)", link)
                    if match:
                        fingerprint = f"{protocol}-{match.group(1).lower()}"
                    else:
                        fingerprint = link.split('?')[0].split('#')[0]
                
                else: # ssr 和其他未知协议
                    fingerprint = link.split('#')[0]

                # 如果没有有效的指纹，则跳过
                if not fingerprint:
                    continue

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

            print(f"Processing [ID: {item_id:0>2d}] {item_url}")
            
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
        
        print("Performing deduplication using improved RegEx...")
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
