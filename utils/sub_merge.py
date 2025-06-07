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

    def deduplicate_nodes_by_fingerprint(self, node_links_set):
        """
        通过提取“协议-地址-端口”作为核心指纹进行精确去重。
        """
        unique_nodes = {} # {fingerprint: link}
        DEFAULT_PORTS = { 'vless': 443, 'trojan': 443, 'ss': 8443 }

        for link in node_links_set:
            try:
                fingerprint = ''
                protocol = link.split('://')[0].lower()
                host, port = '', ''

                if protocol == 'vmess':
                    try:
                        vmess_json_str = base64.b64decode(link[8:]).decode('utf-8', errors='ignore')
                        node_dict = json.loads(vmess_json_str)
                        host = str(node_dict.get('add', '')).strip().lower()
                        port = str(node_dict.get('port', ''))
                        if host and port:
                            fingerprint = f"{protocol}-{host}:{port}"
                    except Exception:
                        continue
                elif protocol in ['vless', 'trojan', 'ss']:
                    at_index = link.find('@')
                    if at_index == -1: continue
                    server_part = link[at_index + 1:].split('?')[0].split('#')[0]
                    if server_part.rfind(':') > server_part.rfind(']'):
                        host_part, port_part = server_part.rsplit(':', 1)
                        host = host_part.strip().lower()
                        port = port_part.strip()
                    else:
                        host = server_part.strip().lower()
                        port = str(DEFAULT_PORTS.get(protocol, ''))
                    if host and port:
                        fingerprint = f"{protocol}-{host}:{port}"
                else:
                    fingerprint = link.split('#')[0]
                
                if not fingerprint: continue

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
        
        print("Performing precise deduplication based on protocol, address, and port...")
        final_node_links = self.deduplicate_nodes_by_fingerprint(content_set)
        final_node_count = len(final_node_links)
        removed_count = initial_node_count - final_node_count
        print(f"  -> Deduplication complete. Removed {removed_count} duplicate nodes.")
        print(f"  -> Final unique node count: {final_node_count}")

        print('\nPackaging all unique nodes into a Base64 subscription...')

        # 按节点名排序，如果节点名相同则按整个链接排序
        final_node_links.sort(key=lambda x: (x.split('#')[1] if '#' in x else '', x))
        final_plain_text = '\n'.join(final_node_links)
        
        # 【核心调试步骤】生成明文调试文件
        debug_plain_text_path = os.path.join(self.merge_dir, 'debug_final_plain.txt')
        with open(debug_plain_text_path, 'w', encoding='utf-8') as f:
            f.write(final_plain_text)
        print(f"[DEBUG] Wrote {final_node_count} final unique nodes to: {debug_plain_text_path}")


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
