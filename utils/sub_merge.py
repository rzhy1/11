#!/usr/bin/env python3

import json, os, base64, time, requests, re
# 导入我们全新的、可靠的 convert 函数
from subconverter import convert, base64_decode

def is_likely_base64(s):
    s = s.strip()
    if len(s) % 4 != 0 or not re.match(r'^[A-Za-z0-9+/=]+$', s):
        return False
    try:
        base64.b64decode(s, validate=True)
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
        self.url_list = self.read_list()
        self.sub_merge()
        if self.readme_file:
            self.readme_update()

    def read_list(self):
        with open(self.list_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def cleanup_node_list(self, nodes):
        cleaned_nodes = []
        pattern = re.compile(r"(server\s*:\s*)([^,'\"\s{}[\]]+:[^,'\"\s{}[\]]+)")
        def add_quotes(match):
            return f"{match.group(1)}'{match.group(2)}'"
        for node in nodes:
            cleaned_nodes.append(pattern.sub(add_quotes, node))
        return cleaned_nodes

    def sub_merge(self):
        url_list = [item for item in self.url_list if item.get('enabled')]
        list_dir, merge_dir = self.list_dir, self.merge_dir

        if os.path.exists(list_dir):
            for f in os.listdir(list_dir):
                os.remove(os.path.join(list_dir, f))
        else:
            os.makedirs(list_dir)

        content_set = set()
        for item in url_list:
            item_url, item_id, item_remarks = item.get('url'), item.get('id'), item.get('remarks')
            if not item_url:
                print(f"Skipping [ID: {item_id:0>2d}] {item_remarks} (URL is empty).")
                continue
            
            print(f"Processing [ID: {item_id:0>2d}] {item_remarks} from {item_url}")
            try:
                response = requests.get(item_url, timeout=15)
                response.raise_for_status()
                raw_content = response.text.strip()
                if not raw_content: raise ValueError("Downloaded content is empty.")

                plain_text_nodes = ""
                if is_likely_base64(raw_content):
                    print("  -> Detected Base64 format, decoding...")
                    plain_text_nodes = base64_decode(raw_content)
                elif 'proxies:' in raw_content or 'proxy-groups:' in raw_content:
                    print("  -> Detected YAML format.")
                    plain_text_nodes = raw_content
                else:
                    print("  -> Detected Plain Text node list.")
                    plain_text_nodes = raw_content
                
                found_lines = [line.strip() for line in plain_text_nodes.splitlines() if line.strip()]
                if found_lines:
                    cleaned_lines = self.cleanup_node_list(found_lines)
                    content_set.update(cleaned_lines)
                    print(f'  -> Success! Added {len(cleaned_lines)} lines to merge pool.')
                else:
                    print("  -> Warning: No content lines found after processing.")
            except Exception as e:
                print(f"  -> Failed! Reason: {e}")
            finally:
                print()

        if not content_set:
            print('Merging failed: No nodes collected.')
            return

        print(f'\nTotal unique lines collected: {len(content_set)}')
        print('Handing over to the simplified subconverter wrapper...')

        final_input_content = '\n'.join(sorted(list(content_set)))
        
        # 直接调用我们简化后的 convert 函数
        final_b64_content = convert(final_input_content, 'base64', self.format_config)

        if not final_b64_content:
            print("Conversion failed. Subconverter returned empty content.")
            return

        print("Conversion successful.")
        merge_path_final = os.path.join(self.merge_dir, 'sub_merge_base64.txt')
        with open(merge_path_final, 'w', encoding='utf-8') as f:
            f.write(final_b64_content)
        print(f'\nDone! Output merged nodes to {merge_path_final}.')

    def readme_update(self):
        # ... (readme_update 方法保持不变) ...
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
    # ... (__main__ 方法保持不变) ...
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
