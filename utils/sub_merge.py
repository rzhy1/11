#!/usr/bin/env python3

import json
import os
import base64
import requests
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

def robust_b64decode(s: str) -> str:
    """
    一个更健壮的 Base64 解码函数，能处理各种填充问题。
    如果解码失败，假定输入是纯文本并直接返回。
    """
    s = s.strip()
    try:
        # 尝试标准解码
        return base64.b64decode(s).decode('utf-8', errors='ignore')
    except (ValueError, TypeError):
        # 如果失败，尝试补全 '='
        padding = len(s) % 4
        if padding != 0:
            s += '=' * (4 - padding)
        try:
            return base64.b64decode(s).decode('utf-8', errors='ignore')
        except Exception:
            # 如果还是失败，我们假定它就是纯文本
            return s

class merge():
    def __init__(self, file_dir, format_config):
        self.list_file = file_dir['list_file']
        self.merge_dir = file_dir['merge_dir']
        self.readme_file = file_dir.get('readme_file')
        self.format_config = format_config
        self.url_list = self.read_list()
        
        # 直接在构造函数中执行核心逻辑
        self.run()

    def read_list(self):
        with open(self.list_file, 'r', encoding='utf-8') as f:
            return [item for item in json.load(f) if item.get('enabled')]

    def fetch_single_url(self, url, item_type):
        """下载并解码单个 URL 的内容"""
        try:
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            raw_content = response.text.strip()
            
            if item_type == 'subscription':
                # 如果标记为 subscription, 尝试解码，否则视为纯文本
                return robust_b64decode(raw_content)
            else: # raw_text_url
                return raw_content
        except Exception as e:
            # 在工作线程中，我们不打印，只返回错误
            return {'error': str(e), 'url': url}

    def run(self):
        all_nodes = set()
        
        # --- 步骤 1: 并发获取所有节点 ---
        print("--- Step 1: Fetching all node data concurrently ---")
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_url = {}
            for item in self.url_list:
                urls = item.get('url', '').split('|')
                item_type = item.get('type', 'subscription')
                for url in urls:
                    if url:
                        future = executor.submit(self.fetch_single_url, url, item_type)
                        future_to_url[future] = item.get('remarks')

            for future in as_completed(future_to_url):
                remarks = future_to_url[future]
                content = future.result()
                if isinstance(content, dict) and 'error' in content:
                    print(f"  -> Failed to fetch from [{remarks}]. Reason: {content['error']}")
                elif content:
                    nodes_in_sub = {line for line in content.splitlines() if line.strip()}
                    all_nodes.update(nodes_in_sub)
                    print(f"  -> Success: Fetched {len(nodes_in_sub)} nodes from [{remarks}]")

        if not all_nodes:
            print("\nFATAL: No nodes were collected from any source. Aborting.")
            return

        # 对所有收集到的节点进行一次性的清洗
        pattern = re.compile(r"(server\s*:\s*)([^,'\"\s{}[\]]+:[^,'\"\s{}[\]]+)")
        def add_quotes(match): return f"{match.group(1)}'{match.group(2)}'"
        cleaned_nodes = {pattern.sub(add_quotes, node) for node in all_nodes}
        
        node_count = len(cleaned_nodes)
        print(f"\n--- Step 2: Collected {node_count} unique raw nodes. Starting batch processing. ---")

        # --- 步骤 2: 分批处理 ---
        BATCH_SIZE = 500  # 每批处理 500 个节点
        final_processed_nodes_text = []
        node_list = list(cleaned_nodes)

        subconverter_executable = os.path.abspath('./utils/subconverter/subconverter-linux-amd64')
        if not os.access(subconverter_executable, os.X_OK):
            os.chmod(subconverter_executable, 0o755)

        for i in range(0, len(node_list), BATCH_SIZE):
            batch = node_list[i:i + BATCH_SIZE]
            batch_num = (i // BATCH_SIZE) + 1
            print(f"  -> Processing batch {batch_num} ({len(batch)} nodes)...")

            temp_input_file = os.path.abspath(os.path.join(self.merge_dir, f'temp_batch_{batch_num}.txt'))
            
            with open(temp_input_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(batch))

            try:
                # 我们让 subconverter 处理（去重、应用规则等），并输出为明文节点列表
                command = [
                    subconverter_executable,
                    '-i', temp_input_file,
                    '-g' # generate, 表示生成节点列表, 而不是完整的配置文件
                ]
                if self.format_config.get('deduplicate'): command.append('--deduplicate')
                if self.format_config.get('config'): command.extend(['-c', os.path.abspath(self.format_config['config'])])

                result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=True, encoding='utf-8')
                
                # 读取处理后的结果（标准输出）
                processed_nodes = result.stdout.strip()
                if processed_nodes:
                    final_processed_nodes_text.append(processed_nodes)

            except subprocess.TimeoutExpired:
                print(f"    -!> Batch {batch_num} timed out and was skipped.")
            except subprocess.CalledProcessError as e:
                print(f"    -!> Batch {batch_num} failed and was skipped. Error: {e.stderr}")
            finally:
                if os.path.exists(temp_input_file): os.remove(temp_input_file)

        if not final_processed_nodes_text:
            print("\nFATAL: No nodes survived the batch processing. Aborting.")
            return

        print(f"\n--- Step 3: All batches processed. Aggregating and encoding final result. ---")
        
        # --- 步骤 3: 聚合结果并编码 ---
        final_plain_text = "\n".join(final_processed_nodes_text)
        
        # 直接对最终的明文节点列表进行 Base64 编码
        final_base64_content = base64.b64encode(final_plain_text.encode('utf-8')).decode('utf-8')

        final_output_file = os.path.abspath(os.path.join(self.merge_dir, 'sub_merge_base64.txt'))
        with open(final_output_file, 'w', encoding='utf-8') as f:
            f.write(final_base64_content)
            
        print(f"\nSuccessfully merged nodes to {final_output_file}")
        
        if self.readme_file:
            self.readme_update(final_output_file)

    def readme_update(self, merge_file_path):
        print('Updating README...')
        if not os.path.exists(merge_file_path) or not os.path.exists(self.readme_file):
            print("Warning: Merged file or README file not found. Skipping update.")
            return

        with open(self.readme_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        top_amount = 0
        try:
            with open(merge_file_path, 'r', encoding='utf-8') as f_merge:
                proxies_base64 = f_merge.read()
                if proxies_base64:
                    decoded = base64.b64decode(proxies_base64).decode('utf-8', errors='ignore')
                    top_amount = len([p for p in decoded.split('\n') if p.strip()])
        except Exception as e:
            print(f"Could not calculate node amount from merged file: {e}")
            top_amount = "Error"

        updated = False
        for i, line in enumerate(lines):
            if '### 所有节点' in line:
                if i + 1 < len(lines) and '合并节点总数' in lines[i+1]:
                    lines[i+1] = f'合并节点总数: `{top_amount}`\n'
                else:
                    lines.insert(i + 1, f'合并节点总数: `{top_amount}`\n')
                updated = True
                break
        
        if updated:
            with open(self.readme_file, 'w', encoding='utf-8') as f:
                f.write("".join(lines))
                print('完成!\n')
        else:
            print("Could not find the target line '### 所有节点' in README.md to update.")


if __name__ == '__main__':
    # 确保路径在 Actions 环境中是相对于项目根目录的
    project_root = os.getcwd()
    
    file_dir = {
        'list_file': os.path.join(project_root, 'sub/sub_list.json'),
        'merge_dir': os.path.join(project_root, 'sub/'),
        'readme_file': os.path.join(project_root, 'README.md')
    }
    
    # 确保 config 路径也正确
    config_path = os.path.join(project_root, 'utils/sub_config/clean_pref.ini')
    if not os.path.exists(config_path):
        # 如果干净的配置文件不存在，就不要传递 config 参数
        print(f"Warning: Clean config file not found at {config_path}. Proceeding without it.")
        config_path = ''

    format_config = {
        'deduplicate': True,
        'rename': '',
        'include_remarks': '',
        'exclude_remarks': '',
        'config': config_path
    }
    
    merge(file_dir, format_config)
