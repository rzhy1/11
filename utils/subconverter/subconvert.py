#!/usr/bin/env python3

import os, re, subprocess, configparser, base64

def convert(content_str, target, other_config={}):
    """
    【最终简化版】接收明文内容字符串，写入临时文件，然后调用 subconverter 核心进行处理。
    """
    work_dir = os.getcwd()
    subconverter_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(subconverter_dir)

    temp_input_file = './temp_input.txt'
    with open(temp_input_file, 'w', encoding='utf-8') as f:
        f.write(content_str)
        
    output = ""
    try:
        # 将所有配置打包，直接调用一次 subconverterhandler
        config = {
            'target': target,
            'url': temp_input_file, # 直接将文件路径作为 url
            'rename': other_config.get('rename', ''),
            'include': other_config.get('include', ''),
            'exclude': other_config.get('exclude', ''),
            'config': other_config.get('config', '')
        }
        output = subconverterhandler(config)
    except Exception as e:
        print(f"An error occurred in convert function: {e}")
    finally:
        if os.path.exists(temp_input_file):
            os.remove(temp_input_file)
        os.chdir(work_dir)

    return output


def subconverterhandler(input_config):
    """
    【最终简化版】接收一个包含所有参数的配置字典，修改 generate.ini 并调用 subconverter 核心。
    """
    configparse = configparser.ConfigParser()
    configparse.read('./generate.ini', encoding='utf-8')
    
    target = input_config.get('target', 'clash')
    
    # 检查 target section 是否存在
    if not configparse.has_section(target):
        raise configparser.NoSectionError(target)

    # 将配置写入 ini
    for key, value in input_config.items():
        if key != 'target':
             configparse.set(target, key, value)
    
    with open('./generate.ini', 'w', encoding='utf-8') as ini:
        configparse.write(ini, space_around_delimiters=False)

    executable = 'subconverter-linux-amd64' if os.name == 'posix' else 'subconverter-windows-amd64.exe'
    args = [f'./{executable}', '-g', '--artifact', target]
    
    process = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=60)

    # 打印日志
    if process.stdout:
        print(process.stdout)
    if process.stderr:
        print(process.stderr)

    if process.returncode != 0:
        print(f"Subconverter exited with error code {process.returncode}")
        return ""

    # 从 ./output 或其他兼容路径读取结果
    output_filename = f'./output/{target}.txt' if target in ['base64', 'url'] else f'./output/{target}.yaml'
    if not os.path.exists(output_filename):
        output_filename = f'./{target}.txt' if target in ['base64', 'url'] else f'./{target}.yaml'
        if not os.path.exists(output_filename):
             output_filename = './temp' # 兼容最旧的版本
             if not os.path.exists(output_filename):
                 print(f"Error: Output artifact for target '{target}' not found.")
                 return ""

    with open(output_filename, 'r', encoding='utf-8', errors='ignore') as f:
        output_content = f.read()

    if os.path.exists(output_filename):
        os.remove(output_filename)

    return output_content

def base64_decode(content):
    try:
        missing_padding = len(content) % 4
        if missing_padding: content += '=' * (4 - missing_padding)
        return base64.b64decode(content).decode('utf-8', 'ignore')
    except:
        return ""
