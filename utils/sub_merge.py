#!/usr/bin/env python3

import json, os, base64, time, requests, re, subprocess
from concurrent.futures import ThreadPoolExecutor

# 我们自己实现可靠的 base64_decode，不再从 subconverter 包导入
def base64_decode(s):
    try:
        s = s.strip()
        missing_padding = len(s) % 4
        if missing_padding: s += '=' * (4 - missing_padding)
        return base64.b64decode(s).decode('utf-8', 'ignore')
    except: return ""

def is_likely_base64(s):
    s = s.strip()
    # 改进正则以匹配可能的 Base64 字符串
    if not re.match(r'^[A-Za-z0-9+/=\s]+$', s):
        return False
    # 移除所有空白字符后检查长度
    s_no_whitespace = "".join(s.split())
    if len(s_no_whitespace) % 4 != 0:
        return False
    try:
        base64.b64decode(s_no_whitespace, validate=True)
        return True
    except Exception:
        return False

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

    def fetch_and_process_url(self, item):
        """用于并发处理单个订阅源，返回初步提取的节点行"""
        item_url = item.get('url')
        if not item_url: return []
        
        try:
            response = requests.get(item_url, timeout=20)
            response.raise_for_status()
            raw_content = response.text.strip()
            if not raw_content: return []

            # 我们不再做复杂的格式判断，直接返回所有非空行
            # 让 subconverter 核心去识别哪些是有效节点
            return [line.strip() for line in raw_content.splitlines() if line.strip()]
        except Exception as e:
            print(f"  -> Failed to fetch [ID: {item.get('id'):0>2d}] {item.get('remarks')}. Reason: {e}")
            return []

    def deduplicate_nodes(self, nodes):
        """
        这个去重函数现在可以暂时简化，因为 subconverter 也会去重。
        主要目的是去除完全相同的行。
        """
        print("\n--- Step 2: Performing basic line-based deduplication ---")
        unique_lines = list(set(nodes))
        removed_count = len(nodes) - len(unique_lines)
        print(f"Removed {removed_count} identical lines.")
        return unique_lines

    def sub_merge(self):
        print("--- Step 1: Concurrently fetching all subscriptions ---")
        all_lines_raw = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_url = {executor.submit(self.fetch_and_process_url, item): item for item in self.url_list}
            for future in future_to_url:
                item = future_to_url[future]
                try:
                    lines = future.result()
                    if lines:
                        print(f"  -> Fetched {len(lines)} lines from [ID: {item.get('id'):0>2d}] {item.get('remarks')}")
                        all_lines_raw.extend(lines)
                except Exception as e:
                    print(f"An error occurred in a thread for {item.get('remarks')}: {e}")
        
        print(f"\nTotal lines collected: {len(all_lines_raw)}")
        if not all_lines_raw:
            print('Merging failed: No nodes collected.')
            return

        unique_lines = self.deduplicate_nodes(all_lines_raw)
        print(f'Total unique lines after basic deduplication: {len(unique_lines)}')

        print("\n--- Step 3: Final processing with subconverter ---")
        final_input_content = '\n'.join(sorted(unique_lines))

        original_cwd = os.getcwd()
        try:
            os.chdir(os.path.dirname(self.subconverter_path))
            exec_name = os.path.basename(self.subconverter_path)
            
            command = [f'./{exec_name}', '--no-color', '--target', 'base64']
            
            # 传递 format_config 中的规则
            if self.format_config.get('rename'): command.extend(['--rename', self.format_config['rename']])
            if self.format_config.get('include'): command.extend(['--include', self.format_config['include']])
            if self.format_config.get('exclude'): command.extend(['--exclude', self.format_config['exclude']])
            # 让 subconverter 进行它专业的去重
            if self.format_config.get('deduplicate') is not False:
                pass # 默认去重
            else:
                command.append('--no-deduplicate')

            print(f"Executing subconverter with {len(unique_lines)} lines... (timeout: 180s)")
            
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
            print("FATAL ERROR: Subconverter timed out.")
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
        # ... (readme_update 保持不变)
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
    # ... (__main__ 保持不变)
    file_dir = {
        'list_dir': './sub/list/',
        'list_file': './sub/sub_list.json',
        'merge_dir': './sub/',
        'readme_file': './README.md',
    }
    format_config = {
        'deduplicate': True, # 推荐开启，让 subconverter 做专业去重
        'rename': '',
        'include_remarks': '',
        'exclude_remarks': '',
        'config': ''
    }
    merge(file_dir, format_config)
