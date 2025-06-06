#!/usr/bin/env python3

import json, os, base64, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from subconverter import convert, base64_decode

merge_path = './sub/sub_merge_base64.txt'

class merge():
    def __init__(self, file_dir, format_config):
        self.list_dir = file_dir['list_dir']
        self.list_file = file_dir['list_file']
        self.merge_dir = file_dir['merge_dir']
        self.update_dir = file_dir['update_dir']
        self.readme_file = file_dir['readme_file']
        self.share_file = file_dir['share_file']

        self.format_config = {
            'deduplicate': bool(format_config['deduplicate']), 
            'rename': format_config['rename'],
            'include': format_config['include_remarks'], 
            'exclude': format_config['exclude_remarks'], 
            'config': format_config['config']
        }

        print("Initializing merge process...")
        self.url_list = self.read_list()
        print(f"Loaded {len(self.url_list)} enabled subscriptions")
        self.sub_merge()
        if self.readme_file != '':
            self.readme_update()

    def read_list(self):
        with open(self.list_file, 'r', encoding='utf-8') as f:
            raw_list = json.load(f)
        enabled_list = [item for item in raw_list if item['enabled']]
        print(f"Found {len(raw_list)} subscriptions, {len(enabled_list)} enabled")
        return enabled_list

    def sub_merge(self):
        url_list = self.url_list
        list_dir = self.list_dir
        merge_dir = self.merge_dir

        # Clear existing files
        print("\nCleaning output directories...")
        for dirpath, dirnames, filenames in os.walk(list_dir):
            for filename in filenames:
                os.remove(os.path.join(dirpath, filename))

        content_set = set()
        total_nodes = 0
        success_count = 0
        empty_count = 0

        print("\nStart processing subscriptions:")
        for url in url_list:
            print(f"\nProcessing subscription [{url['id']:02d}]: {url['remarks']}")
            try:
                content = convert(url['url'], 'url', {
                    'keep_encode': True,
                    'raw_format': True,
                    'escape_special_chars': False
                })
                
                if content:
                    nodes = content.splitlines()
                    node_count = len(nodes)
                    total_nodes += node_count
                    unique_nodes = len(set(nodes))
                    
                    content_set.update(nodes)
                    success_count += 1
                    
                    print(f"  ✓ Found {node_count} nodes ({unique_nodes} unique)")
                    if node_count != unique_nodes:
                        print(f"  ! Contains {node_count - unique_nodes} duplicate nodes")
                    
                    # Write individual subscription file
                    if self.list_dir:
                        output_path = f'{list_dir}{url["id"]:0>2d}.txt'
                        with open(output_path, 'w', encoding='utf-8') as file:
                            file.write(content)
                        print(f"  ↳ Saved to {output_path}")
                else:
                    empty_count += 1
                    print("  × No valid nodes found in this subscription")
                    
            except Exception as e:
                empty_count += 1
                print(f"  ! Error processing subscription: {str(e)}")
                continue

        # Final merge and output
        print("\nMerging all nodes...")
        unique_count = len(content_set)
        duplicate_rate = (total_nodes - unique_count) / total_nodes if total_nodes > 0 else 0
        
        print(f"\nProcessing Summary:")
        print(f"  Total subscriptions: {len(url_list)}")
        print(f"  Successfully processed: {success_count}")
        print(f"  Empty/failed subscriptions: {empty_count}")
        print(f"  Total nodes collected: {total_nodes}")
        print(f"  Unique nodes after deduplication: {unique_count}")
        print(f"  Duplicate rate: {duplicate_rate:.2%}")

        # Convert to base64 and save
        content = '\n'.join(content_set)
        content = convert(content, 'base64', self.format_config)
        
        merge_path = f'{merge_dir}/sub_merge_base64.txt'
        with open(merge_path, 'wb') as file:
            file.write(content.encode('utf-8'))
        
        print(f"\nMerge completed! Final output saved to {merge_path}")
        print(f"Total unique nodes in final output: {len(content_set)}")

    def readme_update(self):
        print('\nUpdating README...')
        try:
            with open(self.readme_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Find and update node count section
            updated = False
            for index in range(len(lines)):
                if lines[index] == '### 所有节点\n':
                    # Remove old count
                    if index + 1 < len(lines) and '合并节点总数' in lines[index + 1]:
                        lines.pop(index + 1)
                    
                    # Get current node count
                    with open(f'{self.merge_dir}sub_merge_base64.txt', 'r', encoding='utf-8') as f:
                        proxies_base64 = f.read()
                        proxies = base64_decode(proxies_base64)
                        node_count = len(proxies.split('\n'))
                    
                    # Insert new count
                    lines.insert(index + 1, f'合并节点总数: `{node_count}`\n')
                    updated = True
                    break
            
            if updated:
                with open(self.readme_file, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                print('README updated successfully')
            else:
                print('! README update failed: could not find node count section')
                
        except Exception as e:
            print(f'! Error updating README: {str(e)}')

if __name__ == '__main__':
    file_dir = {
        'list_dir': './sub/list/',
        'list_file': './sub/sub_list.json',
        'merge_dir': './sub/',
        'update_dir': './sub/update/',
        'readme_file': './README.md',
        'share_file': './sub/share.txt'
    }
    
    format_config = {
        'deduplicate': True,
        'rename': '',
        'include_remarks': '',
        'exclude_remarks': '',
        'config': ''
    }
    
    print("=== Subscription Merge Tool ===")
    merge(file_dir, format_config)
    print("\nAll tasks completed!")
