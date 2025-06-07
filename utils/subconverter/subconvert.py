#!/usr/bin/env python3

import os, subprocess, base64

def convert(content_str, target, other_config={}):
    """
    【最终决定版】直接通过命令行参数与 subconverter 核心交互，不再修改 INI 文件。
    """
    work_dir = os.getcwd()
    subconverter_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(subconverter_dir)

    temp_input_file = './temp_input.txt'
    temp_output_file = './temp_output.txt' # 定义一个临时的输出文件名

    with open(temp_input_file, 'w', encoding='utf-8') as f:
        f.write(content_str)
        
    output = ""
    try:
        # 【核心修复】构建完整的命令行参数列表
        executable = 'subconverter-linux-amd64' if os.name == 'posix' else 'subconverter-windows-amd64.exe'
        command = [
            f'./{executable}',
            '--no-color', # 禁用颜色输出，让日志更干净
            '--target', target,
            '--url', temp_input_file, # 输入文件
            '--output', temp_output_file # 输出文件
        ]

        # 动态添加其他配置参数
        if other_config.get('deduplicate') is False: # 注意检查 False
            command.append('--no-deduplicate')
        if other_config.get('rename'):
            command.extend(['--rename', other_config['rename']])
        if other_config.get('include'):
            command.extend(['--include', other_config['include']])
        if other_config.get('exclude'):
            command.extend(['--exclude', other_config['exclude']])
        if other_config.get('config'):
            command.extend(['--config', other_config['config']])
        
        print(f"  -> Executing subconverter command: {' '.join(command)}")
        
        process = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=60)

        if process.returncode != 0:
            print("  -> Subconverter process exited with an error.")
            print("  -> Stderr:", process.stderr)
            return ""

        if not os.path.exists(temp_output_file):
            print("  -> Error: Subconverter ran successfully, but the output file was not created.")
            print("  -> Stdout:", process.stdout)
            print("  -> Stderr:", process.stderr)
            return ""

        with open(temp_output_file, 'r', encoding='utf-8', errors='ignore') as f:
            output = f.read()

    except Exception as e:
        print(f"An error occurred while running subconverter: {e}")
    finally:
        # 清理临时文件
        if os.path.exists(temp_input_file):
            os.remove(temp_input_file)
        if os.path.exists(temp_output_file):
            os.remove(temp_output_file)
        os.chdir(work_dir)

    return output

def base64_decode(content):
    try:
        content = content.strip()
        missing_padding = len(content) % 4
        if missing_padding: content += '=' * (4 - missing_padding)
        return base64.b64decode(content).decode('utf-8', 'ignore')
    except:
        return ""
