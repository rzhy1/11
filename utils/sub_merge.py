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

		self.url_list = self.read_list()
		self.sub_merge()
		if self.readme_file != '':
			self.readme_update()

	def read_list(self):
		with open(self.list_file, 'r', encoding='utf-8') as f:
			raw_list = json.load(f)
		return [item for item in raw_list if item['enabled']]

	def sub_merge(self):
		url_list = self.url_list
		list_dir = self.list_dir
		merge_dir = self.merge_dir

		# 清空目录
		for dirpath, dirnames, filenames in os.walk(list_dir):
			for filename in filenames:
				os.remove(os.path.join(dirpath, filename))

		content_set = set()
	
		for url in url_list:
			url_content = url['url']
			print(f'Processing {url["remarks"]}...')  # 添加处理提示
		
			# 直接处理所有以协议开头的节点
			if any(url_content.startswith(proto) for proto in ['vmess://', 'vless://', 'trojan://', 'ss://']):
				content = url_content  # 保留原始协议格式
			else:
				# 其他情况使用convert转换
				content = convert(url_content, 'url', {
					'keep_encode': True,
					'raw_format': True,
					'escape_special_chars': False
				})
		
			if content:
				# 处理多行内容
				nodes = content.splitlines()
				for node in nodes:
					if any(node.startswith(proto) for proto in ['vmess://', 'vless://', 'trojan://', 'ss://']):
						content_set.add(node)
			
				print(f'Writing content of {url["remarks"]} to {url["id"]:0>2d}.txt')
			else:
				print(f'Writing error of {url["remarks"]} to {url["id"]:0>2d}.txt')
				content = 'No nodes were found in url.'
		
			if self.list_dir:
				with open(f'{list_dir}{url["id"]:0>2d}.txt', 'w', encoding='utf-8') as file:
					file.write(content)

		print('Merging nodes...')
		# 合并时保留原始协议格式
		content = '\n'.join(content_set)
	
		# 只有当内容不是base64时才进行编码
		if not content.startswith(('vmess://', 'vless://', 'trojan://', 'ss://')):
			content = convert(content, 'base64', self.format_config)
	
		merge_path = f'{merge_dir}/sub_merge_base64.txt'
		with open(merge_path, 'wb') as file:
			file.write(content.encode('utf-8'))
	
		print(f'Done! Output merged nodes to {merge_path}.')
		print(f'Total unique nodes: {len(content_set)}')

	def readme_update(self):
		print('Updating README...')
		with open(self.readme_file, 'r', encoding='utf-8') as f:
			lines = f.readlines()
			f.close()

		for index in range(len(lines)):
			if lines[index] == '### 所有节点\n':
				lines.pop(index+1)

				with open(f'{self.merge_dir}sub_merge_base64.txt', 'r', encoding='utf-8') as f:
					proxies_base64 = f.read()
					proxies = base64_decode(proxies_base64)
					proxies = proxies.split('\n')
					top_amount = len(proxies) - 1
					f.close()
				lines.insert(index+1, f'合并节点总数: `{top_amount}`\n')
				break
		
		with open(self.readme_file, 'w', encoding='utf-8') as f:
			 data = ''.join(lines)
			 print('完成!\n')
			 f.write(data)

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
	
	merge(file_dir, format_config)
