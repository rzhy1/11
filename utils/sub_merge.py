#!/usr/bin/env python3

import json, os, base64, time, requests, re, subprocess

# 我们不再需要导入 subconverter 包，因为我们直接调用可执行文件
# from subconverter import convert, base64_decode

# 我们自己实现一个可靠的 base64_decode
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
    # Base64 字符串的长度必须是4的倍数 (在补全=号后)
    # 并且只包含特定字符集
    return re.match(r'^[A-Za-z0-9+/=]+$', s) and len(s) % 4 == 0

class merge():
    def __init__(self, file_dir, format_config):
        self.list_dir = file_dir['list_dir']
        self.list_file = file_dir['list_file']
        self.merge_dir = file_dir['merge_dir']
        self.readme_file = file_dir.get('readme_file')
        self.format_config = format_config
        self.subconverter_path = './utils/subconverter/subconverter-linux-amd64'

        self.url_list = self.read_list()
        self.sub_merge()
        if self.readme_file:
            self.readme_update()

    def read_list(self):
        with open(self.list_file, 'r', encoding='utf-8') as f:
            return [item for item in json.load(f) if item.get('enabled')]

    def deduplicate_nodes(self, nodes):
        """高效的节点去重函数，基于 server:port 或其他核心标识"""
        print("\nPerforming advanced deduplication...")
        unique_proxies = {} # 使用字典来去重 { 'fingerprint': 'node_link' }
        for node in nodes:
            fingerprint = ""
            try:
                protocol = node.split('://')[0].lower()
                if protocol == 'vmess':
                    # VMess V2RayN an VLESS an Trojan
                    try:
                        decoded_part = base64.b64decode(node[8:]).decode('utf-8')
                        vmess_config = json.loads(decoded_part)
                        fingerprint = f"{vmess_config.get('add', '')}:{vmess_config.get('port', '')}"
                    except: # 解码失败或非json，可能是其他格式
                         fingerprint = node.split('#')[0]
                elif protocol in ['vless', 'trojan', 'ss']:
                    # VLESS/Trojan/SS: user@server:port
                    match = re.search(r'//(?:.*@)?([^?#:]+:\d+)', node)
                    if match:
                        fingerprint = match.group(1)
                    else:
                         fingerprint = node.split('#')[0].split('?')[0] # 备用方案
                else: # SSR and others
                    fingerprint = node.split('#')[0]

                if fingerprint not in unique_proxies:
                    unique_proxies[fingerprint] = node
            except Exception as e:
                print(f"  -> Could not create fingerprint for node, skipping: {node[:30]}... ({e})")
                continue # 如果出错，跳过这个节点
        
        final_nodes = list(unique_proxies.values())
        removed_count = len(nodes) - len(final_nodes)
        print(f"  -> Deduplication complete. Removed {removed_count} duplicate nodes.")
        return final_nodes

    def sub_merge(self):
        list_dir, merge_dir = self.list_dir, self.merge_dir
        if os.path.exists(list_dir):
            for f in os.listdir(list_dir): os.remove(os.path.join(list_dir, f))
        else:
            os.makedirs(list_dir)

        all_nodes = [] # 使用列表，因为 set 无法保证顺序，且我们自己去重
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
                # 智能格式判断
                if is_likely_base64(raw_content):
                    print("  -> Detected Base64 format, decoding...")
                    plain_text_nodes = base64_decode(raw_content)
                else:
                    # 对于 YAML 或纯文本，我们都直接作为文本处理
                    # subconverter 核心能自动识别里面的节点
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
        
        # 步骤 1: 在 Python 中高效去重
        unique_nodes = self.deduplicate_nodes(all_nodes)
        print(f'Total unique nodes after deduplication: {len(unique_nodes)}')

        # 步骤 2: 将去重后的、干净的节点列表交给 subconverter
        print('\nHanding over unique nodes to subconverter for final packaging...')
        final_input_content = '\n'.join(sorted(unique_nodes))

        try:
            command = [
                self.subconverter_path,
                '--no-color',
                '--target', 'base64'
            ]
            # 动态添加配置
            if self.format_config.get('rename'):
                command.extend(['--rename', self.format_config['rename']])
            if self.format_config.get('include'):
                command.extend(['--include', self.format_config['include']])
            if self.format_config.get('exclude'):
                command.extend(['--exclude', self.format_config['exclude']])
            # 注意：subconverter 的去重可能与我们的不同，建议关闭
            if self.format_config.get('deduplicate') is False:
                 command.append('--no-deduplicate')

            print(f"  -> Executing subconverter with {len(unique_nodes)} nodes... (timeout: 180s)")
            
            process = subprocess.run(
                command,
                input=final_input_content.encode('utf-8'),
                capture_output=True,
                check=True, # 如果出错，会抛出异常
                timeout=180 # 3分钟超时，对于去重后的数据量应该足够
            )
            
            final_b64_content = process.stdout

            if not final_b64_content:
                print("  -> Conversion failed: Subconverter returned empty content.")
                if process.stderr: print("  -> Stderr:", process.stderr.decode('utf-8'))
                return

            print("  -> Conversion successful.")
            merge_path_final = os.path.join(self.merge_dir, 'sub_merge_base64.txt')
            with open(merge_path_final, 'wb') as f:
                f.write(final_b64_content)
            print(f'\nDone! Output merged nodes to {merge_path_final}.')

        except subprocess.TimeoutExpired:
            print("  -> FATAL ERROR: Subconverter timed out even after deduplication. The final node set might still be too large or complex.")
        except subprocess.CalledProcessError as e:
            print("  -> FATAL ERROR: Subconverter exited with an error.")
            print(f"  -> Stderr: {e.stderr.decode('utf-8')}")
        except FileNotFoundError:
            print(f"  -> FATAL ERROR: Subconverter executable not found at '{self.subconverter_path}'")
        except Exception as e:
            print(f"  -> FATAL ERROR: An unexpected error occurred: {e}")

    def readme_update(self):
        # ... (readme_update 保持不变) ...
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
    # ... (__main__ 保持不变) ...
    file_dir = {
        'list_dir': './sub/list/',
        'list_file': './sub/sub_list.json',
        'merge_dir': './sub/',
        'readme_file': './README.md',
    }
    format_config = {
        'deduplicate': False, # 推荐关闭，因为我们自己做了更可控的去重
        'rename': '',
        'include_remarks': '',
        'exclude_remarks': '',
        'config': ''
    }
    merge(file_dir, format_config)
