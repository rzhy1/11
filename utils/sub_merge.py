#!/usr/bin/env python3

import json, os, base64, time, requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from subconverter import convert, base64_decode

merge_path = './sub/sub_merge_base64.txt'

class merge():
	def __init__(self,file_dir,format_config):
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
		self.sub_merge()
		if self.readme_file != '':
			self.readme_update()

	def read_list(self): # 将 sub_list.json Url 内容读取为列表
		with open(self.list_file, 'r', encoding='utf-8') as f:
			raw_list = json.load(f)
		return [item for item in raw_list if item['enabled']]

	def sub_merge(self): # 将转换后的所有 Url 链接内容合并转换 YAML or Base64, ，并输出文件，输入订阅列表。
		url_list = self.url_list
		list_dir = self.list_dir
		merge_dir = self.merge_dir

		if os.path.exists(list_dir):
			for dirpath, dirnames, filenames in os.walk(list_dir):
				os.remove(os.path.join(dirpath, filename))
		else:
			os.makedirs(list_dir)

		# 这里不再用 set, 而是用 list, 因为我们要保留 YAML 格式的节点
		all_proxies_yaml = []

		for item in url_list:
			content = ''
			item_url = item.get('url')
			item_id = item.get('id')
			item_remarks = item.get('remarks')
			
			if not item_url:
				print(f'Skipping {item_remarks} (ID: {item_id}) due to empty URL.\n')
				continue

			item_type = item.get('type', 'subscription')
			print(f'Processing [ID: {item_id}] {item_remarks} with type [{item_type}]...')

			# 统一将各种源转换为 Clash (YAML) 格式的节点列表
			try:
				# 使用 convert 函数，指定目标为 'clash'
				# subconverter 会返回一个包含 'proxies' 列表的 YAML 字符串
				yaml_content = convert(item_url, 'clash', {'url_type': item_type})
				
				if yaml_content:
					# 解析 YAML，只提取 proxies 部分
					import yaml # 需要安装 pyyaml: pip install pyyaml
					data = yaml.safe_load(yaml_content)
					proxies = data.get('proxies', [])
					if proxies:
						all_proxies_yaml.extend(proxies)
						print(f'Success! Found and converted {len(proxies)} nodes.\n')
						# 写入缓存文件（可选，但有助于调试）
						with open(f'{list_dir}{item_id:0>2d}.yml', 'w', encoding='utf-8') as f:
							yaml.dump({'proxies': proxies}, f, allow_unicode=True)
					else:
						print('Warning: Source converted, but no proxies found inside.\n')
				else:
					print('Failed: Conversion returned empty content.\n')
			
			except Exception as e:
				print(f'Error processing subscription: {e}\n')

		if not all_proxies_yaml:
			print('Merging failed: No nodes collected from any source.')
			return

		print(f'\nMerging {len(all_proxies_yaml)} nodes in total...')
		
		# 将收集到的所有 YAML 格式的节点组合成一个大的 Clash 配置
		final_clash_config = {
			'proxies': all_proxies_yaml
		}
		
		# 将这个 Python 字典转换回 YAML 字符串
		import yaml
		final_yaml_str = yaml.dump(final_clash_config, allow_unicode=True)

		# 最后，将这个完整的 YAML 字符串交给 subconverter 做最终的格式化和输出
		final_content = convert(final_yaml_str, 'base64', self.format_config)
		
		merge_path_final = f'{merge_dir}/sub_merge_base64.txt'
		with open(merge_path_final, 'wb') as file:
			file.write(final_content.encode('utf-8'))
		print(f'Done! Output merged nodes to {merge_path_final}.')

	def readme_update(self): # 更新 README 节点信息
		print('Updating README...')
		with open(self.readme_file, 'r', encoding='utf-8') as f:
			lines = f.readlines()
			f.close()

		# 所有节点打印
		for index in range(len(lines)):
			if lines[index] == '### 所有节点\n': # 目标行内容
				# 清除旧内容
				lines.pop(index+1) # 删除节点数量

				with open(f'{self.merge_dir}sub_merge_base64.txt', 'r', encoding='utf-8') as f:
					proxies_base64 = f.read()
					proxies = base64_decode(proxies_base64)
					proxies = proxies.split('\n')
					top_amount = len(proxies) - 1
					f.close()
				lines.insert(index+1, f'合并节点总数: `{top_amount}`\n')
				break
		
		# 写入 README 内容
		with open(self.readme_file, 'w', encoding='utf-8') as f:
			 data = ''.join(lines)
			 print('完成!\n')
			 f.write(data)

if __name__ == '__main__':
	# 这里需要提供实际的 file_dir 和 format_config 参数
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
	
	merge(file_dir, format_config)
