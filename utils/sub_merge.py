#!/usr/bin/env python3

import json, os, base64, time, requests, re
# 【核心修改】引入 subprocess 来直接调用外部命令
import subprocess

# 辅助函数 is_base64 保持不变
def is_base64(s):
    try:
        if len(s.strip()) % 4 != 0: return False
        base64.b64decode(s, validate=True)
        return True
    except Exception:
        return False
# subconverter.convert 和 subconverter.base64_decode 依然需要，因为我们在前面用到了
from subconverter import base64_decode

class merge():
    def __init__(self,file_dir,format_config):
        # __init__ 保持不变
        self.list_dir = file_dir['list_dir']
        self.list_file = file_dir['list_file']
        self.merge_dir = file_dir['merge_dir']
        self.readme_file = file_dir.get('readme_file')

        self.format_config = {
            'deduplicate': bool(format_config.get('deduplicate', True)), 
            'rename': format_config.get('rename', ''),
            'include': format_config.get('include_remarks', ''), 
            'exclude': format_config.get('exclude_remarks', ''), 
            'config': format_config.get('config', '')
        }

        self.url_list = self.read_list()
        self.sub_merge()
        if self.readme_file:
            self.readme_update()

    # read_list 和 cleanup_node_list 保持不变
    def read_list(self):
        with open(self.list_file, 'r', encoding='utf-8') as f:
            raw_list = json.load(f)
        return [item for item in raw_list if item.get('enabled')]
    
    def cleanup_node_list(self, nodes):
        cleaned_nodes = []
        pattern = re.compile(r"(server\s*:\s*)([^,'\"\s{}[\]]+:[^,'"\s{}[\]]+)")
        def add_quotes(match):
            return f"{match.group(1)}'{match.group(2)}'"
        for node in nodes:
            cleaned_node = pattern.sub(add_quotes, node)
            cleaned_nodes.append(cleaned_node)
        return cleaned_nodes

    def sub_merge(self):
        # 前半部分的节点获取和处理逻辑完全正确，保持不变
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
        for item in url_list:
            item_id = item.get('id')
            item_remarks = item.get('remarks')
            item_type = item.get('type', 'subscription')
            urls = item.get('url', '').split('|')
            item_nodes = set()
            has_error = False

            for url in urls:
                if not url: continue
                print(f"Processing [ID: {item_id}] {item_remarks} - URL: {url[:50]}...")
                try:
                    response = requests.get(url, timeout=15)
                    response.raise_for_status()
                    raw_content = response.text.strip()
                    plain_text_nodes = ''
                    if item_type == 'subscription':
                        if is_base64(raw_content):
                            plain_text_nodes = base64_decode(raw_content)
                        else:
                            print(f"  -> Warning: type is 'subscription' but content is not Base64. Treating as plain text.")
                            plain_text_nodes = raw_content
                    else: # raw_text_url
                        plain_text_nodes = raw_content
                    if plain_text_nodes:
                        nodes = [line for line in plain_text_nodes.splitlines() if line.strip()]
                        cleaned_nodes = self.cleanup_node_list(nodes)
                        item_nodes.update(cleaned_nodes)
                    else:
                        raise ValueError("No valid nodes found after processing.")
                except Exception as e:
                    print(f"  -> Failed for URL {url[:50]}... Reason: {e}")
                    has_error = True
            
            if item_nodes:
                content_set.update(item_nodes)
                print(f"  => Success for [ID: {item_id}]! Found and added {len(item_nodes)} unique nodes.\n")
                with open(f'{list_dir}{item_id:0>2d}.txt', 'w', encoding='utf-8') as f:
                    f.write('\n'.join(sorted(list(item_nodes))))
            elif not has_error:
                print(f"  => Finished for [ID: {item_id}], but no nodes were found.\n")


        if not content_set:
            print('Merging failed: No nodes collected from any source.')
            return

        print(f'\nMerging {len(content_set)} unique nodes...')
        
        # --- 【核心修改】 ---
        # 1. 准备要传递给命令行工具的参数和文件
        temp_merge_file = os.path.abspath(f'{merge_dir}/temp_merge.txt')
        final_output_file = os.path.abspath(f'{merge_dir}/sub_merge_base64.txt')
        subconverter_executable = os.path.abspath('./utils/subconverter/subconverter-linux-amd64')
        config_file_path = self.format_config.get('config')
        
        # 确保 subconverter 可执行
        if not os.access(subconverter_executable, os.X_OK):
            os.chmod(subconverter_executable, 0o755)

        with open(temp_merge_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(sorted(list(content_set))))

        try:
            # 2. 构建命令行参数列表
            command = [
                subconverter_executable,
                '-i', temp_merge_file,   # 输入文件
                '-o', final_output_file,  # 输出文件
                '-t', 'base64'            # 目标格式
            ]
            
            # 动态添加其他配置参数
            if self.format_config.get('deduplicate'):
                command.extend(['--deduplicate'])
            if self.format_config.get('rename'):
                command.extend(['-r', self.format_config['rename']])
            if self.format_config.get('include'):
                command.extend(['--include', self.format_config['include']])
            if self.format_config.get('exclude'):
                command.extend(['--exclude', self.format_config['exclude']])
            if config_file_path:
                # 使用绝对路径以避免歧义
                abs_config_path = os.path.abspath(config_file_path)
                command.extend(['-c', abs_config_path])
            
            print("Executing command:", ' '.join(command))
            
            # 3. 使用 subprocess 直接调用可执行文件
            result = subprocess.run(command, capture_output=True, text=True, check=True)

            # 打印 subconverter 的标准输出和错误（如果有的话）
            if result.stdout:
                print("Subconverter STDOUT:\n", result.stdout)
            if result.stderr:
                print("Subconverter STDERR:\n", result.stderr)

            print(f'Done! Output merged nodes to {final_output_file}.')

        except subprocess.CalledProcessError as e:
            # 如果命令执行失败（返回非零退出码）
            print(f"FATAL: Final merge failed! Subconverter process exited with error.")
            print("Subconverter STDERR:\n", e.stderr)
        except Exception as e:
            print(f"FATAL: An unexpected error occurred during final merge! Reason: {e}")
        finally:
            # 4. 清理临时文件
            if os.path.exists(temp_merge_file):
                os.remove(temp_merge_file)
    
    # readme_update 保持不变
    def readme_update(self):
        print('Updating README...')
        merge_file_path = f'{self.merge_dir}/sub_merge_base64.txt'
        if not os.path.exists(merge_file_path):
            print(f"Warning: Merged file not found. Skipping README update.")
            return

        with open(self.readme_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        try:
            for index, line in enumerate(lines):
                if '### 所有节点' in line:
                    if index + 1 < len(lines) and '合并节点总数' in lines[index+1]:
                        lines.pop(index+1) 

                    with open(merge_file_path, 'r', encoding='utf-8') as f_merge:
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
    # __main__ 保持不变
    file_dir = {
        'list_dir': './sub/list/',
        'list_file': './sub/sub_list.json',
        'merge_dir': './sub/',
        'readme_file': './README.md'
    }
    
    format_config = {
        'deduplicate': True,
        'rename': '',
        'include_remarks': '',
        'exclude_remarks': '',
        # 我们在这里也清空 config，让命令行调用更纯粹
        'config': '' 
    }
    
    merge(file_dir, format_config)
