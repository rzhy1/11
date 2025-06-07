#!/usr/bin/env python3
import json, os, base64, time, requests, yaml, re
# 重新引入 subconverter，它是我们强大的后盾
from subconverter import convert, base64_decode

# 辅助函数，用于更可靠地判断 Base64
def is_likely_base64(s):
    # 基础检查：长度、字符集等
    if len(s) % 4 != 0 or not re.match('^[A-Za-z0-9+/=]+$', s):
        return False
    try:
        # 尝试解码，如果内容看起来像乱码（包含大量非 ascii 控制字符），可能不是节点列表的 base64
        decoded = base64.b64decode(s).decode('utf-8')
        # 简单启发式：如果解码后包含常见协议或关键词，则可能性高
        if 'vmess://' in decoded or 'proxies:' in decoded or 'ss://' in decoded:
            return True
        # 如果解码后全是二进制数据，可能性低
        if any(char.isprintable() or char.isspace() for char in decoded):
            # 如果可打印字符比例很高，也可能是
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
        """对节点列表的每一行进行清洗，修复潜在的YAML语法问题。"""
        cleaned_nodes = []
        # 这个正则专门修复 server: [ipv6地址] 的问题
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
                
                # 【智能格式判断】
                # 1. 判断是否是 Base64
                if is_likely_base64(raw_content):
                    print("  -> Detected Base64 format, decoding...")
                    plain_text_nodes = base64.b64decode(raw_content).decode('utf-8', errors='ignore')
                # 2. 如果不是 Base64，判断是否是 YAML
                elif 'proxies:' in raw_content or 'proxy-groups:' in raw_content:
                    print("  -> Detected YAML format.")
                    # 对于 YAML，我们直接把整个内容交给 subconverter，它能专业地解析
                    plain_text_nodes = raw_content
                # 3. 否则，认为是纯文本节点列表
                else:
                    print("  -> Detected Plain Text node list format.")
                    plain_text_nodes = raw_content

                # 从解码/原始文本中提取有效节点
                # 注意：我们不再用 startswith 来过滤，因为YAML格式的节点不符合这个规则
                # 我们将所有内容都加入，让 subconverter 去识别
                found_nodes = [line.strip() for line in plain_text_nodes.splitlines() if line.strip()]
                
                if found_nodes:
                    # 在加入集合前，先进行清洗
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
        
        print('Handing over to subconverter for final processing, filtering, and packaging...')

        # 将所有收集到的干净行拼接起来
        final_input_content = '\n'.join(sorted(list(content_set)))
        
        # 从 self.format_config 获取 subconverter 的配置
        subconverter_config = {
            'deduplicate': bool(self.format_config.get('deduplicate', True)),
            'rename': self.format_config.get('rename', ''),
            'include': self.format_config.get('include_remarks', ''),
            'exclude': self.format_config.get('exclude_remarks', ''),
            'config': self.format_config.get('config', '')
        }
        
        # 【核心】调用 subconverter 进行专业处理
        final_b64_content = convert(final_input_content, 'base64', subconverter_config)

        if not final_b64_content:
            print("  -> Subconverter returned empty content. There might be no valid nodes after filtering.")
            return

        print(f"  -> Subconverter processing successful.")

        merge_path_final = f'{self.merge_dir}/sub_merge_base64.txt'
        with open(merge_path_final, 'wb') as file:
            file.write(final_b64_content)
        print(f'\nDone! Output merged nodes to {merge_path_final}.')


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
    
    # 确保 format_config 被正确传递
    format_config = {
        'deduplicate': True,
        'rename': '',
        'include_remarks': '',
        'exclude_remarks': '',
        'config': ''
    }
    
    merge(file_dir, format_config)
