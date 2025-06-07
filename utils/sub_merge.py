#!/usr/bin/env python3

import json, os, base64, time, requests, re, subprocess, yaml

def base64_decode(s):
    try:
        s = s.strip()
        missing_padding = len(s) % 4
        if missing_padding: s += '=' * (4 - missing_padding)
        return base64.b64decode(s).decode('utf-8', 'ignore')
    except: return ""

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

    def run_subconverter(self, args):
        """一个通用的、健壮的 subconverter 调用函数"""
        original_cwd = os.getcwd()
        try:
            os.chdir(self.subconverter_dir)
            
            command = [f'./{self.subconverter_exec}', '--no-color'] + args
            print(f"  -> Executing: {' '.join(command)}")

            process = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=180)

            if process.returncode != 0:
                print(f"  -> Subconverter failed. Stderr:\n{process.stderr}")
                return None
            
            return process.stdout

        except FileNotFoundError:
            print(f"  -> FATAL: Executable not found in {self.subconverter_dir}")
            return None
        except subprocess.TimeoutExpired:
            print("  -> FATAL: Subconverter timed out.")
            return None
        except Exception as e:
            print(f"  -> FATAL: An unexpected error occurred: {e}")
            return None
        finally:
            os.chdir(original_cwd)

    def sub_merge(self):
        # 步骤 1: 将所有 URL 合并成一个超级 URL
        print("--- Step 1: Aggregating all subscription URLs ---")
        all_urls = [item.get('url') for item in self.url_list if item.get('url')]
        if not all_urls:
            print("No enabled URLs found. Exiting.")
            return
        
        super_url = '|'.join(all_urls)
        print(f"Aggregated {len(all_urls)} URLs into a single super URL.")

        # 步骤 2: 一次性调用 subconverter 将所有源转换为 Clash YAML
        print("\n--- Step 2: Batch converting all URLs to unified YAML format ---")
        # 我们需要一个临时的配置文件来指定输出
        temp_clash_config_path = os.path.join(self.subconverter_dir, 'temp_clash_config.ini')
        with open(temp_clash_config_path, 'w', encoding='utf-8') as f:
            f.write(f"[proxies]\nurl={super_url}\n") # 这里用一个临时的 section
        
        clash_provider_str = self.run_subconverter(['--config', temp_clash_config_path, '--target', 'clash'])
        
        # 清理临时配置文件
        os.remove(temp_clash_config_path)

        if not clash_provider_str:
            print("Failed to convert URLs to YAML. Aborting.")
            return

        try:
            data = yaml.safe_load(clash_provider_str)
            all_proxies_list = data.get('proxies', [])
            if not all_proxies_list:
                print("Conversion resulted in an empty proxy list. Aborting.")
                return
            print(f"Successfully converted and collected {len(all_proxies_list)} nodes.")
        except yaml.YAMLError as e:
            print(f"Failed to parse the YAML output from subconverter: {e}")
            return

        # 步骤 3: 在 Python 中高效去重
        print("\n--- Step 3: Deduplicating nodes in Python ---")
        unique_proxies_dict = {}
        for proxy in all_proxies_list:
            fingerprint = f"{proxy.get('server', '')}:{proxy.get('port', '')}"
            if fingerprint != ':' and fingerprint not in unique_proxies_dict:
                unique_proxies_dict[fingerprint] = proxy
        
        final_proxies = list(unique_proxies_dict.values())
        removed_count = len(all_proxies_list) - len(final_proxies)
        print(f'Deduplication complete. Removed {removed_count} duplicate nodes.')
        print(f'Final unique node count: {len(final_proxies)}')

        # 步骤 4: 最终打包
        print("\n--- Step 4: Final packaging with rules ---")
        final_clash_provider = {'proxies': final_proxies}
        final_clash_provider_str = yaml.dump(final_clash_provider, allow_unicode=True)
        
        # 将最终的 YAML 写入临时文件，交给 subconverter 做最后处理
        temp_final_input_path = os.path.join(self.subconverter_dir, 'final_input.yaml')
        with open(temp_final_input_path, 'w', encoding='utf-8') as f:
            f.write(final_clash_provider_str)
            
        final_args = [
            '--target', 'base64',
            '--url', temp_final_input_path # 输入是我们的最终 YAML 文件
        ]
        if self.format_config.get('rename'): final_args.extend(['--rename', self.format_config['rename']])
        if self.format_config.get('include'): final_args.extend(['--include', self.format_config['include']])
        if self.format_config.get('exclude'): final_args.extend(['--exclude', self.format_config['exclude']])
        if self.format_config.get('deduplicate') is False: final_args.append('--no-deduplicate')

        final_b64_content_bytes = self.run_subconverter(final_args)
        os.remove(temp_final_input_path)

        if not final_b64_content_bytes:
            print("Final packaging failed.")
            return
            
        final_b64_content = final_b64_content_bytes.encode('utf-8')

        print("Final packaging successful.")
        merge_path_final = os.path.join(self.merge_dir, 'sub_merge_base64.txt')
        with open(merge_path_final, 'wb') as f:
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
