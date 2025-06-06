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
			item_type = item.get('type', 'subscription')

			# 打印“开始”信息，使用 end='' 让光标停在同一行
			print(f'Processing [ID: {item_id:0>2d}] {item_remarks}... ', end='', flush=True)
			
			content = ''
			file_content = ''
			success = False

			# 如果 URL 为空，直接标记失败
			if not item_url:
				status_message = 'Failed! URL is empty.'
			else:
				try:
					# 在“静音”模式下执行核心操作
					with suppress_stdout_stderr():
						if item_type == 'subscription':
							content = convert(item_url, 'url', {'keep_encode': True, 'raw_format': True, 'escape_special_chars': False})
						elif item_type == 'raw_text_url':
							response = requests.get(item_url, timeout=15)
							response.raise_for_status()
							content = response.text
						else:
							content = f"Error: Unknown subscription type '{item_type}'"

					# 操作完成后，分析结果
					if content and not content.startswith('Error:'):
						nodes = [line for line in content.splitlines() if line.strip()]
						if nodes:
							content_set.update(nodes)
							file_content = '\n'.join(nodes)
							status_message = f"Success! {len(nodes)} nodes found."
							success = True
						else:
							status_message = "Failed! No nodes found in the content."
							file_content = "No nodes found in the content."
					else:
						status_message = f"Failed! Reason: {content or 'No content returned'}"
						file_content = status_message
				
				except requests.exceptions.RequestException as e:
					status_message = f"Failed! Network error."
					file_content = str(e)
				except Exception as e:
					status_message = f"Failed! An unexpected error occurred."
					file_content = str(e)
			
			# 打印最终的“成功”或“失败”信息
			print(status_message)
			
			# 将获取到的内容或错误信息写入缓存文件
			if self.list_dir:
				with open(f'{list_dir}{item_id:0>2d}.txt', 'w', encoding='utf-8') as file:
					file.write(file_content)
			
			# 打印一个空行，用于分隔
			print()

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
