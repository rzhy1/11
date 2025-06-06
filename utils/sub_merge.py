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
				for filename in filenames:
					os.remove(os.path.join(dirpath, filename))
		else:
			os.makedirs(list_dir)

		content_set = set()
		for item in url_list:
			item_url = item.get('url')
			item_id = item.get('id')
			item_remarks = item.get('remarks')
			
			# 如果 URL 为空，直接跳过并打印信息
			if not item_url:
				print(f"Skipping [ID: {item_id:0>2d}] {item_remarks} because URL is empty.\n")
				continue

			# 这是核心改动：我们先执行 convert，让它打印自己的日志
			content = convert(item_url, 'url', {'keep_encode': True, 'raw_format': True, 'escape_special_chars': False})

			# 然后，我们再根据 convert 的结果，构建并打印我们自己的最终信息
			if content:
				# 清理并统计有效节点
				nodes = [line for line in content.splitlines() if line.strip()]
				if nodes:
					content_set.update(nodes)
					# 在我们自己的 print 语句末尾加上 '\n' 来主动换行
					print(f"Writing content of {item_remarks} to {item_id:0>2d}.txt ({len(nodes)} nodes found)\n")
					# 准备写入文件的内容
					file_content = '\n'.join(nodes)
				else:
					print(f"Writing error of {item_remarks} to {item_id:0>2d}.txt (Source is empty)\n")
					file_content = 'No nodes were found in url.'
			else:
				print(f"Writing error of {item_remarks} to {item_id:0>2d}.txt (Failed to convert)\n")
				file_content = 'No nodes were found in url.'

			# 最后，写入文件
			if self.list_dir:
				with open(f'{list_dir}{item_id:0>2d}.txt', 'w', encoding='utf-8') as file:
					file.write(file_content)

		# --- 后续的合并逻辑保持不变 ---
		if not content_set:
			print('Merging failed: No nodes collected from any source.')
			return

		print(f'Merging {len(content_set)} unique nodes...')
		content = '\n'.join(content_set)
		final_content = convert(content, 'base64', self.format_config)
		merge_path_final = f'{merge_dir}sub_merge_base64.txt'
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
