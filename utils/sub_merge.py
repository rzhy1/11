import json, os, base64, time
from concurrent.futures import ThreadPoolExecutor, as_completed # 新增导入 as_completed
import shutil # 新增导入 shutil

# 假设 subconverter 模块提供 convert 和 base64_decode 函数
# from subconverter import convert, base64_decode

class merge():
    def __init__(self,file_dir,format_config):
        # ... (其他初始化代码不变)
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

        self.url_list = self.read_list()
        # 将 sub_merge 和 readme_update 的调用移出 __init__，建议在外部调用一个 run() 方法
        # self.sub_merge()
        # if self.readme_file != '':
        #     self.readme_update()

    def run(self): # 新增一个 run 方法来执行主要逻辑
        self.sub_merge()
        if self.readme_file != '':
            self.readme_update()

    # ... (read_list 方法不变)

    def sub_merge(self):
        url_list = self.url_list
        list_dir = self.list_dir
        merge_dir = self.merge_dir

        # 优化1: 更高效地清空目录
        if os.path.exists(list_dir):
            shutil.rmtree(list_dir) # 递归删除目录及其内容
        os.makedirs(list_dir, exist_ok=True) # 重新创建目录

        content_set = set()
        
        # 优化2: 使用 ThreadPoolExecutor 进行并发处理
        max_workers = os.cpu_count() * 2 # 根据CPU核心数设置合理的并发数，可以调整
        if max_workers is None: # os.cpu_count() 可能返回 None
            max_workers = 4 # 默认值
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(convert, url['url'], 'url', {'keep_encode': True, 'raw_format': True, 'escape_special_chars': False}): url for url in url_list}
            
            for future in as_completed(futures):
                url = futures[future]
                try:
                    content = future.result() # 获取 convert 函数的返回值
                    if content:
                        content_set.update(content.splitlines())
                        print(f'Writing content of {url["remarks"]} to {url["id"]:0>2d}.txt')
                    else:
                        content = 'No nodes were found in url.'
                        print(f'Writing error of {url["remarks"]} to {url["id"]:0>2d}.txt (No nodes found or conversion failed)')
                    
                    # 优化3: 使用 os.path.join 拼接路径
                    output_file_path = os.path.join(list_dir, f'{url["id"]:0>2d}.txt')
                    with open(output_file_path, 'w', encoding='utf-8') as file:
                        file.write(content)
                except Exception as exc:
                    print(f'{url["remarks"]} generated an exception: {exc}')
                    # 可以在这里记录下失败的 URL
                    output_file_path = os.path.join(list_dir, f'{url["id"]:0>2d}.txt')
                    with open(output_file_path, 'w', encoding='utf-8') as file:
                        file.write(f'Error converting {url["url"]}: {exc}')

        print('Merging nodes...')
        content = '\n'.join(sorted(list(content_set))) # 可以先排序再合并，保证每次输出稳定
        content = convert(content, 'base64', self.format_config)
        
        # 优化3: 使用 os.path.join 拼接路径
        merge_path = os.path.join(merge_dir, 'sub_merge_base64.txt')
        with open(merge_path, 'wb') as file: # 'wb' 是正确的，因为 base64 编码后的数据通常当作二进制写入
            file.write(content.encode('utf-8'))
        print(f'Done! Output merged nodes to {merge_path}.')

    def readme_update(self):
        print('Updating README...')
        
        # 优化3: 使用 os.path.join 拼接路径
        readme_file_path = self.readme_file
        merge_file_path = os.path.join(self.merge_dir, 'sub_merge_base64.txt')

        # 确保文件存在再读取，避免FileNotFoundError
        if not os.path.exists(readme_file_path):
            print(f"Error: README file not found at {readme_file_path}")
            return
            
        with open(readme_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        found_target = False
        for index in range(len(lines)):
            if lines[index] == '### 所有节点\n': # 目标行内容
                # 清除旧内容
                if index + 1 < len(lines): # 避免索引越界
                    lines.pop(index+1) # 删除节点数量

                if not os.path.exists(merge_file_path):
                    print(f"Error: Merged file not found at {merge_file_path}")
                    top_amount = 0 # 无法获取节点数
                else:
                    with open(merge_file_path, 'r', encoding='utf-8') as f:
                        proxies_base64 = f.read()
                        proxies = base64_decode(proxies_base64)
                        proxies = proxies.split('\n')
                        # len(proxies) 可能会因为末尾的空行多一个，-1 是一个常见处理方式
                        top_amount = len([p for p in proxies if p.strip()]) # 更严谨地计算非空节点
                
                lines.insert(index+1, f'合并节点总数: `{top_amount}`\n')
                found_target = True
                break
        
        if not found_target:
            print("Warning: '### 所有节点' section not found in README.")

        # 写入 README 内容
        with open(readme_file_path, 'w', encoding='utf-8') as f:
             data = ''.join(lines)
             f.write(data)
        print('完成!\n')

# 在 __main__ 中实例化并调用 run 方法
if __name__ == '__main__':
    file_dir = {
        'list_dir': './sub/list/',
        'list_file': './sub/sub_list.json',
        'merge_dir': './sub/',
        'update_dir': './sub/update/', # 目前未使用到，可以考虑移除或未来使用
        'readme_file': './README.md',
        'share_file': './sub/share.txt' # 目前未使用到，可以考虑移除或未来使用
    }
    
    format_config = {
        'deduplicate': True,
        'rename': '',
        'include_remarks': '',
        'exclude_remarks': '',
        'config': ''
    }
    
    # 创建实例并调用 run 方法
    merger = merge(file_dir, format_config)
    merger.run()
