#!/usr/bin/env python3

import json, os, base64, time
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

	def sub_merge(self):
		content_set = set()
		for url in self.url_list:
			url_content = url['url']
			# 区分 Base64 和明文协议
			if any(
				url_content.startswith(proto) and '=' in url_content
				for proto in ('vmess://', 'ss://', 'ssr://')
			):
				content = convert(url_content, 'url', {'keep_encode': True, 'raw_format': True})
			else:
				content = url_content  # 直接保留明文协议
		
			if content:
				content_set.update(content.splitlines())
				print(f'Writing content of {url["remarks"]} to {url["id"]:0>2d}.txt')
			else:
				content = 'No nodes were found in url.'
				print(f'Writing error of {url["remarks"]} to {url["id"]:0>2d}.txt')
		
			if self.list_dir:
				with open(f'{self.list_dir}{url["id"]:0>2d}.txt', 'w', encoding='utf-8') as file:
					file.write(content)

		# 合并所有节点
		merged_content = '\n'.join(content_set)
		merge_path = f'{self.merge_dir}/sub_merge_base64.txt'
	
		# 根据配置决定是否输出 Base64
		if self.format_config.get('output_base64', True):
			try:
				merged_content = base64.b64encode(merged_content.encode('utf-8')).decode('utf-8')
			except:
				print("Warning: Output kept as plaintext due to Base64 encode error.")
	
		with open(merge_path, 'w', encoding='utf-8') as file:
			file.write(merged_content)
		print(f'Done! Output merged nodes to {merge_path}.')

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
