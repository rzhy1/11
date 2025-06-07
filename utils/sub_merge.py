#!/usr/bin/env python3

import json, os, base64, time, requests, re, subprocess
from concurrent.futures import ThreadPoolExecutor

# 辅助函数
def base64_decode(s):
    try:
        s = s.strip()
        missing_padding = len(s) % 4
        if missing_padding: s += '=' * (4 - missing_padding)
        return base64.b64decode(s).decode('utf-8', 'ignore')
    except: return ""

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
        """【新】用于并发处理单个订阅源的函数"""
        item_url, item_id, item_remarks = item.get('url'), item.get('id'), item.get('remarks')
        if not item_url: return []
        
        print(f"  -> Fetching [ID: {item_id:0>2d}] {item_remarks}")
        try:
            response = requests.get(item_url, timeout=20)
            response.raise_for_status()
            raw_content = response.text.strip()
            if not raw_content: return []

            plain_text_nodes = ""
            if is_likely_base64(raw_content):
                plain_text_nodes = base64_decode(raw_content)
            else:
                plain_text_nodes = raw_content
            
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

    def sub_merge(self):
        print("--- Step 1: Concurrently fetching all subscriptions ---")
        all_nodes_raw = []
        # 使用线程池并发下载
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_url = {executor.submit(self.fetch_and_process_url, item): item for item in self.url_list}
            for future in future_to_url:
                try:
                    nodes = future.result()
                    if nodes:
                        all_nodes_raw.extend(nodes)
                except Exception as e:
                    print(f"An error occurred in a thread: {e}")
        
        print(f"\nTotal lines collected (before deduplication): {len(all_nodes_raw)}")
        if not all_nodes_raw:
            print('Merging failed: No nodes collected.')
            return

        unique_nodes = self.deduplicate_nodes(all_nodes_raw)
        print(f'Total unique nodes after deduplication: {len(unique_nodes)}')

        print("\n--- Step 3: Final packaging with subconverter ---")
        final_input_content = '\n'.join(sorted(unique_nodes))

        original_cwd = os.getcwd()
        try:
            os.chdir(self.subconverter_dir)
            
            command = [
                f'./{self.subconverter_exec}', '--no-color', '--target', 'base64'
            ]
            if self.format_config.get('rename'): command.extend(['--rename', self.format_config['rename']])
            if self.format_config.get('include'): command.extend(['--include', self.format_config['include']])
            if self.format_config.get('exclude'): command.extend(['--exclude', self.format_config['exclude']])
            if self.format_config.get('deduplicate') is False: command.append('--no-deduplicate')

            print(f"Executing subconverter with {len(unique_nodes)} nodes... (timeout: 180s)")
            
            process = subprocess.run(
                command, input=final_input_content.encode('utf-8'),
                capture_output=True, check=True, timeout=180
            )
            
            final_b64_content = process.stdout
            if not final_b64_content:
                print("Conversion failed: Subconverter returned empty content.")
                if process.stderr: print(f"Stderr: {process.stderr.decode('utf-8')}")
                return

            print("Conversion successful.")
            merge_path_final = os.path.join(original_cwd, self.merge_dir, 'sub_merge_base64.txt')
            with open(merge_path_final, 'wb') as f:
                f.write(final_b64_content)
            print(f'\nDone! Output merged nodes to {merge_path_final}.')

        except subprocess.TimeoutExpired:
            print("FATAL ERROR: Subconverter timed out even after deduplication.")
        except subprocess.CalledProcessError as e:
            print("FATAL ERROR: Subconverter exited with an error.")
            print(f"Stderr: {e.stderr.decode('utf-8')}")
        except FileNotFoundError:
            print(f"FATAL ERROR: Executable not found in '{os.getcwd()}'")
        except Exception as e:
            print(f"FATAL ERROR: An unexpected error occurred: {e}")
        finally:
            os.chdir(original_cwd)

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
