#!/usr/bin/env python3

import json, os, base64, time, requests, re
# 我们现在可以安全地使用这个导入了
from subconverter import convert, base64_decode

# 辅助函数 is_likely_base64 保持不变
def is_likely_base64(s):
    if len(s.strip()) % 4 != 0 or not re.match('^[A-Za-z0-9+/=]+$', s.strip()):
        return False
    try:
        decoded = base64.b64decode(s).decode('utf-8')
        if any(kw in decoded for kw in ['vmess://', 'proxies:', 'ss://', 'vless://']):
            return True
        if any(char.isprintable() or char.isspace() for char in decoded):
            return True
        return False
    except Exception:
        return False

class merge():
    def __init__(self,file_dir,format_config):
        self.list_dir = file_dir['list_dir']
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
            raw_list = json.load(f)
        return [item for item in raw_list if item.get('enabled')]

    def cleanup_node_list(self, nodes):
        cleaned_nodes = []
        pattern = re.compile(r"(server\s*:\s*)([^,'\"\s{}[\]]+:[^,'\"\s{}[\]]+)")
        def add_quotes(match):
            return f"{match.group(1)}'{match.group(2)}'"
        for node in nodes:
            cleaned_node = pattern.sub(add_quotes, node)
            cleaned_nodes.append(cleaned_node)
        return cleaned_nodes

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

        for item in url_list:
            item_url = item.get('url')
            item_id = item.get('id')
            item_remarks = item.get('remarks')
            
            if not item_url:
                print(f"Skipping [ID: {item_id:0>2d}] {item_remarks} because URL is empty.")
                continue

            print(f"Processing [ID: {item_id:0>2d}] {item_remarks} from {item_url}")
            
            try:
                response = requests.get(item_url, timeout=15)
                response.raise_for_status()
                raw_content = response.text.strip()
                if not raw_content: raise ValueError("Downloaded content is empty.")
                plain_text_nodes = ''
                if is_likely_base64(raw_content):
                    print("  -> Detected Base64 format, decoding...")
                    plain_text_nodes = base64_decode(raw_content)
                elif 'proxies:' in raw_content or 'proxy-groups:' in raw_content:
                    print("  -> Detected YAML format.")
                    plain_text_nodes = raw_content
                else:
                    print("  -> Detected Plain Text node list format.")
                    plain_text_nodes = raw_content
                found_nodes = [line.strip() for line in plain_text_nodes.splitlines() if line.strip()]
                if found_nodes:
                    cleaned_nodes = self.cleanup_node_list(found_nodes)
                    content_set.update(cleaned_nodes)
                    print(f'  -> Success! Added {len(cleaned_nodes)} lines to the merge pool.')
                else:
                    print(f"  -> ⭐⭐ Warning: No content lines found after processing.")
            except Exception as e:
                print(f"  -> Failed! Reason: {e}")
            print()

        if not content_set:
            print('Merging failed: No nodes collected from any source.')
            return
        
        print(f'\nTotal unique lines collected: {len(content_set)}')
        
        # 【核心修复】将所有节点写入一个临时文件
        temp_subscription_file = os.path.join(self.merge_dir, 'temp_sub_for_convert.txt')
        final_input_content = '\n'.join(sorted(list(content_set)))
        
        with open(temp_subscription_file, 'w', encoding='utf-8') as f:
            f.write(final_input_content)

        print(f'Handing over temporary subscription file to subconverter: {temp_subscription_file}')
        
        subconverter_config = {
            'deduplicate': self.format_config.get('deduplicate', True),
            'rename': self.format_config.get('rename', ''),
            'include': self.format_config.get('include_remarks', ''),
            'exclude': self.format_config.get('exclude_remarks', ''),
            'config': self.format_config.get('config', '')
        }
        
        try:
            # 【核心修复】将临时文件的路径作为 subscription 参数传递
            final_b64_content = convert(temp_subscription_file, 'base64', subconverter_config)

            if not final_b64_content:
                print("  -> Subconverter returned empty content. There might be no valid nodes after filtering.")
                # 清理临时文件
                os.remove(temp_subscription_file)
                return

            print(f"  -> Subconverter processing successful.")
            merge_path_final = f'{self.merge_dir}/sub_merge_base64.txt'
            # convert 函数返回的是字符串，所以用 'w' 写入
            with open(merge_path_final, 'w', encoding='utf-8') as file:
                file.write(final_b64_content)
            print(f'\nDone! Output merged nodes to {merge_path_final}.')

        except Exception as e:
            print(f"  -> FATAL ERROR during final conversion: {e}")
        finally:
            # 无论成功与否，都删除临时文件
            if os.path.exists(temp_subscription_file):
                os.remove(temp_subscription_file)


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
    file_dir = {
        'list_dir': './sub/list/',
        'list_file': './sub/sub_list.json',
        'merge_dir': './sub/',
        'readme_file': './README.md',
    }
    format_config = {
        'deduplicate': True,
        'rename': '',
        'include_remarks': '',
        'exclude_remarks': '',
        'config': ''
    }
    merge(file_dir, format_config)
