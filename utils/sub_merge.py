#!/usr/bin/env python3

import json, os, base64, time, requests, re, subprocess
from concurrent.futures import ThreadPoolExecutor

def base64_decode(s):
    try:
        s = s.strip()
        missing_padding = len(s) % 4
        if missing_padding: s += '=' * (4 - missing_padding)
        return base64.b64decode(s).decode('utf-8', 'ignore')
    except: return ""

def base64_encode(s):
    return base64.b64encode(s.encode('utf-8')).decode('ascii')

def is_likely_base64(s):
    s = s.strip()
    return re.match(r'^[A-Za-z0-9+/=]+$', s) and len(s) % 4 == 0

class merge():
    def __init__(self, file_dir, format_config):
        self.subconverter_dir = os.path.join(os.path.dirname(__file__), 'subconverter')
        self.subconverter_exec = 'subconverter-linux-amd64'
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

    def fetch_and_process_url(self, item):
        item_url, item_id, item_remarks = item.get('url'), item.get('id'), item.get('remarks')
        if not item_url: return []
        try:
            response = requests.get(item_url, timeout=20)
            response.raise_for_status()
            raw_content = response.text.strip()
            if not raw_content: return []
            plain_text_nodes = base64_decode(raw_content) if is_likely_base64(raw_content) else raw_content
            return [line.strip() for line in plain_text_nodes.splitlines() if line.strip()]
        except Exception as e:
            print(f"  -> Failed to fetch [ID: {item_id:0>2d}] {item_remarks}. Reason: {e}")
            return []

    def deduplicate_nodes(self, nodes):
        print("\n--- Step 2: Deduplicating nodes ---")
        unique_proxies = {}
        for node in nodes:
            fingerprint = ""
            try:
                protocol = node.split('://')[0].lower()
                if protocol == 'vmess':
                    try:
                        decoded_part = base64.b64decode(node[8:]).decode('utf-8')
                        vmess_config = json.loads(decoded_part)
                        fingerprint = f"{vmess_config.get('add', '')}:{vmess_config.get('port', '')}"
                    except: fingerprint = node.split('#')[0]
                elif protocol in ['vless', 'trojan', 'ss']:
                    match = re.search(r'//(?:.*@)?([^?#:]+:\d+)', node)
                    if match: fingerprint = match.group(1)
                    else: fingerprint = node.split('#')[0].split('?')[0]
                else: fingerprint = node.split('#')[0]
                if fingerprint and fingerprint not in unique_proxies:
                    unique_proxies[fingerprint] = node
            except: continue
        final_nodes = list(unique_proxies.values())
        removed_count = len(nodes) - len(final_nodes)
        print(f"Deduplication complete. Removed {removed_count} duplicate nodes.")
        return final_nodes

    def run_subconverter_chunk(self, chunk):
        """处理一小块节点"""
        input_content = '\n'.join(chunk)
        original_cwd = os.getcwd()
        try:
            os.chdir(self.subconverter_dir)
            command = [f'./{self.subconverter_exec}', '--no-color', '--target', 'base64']
            
            # 将过滤和重命名规则应用到每一块
            if self.format_config.get('rename'): command.extend(['--rename', self.format_config['rename']])
            if self.format_config.get('include'): command.extend(['--include', self.format_config['include']])
            if self.format_config.get('exclude'): command.extend(['--exclude', self.format_config['exclude']])
            command.append('--no-deduplicate') # 我们已经去重

            process = subprocess.run(
                command, input=input_content.encode('utf-8'),
                capture_output=True, check=True, timeout=60 # 60秒处理一小块，绰绰有余
            )
            return process.stdout
        except Exception as e:
            print(f"  -> A chunk failed to process: {e}")
            return None
        finally:
            os.chdir(original_cwd)

    def sub_merge(self):
        print("--- Step 1: Concurrently fetching all subscriptions ---")
        all_nodes_raw = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_url = {executor.submit(self.fetch_and_process_url, item): item for item in self.url_list}
            for future in future_to_url:
                try:
                    nodes = future.result()
                    if nodes: all_nodes_raw.extend(nodes)
                except Exception as e: print(f"An error in a thread: {e}")
        
        print(f"\nTotal lines collected (before deduplication): {len(all_nodes_raw)}")
        if not all_nodes_raw: return

        unique_nodes = self.deduplicate_nodes(all_nodes_raw)
        print(f'Total unique nodes after deduplication: {len(unique_nodes)}')

        # 【核心改变】分块处理
        print("\n--- Step 3: Processing nodes in chunks to avoid timeout ---")
        chunk_size = 500 # 定义块的大小
        final_processed_nodes = []
        
        # 将 unique_nodes 列表切片
        for i in range(0, len(unique_nodes), chunk_size):
            chunk = unique_nodes[i:i + chunk_size]
            print(f"Processing chunk {i//chunk_size + 1} ({len(chunk)} nodes)...")
            
            # 调用 subconverter 处理这一小块
            result_b64_bytes = self.run_subconverter_chunk(chunk)
            
            if result_b64_bytes:
                # 解码返回的 Base64，得到处理过的明文节点
                processed_chunk_str = result_b64_bytes.decode('utf-8')
                processed_nodes_in_chunk = [line for line in base64_decode(processed_chunk_str).splitlines() if line.strip()]
                final_processed_nodes.extend(processed_nodes_in_chunk)
                print(f"  -> Chunk processed successfully. Got {len(processed_nodes_in_chunk)} nodes.")
        
        if not final_processed_nodes:
            print("Merging failed: No nodes survived the final conversion process.")
            return

        print(f"\n--- Step 4: Final packaging ---")
        print(f"Total nodes after all processing: {len(final_processed_nodes)}")

        # 手动打包最终结果
        final_plain_text = '\n'.join(sorted(final_processed_nodes))
        final_b64_content = base64_encode(final_plain_text)

        print("Packaging successful.")
        merge_path_final = os.path.join(self.merge_dir, 'sub_merge_base64.txt')
        with open(merge_path_final, 'w', encoding='utf-8') as f: # 最终是字符串，用 'w'
            f.write(final_b64_content)
        print(f'\nDone! Output merged nodes to {merge_path_final}.')

    def readme_update(self):
        # ... (readme_update 保持不变) ...
        print('Updating README...')
        merge_path_final = os.path.join(self.merge_dir, 'sub_merge_base64.txt')
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
    # ... (__main__ 保持不变) ...
    file_dir = {
        'list_dir': './sub/list/',
        'list_file': './sub/sub_list.json',
        'merge_dir': './sub/',
        'readme_file': './README.md',
    }
    format_config = {
        'deduplicate': False,
        'rename': '',
        'include_remarks': '',
        'exclude_remarks': '',
        'config': ''
    }
    merge(file_dir, format_config)
