#!/usr/bin/env python3

import json, os, base64, time, requests, re, subprocess

# ... (base64_decode 和 is_likely_base64 函数保持不变) ...
def base64_decode(s):
    try:
        s = s.strip()
        missing_padding = len(s) % 4
        if missing_padding: s += '=' * (4 - missing_padding)
        return base64.b64decode(s).decode('utf-8', 'ignore')
    except Exception:
        return ""

def is_likely_base64(s):
    s = s.strip()
    return re.match(r'^[A-Za-z0-9+/=]+$', s) and len(s) % 4 == 0


class merge():
    def __init__(self, file_dir, format_config):
        self.list_dir = file_dir['list_dir']
        self.list_file = file_dir['list_file']
        self.merge_dir = file_dir['merge_dir']
        self.readme_file = file_dir.get('readme_file')
        self.format_config = format_config
        
        # 【核心修复】使用 __file__ 来构建绝对可靠的路径
        # os.path.dirname(__file__) -> 获取 sub_merge.py 所在的目录 (即 .../utils)
        # os.path.join(..., 'subconverter') -> 拼接出 subconverter 目录的路径
        self.subconverter_dir = os.path.join(os.path.dirname(__file__), 'subconverter')
        self.subconverter_exec = 'subconverter-linux-amd64'

        self.url_list = self.read_list()
        self.sub_merge()
        if self.readme_file:
            self.readme_update()

    # ... (read_list, deduplicate_nodes 函数保持不变) ...
    def read_list(self):
        with open(self.list_file, 'r', encoding='utf-8') as f:
            return [item for item in json.load(f) if item.get('enabled')]

    def deduplicate_nodes(self, nodes):
        print("\nPerforming advanced deduplication...")
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
                    except:
                         fingerprint = node.split('#')[0]
                elif protocol in ['vless', 'trojan', 'ss']:
                    match = re.search(r'//(?:.*@)?([^?#:]+:\d+)', node)
                    if match:
                        fingerprint = match.group(1)
                    else:
                         fingerprint = node.split('#')[0].split('?')[0]
                else:
                    fingerprint = node.split('#')[0]

                if fingerprint and fingerprint not in unique_proxies:
                    unique_proxies[fingerprint] = node
            except Exception as e:
                print(f"  -> Could not create fingerprint for node, skipping: {node[:30]}... ({e})")
                continue
        
        final_nodes = list(unique_proxies.values())
        removed_count = len(nodes) - len(final_nodes)
        print(f"  -> Deduplication complete. Removed {removed_count} duplicate nodes.")
        return final_nodes

    def sub_merge(self):
        # ... (数据收集部分保持不变) ...
        list_dir, merge_dir = self.list_dir, self.merge_dir
        if os.path.exists(list_dir):
            for f in os.listdir(list_dir): os.remove(os.path.join(list_dir, f))
        else:
            os.makedirs(list_dir)

        all_nodes = []
        for item in self.url_list:
            item_url, item_id, item_remarks = item.get('url'), item.get('id'), item.get('remarks')
            if not item_url: continue
            
            print(f"Processing [ID: {item_id:0>2d}] {item_remarks} from {item_url}")
            try:
                response = requests.get(item_url, timeout=20)
                response.raise_for_status()
                raw_content = response.text.strip()
                if not raw_content: raise ValueError("Downloaded content is empty.")
                plain_text_nodes = ""
                if is_likely_base64(raw_content):
                    print("  -> Detected Base64 format, decoding...")
                    plain_text_nodes = base64_decode(raw_content)
                else:
                    print("  -> Detected Plain Text or YAML format.")
                    plain_text_nodes = raw_content
                found_lines = [line.strip() for line in plain_text_nodes.splitlines() if line.strip()]
                if found_lines:
                    all_nodes.extend(found_lines)
                    print(f'  -> Success! Added {len(found_lines)} lines to merge pool.')
                else:
                    print("  -> ⭐⭐ Warning: No content lines found.")
            except Exception as e:
                print(f"  -> Failed! Reason: {e}")
            finally:
                print()
        
        if not all_nodes:
            print('Merging failed: No nodes collected.')
            return

        print(f'\nTotal lines collected (before deduplication): {len(all_nodes)}')
        unique_nodes = self.deduplicate_nodes(all_nodes)
        print(f'Total unique nodes after deduplication: {len(unique_nodes)}')
        print('\nHanding over unique nodes to subconverter for final packaging...')
        final_input_content = '\n'.join(sorted(unique_nodes))

        # 【逻辑保持不变】使用 try...finally 和 os.chdir 保证在正确的目录下执行
        original_cwd = os.getcwd() 
        try:
            os.chdir(self.subconverter_dir)
            print(f"  -> Changed directory to: {os.getcwd()}")
            
            if not os.path.isfile(f'./{self.subconverter_exec}'):
                raise FileNotFoundError(f"Executable '{self.subconverter_exec}' not found in CWD '{os.getcwd()}'")

            command = [
                f'./{self.subconverter_exec}',
                '--no-color',
                '--target', 'base64'
            ]
            if self.format_config.get('rename'): command.extend(['--rename', self.format_config['rename']])
            if self.format_config.get('include'): command.extend(['--include', self.format_config['include']])
            if self.format_config.get('exclude'): command.extend(['--exclude', self.format_config['exclude']])
            if self.format_config.get('deduplicate') is False: command.append('--no-deduplicate')

            print(f"  -> Executing command: {' '.join(command)}")
            
            process = subprocess.run(
                command,
                input=final_input_content.encode('utf-8'),
                capture_output=True,
                check=True,
                timeout=180
            )
            
            final_b64_content = process.stdout
            
            if not final_b64_content:
                print("  -> Conversion failed: Subconverter returned empty content.")
                if process.stderr: print("  -> Stderr:", process.stderr.decode('utf-8'))
                os.chdir(original_cwd)
                return

            print("  -> Conversion successful.")
            # 写入最终文件时，路径必须相对于原始 CWD
            # file_dir['merge_dir'] 是 './sub/'，是相对于项目根目录的
            # 我们需要确保它能被正确解析
            final_merge_dir = os.path.join(original_cwd, self.merge_dir)
            if not os.path.exists(final_merge_dir):
                os.makedirs(final_merge_dir)
            merge_path_final = os.path.join(final_merge_dir, 'sub_merge_base64.txt')
            
            with open(merge_path_final, 'wb') as f:
                f.write(final_b64_content)
            print(f'\nDone! Output merged nodes to {merge_path_final}.')

        except subprocess.TimeoutExpired:
            print("  -> FATAL ERROR: Subconverter timed out.")
        except subprocess.CalledProcessError as e:
            print("  -> FATAL ERROR: Subconverter exited with an error.")
            print(f"  -> Stderr: {e.stderr.decode('utf-8')}")
        except FileNotFoundError as e:
            print(f"  -> FATAL ERROR: {e}")
        except Exception as e:
            print(f"  -> FATAL ERROR: An unexpected error occurred: {e}")
        finally:
            os.chdir(original_cwd)
            print(f"  -> Returned to original directory: {os.getcwd()}")


    def readme_update(self):
        # ... (readme_update 保持不变) ...
        # 【小修复】确保 readme_update 也使用正确的相对路径
        original_cwd = os.getcwd()
        readme_path = os.path.join(original_cwd, self.readme_file)
        merge_path = os.path.join(original_cwd, self.merge_dir, 'sub_merge_base64.txt')
        
        print('Updating README...')
        if not os.path.exists(merge_path):
            print(f"Warning: Merged file not found. Skipping README update.")
            return
        
        with open(readme_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        try:
            # ...
            with open(merge_path, 'r', encoding='utf-8') as f_merge:
                # ...
                proxies_base64 = f_merge.read()
                if proxies_base64:
                    proxies = base64_decode(proxies_base64)
                    top_amount = len([p for p in proxies.split('\n') if p.strip()])
                else:
                    top_amount = 0
            # ...
            for index, line in enumerate(lines):
                if '### 所有节点' in line:
                    if index + 1 < len(lines) and '合并节点总数' in lines[index+1]:
                        lines.pop(index+1) 
                    lines.insert(index+1, f'合并节点总数: `{top_amount}`\n')
                    break
        except Exception as e:
            print(f"Error updating README: {e}")
            return
        
        with open(readme_path, 'w', encoding='utf-8') as f:
             data = ''.join(lines)
             print('完成!\n')
             f.write(data)

if __name__ == '__main__':
    # ... (__main__ 保持不变) ...
    # 【重要】确保传递给 merge 类的路径都是相对于项目根目录的
    # 这是正确的，因为 __main__ 是从根目录启动的
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
