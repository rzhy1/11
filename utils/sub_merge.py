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

		# 清理旧的单个订阅缓存文件
		if os.path.exists(list_dir):
			for dirpath, dirnames, filenames in os.walk(list_dir):
				for filename in filenames:
					os.remove(os.path.join(dirpath, filename))
		else:
			os.makedirs(list_dir)

		content_set = set()
		for item in url_list:
			content = ''
			item_url = item.get('url')
			item_id = item.get('id')
			item_remarks = item.get('remarks')
			
			# 如果 URL 为空或无效，则跳过
			if not item_url:
				print(f'Skipping {item_remarks} (ID: {item_id}) due to empty URL.')
				continue

			# 根据 'type' 字段决定处理方式，默认为 'subscription'
			item_type = item.get('type', 'subscription')
			print(f'Processing [ID: {item_id}] {item_remarks} with type [{item_type}]...')

			try:
				# 策略1：处理标准 Base64 订阅链接
				if item_type == 'subscription':
					content = convert(item_url, 'url', {'keep_encode': True, 'raw_format': True, 'escape_special_chars': False})
				
				# 策略2：处理纯文本节点列表链接
				elif item_type == 'raw_text_url':
					# 我们自己下载内容，然后直接使用
					response = requests.get(item_url, timeout=10)
					response.raise_for_status() # 如果下载失败 (如 404), 会抛出异常
					content = response.text
				
				# 如果有更多类型，可以在这里添加 elif
				
				else:
					content = f"Error: Unknown subscription type '{item_type}'"
					print(content)

			except requests.exceptions.RequestException as e:
				content = f'Error downloading URL: {e}'
				print(f'Failed for {item_remarks}: {content}')
			except Exception as e:
				# 捕获 convert 函数可能抛出的其他错误
				content = f'Error processing subscription: {e}'
				print(f'Failed for {item_remarks}: {content}')

			if content and not content.startswith('Error:'):
				# splitlines() 可以很好地处理不同操作系统的换行符
				nodes = [line for line in content.splitlines() if line.strip()]
				content_set.update(nodes)
				print(f'Writing content of {item_remarks} to {item_id:0>2d}.txt ({len(nodes)} nodes found)\n')
				print()
				# 将干净的节点内容写入缓存，而不是原始下载内容
				content_for_file = '\n'.join(nodes)
			else:
				# 如果 content 为空或者包含错误信息
				if not content:
					content_for_file = 'No nodes were found in url.'
				else:
					content_for_file = content
				print(f'Writing error of {item_remarks} to {item_id:0>2d}.txt')

			if self.list_dir:
				with open(f'{list_dir}{item_id:0>2d}.txt', 'w', encoding='utf-8') as file:
					file.write(content_for_file)

		if not content_set:
			print('Merging failed: No nodes collected from any source.')
			return

		print(f'\nMerging {len(content_set)} unique nodes...')
		content = '\n'.join(content_set)
		# 最终合并转换
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
