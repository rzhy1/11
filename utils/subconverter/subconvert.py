#!/usr/bin/env python3

import os, re, subprocess, configparser, base64

def convert(content_str, target, other_config={}):
    """
    【最终版】接收明文内容字符串，写入临时文件，然后调用 subconverter 核心进行处理。
    """
    work_dir = os.getcwd()
    subconverter_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(subconverter_dir)

    temp_input_file = './temp_input.txt'
    with open(temp_input_file, 'w', encoding='utf-8') as f:
        f.write(content_str)
        
    output = ""
    try:
        # 【核心修复】将 output_path 添加到配置中
        # 我们约定一个固定的临时输出文件名，handler 执行完后会读取并删除它
        temp_output_path = f"./{target}_artifact.tmp"
        
        config = {
            'target': target,
            'url': temp_input_file,
            'output': temp_output_path, # <-- 在这里明确指定输出路径
            'rename': other_config.get('rename', ''),
            'include': other_config.get('include', ''),
            'exclude': other_config.get('exclude', ''),
            'config': other_config.get('config', '')
        }
        
        # 将所有配置打包，直接调用一次 subconverterhandler
        output = subconverterhandler(config)
    except Exception as e:
        print(f"An error occurred in convert function: {e}")
    finally:
        # 无论成功与否，都清理输入文件
        if os.path.exists(temp_input_file):
            os.remove(temp_input_file)
        os.chdir(work_dir)

    return output


def subconverterhandler(input_config):
    """
    【最终版】接收一个包含所有参数的配置字典，修改 generate.ini 并调用 subconverter 核心。
    """
    configparse = configparser.ConfigParser()
    configparse.read('./generate.ini', encoding='utf-8')
    
    target = input_config.get('target', 'clash')
    
    if not configparse.has_section(target):
        # 如果 section 不存在，动态创建它
        configparse.add_section(target)

    # 将所有配置写入 ini 文件
    for key, value in input_config.items():
        if key != 'target':
             configparse.set(target, key, str(value)) # 确保值为字符串
    
    with open('./generate.ini', 'w', encoding='utf-8') as ini:
        configparse.write(ini, space_around_delimiters=False)

    executable = 'subconverter-linux-amd64' if os.name == 'posix' else 'subconverter-windows-amd64.exe'
    args = [f'./{executable}', '-g', '--artifact', target]
    
    # 打印将要执行的命令，便于调试
    print(f"  -> Executing subconverter command: {' '.join(args)}")
    
    process = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=60)

    # 打印日志
    if process.stderr:
        print("  -> Subconverter log (stderr):")
        print(process.stderr)

    if process.returncode != 0:
        print(f"  -> Subconverter exited with error code {process.returncode}")
        return ""

    # 从我们指定的 output 路径读取结果
    output_path = input_config.get('output')
    if not output_path or not os.path.exists(output_path):
        print(f"  -> Error: Expected output file '{output_path}' not found.")
        return ""

    with open(output_path, 'r', encoding='utf-8', errors='ignore') as f:
        output_content = f.read()

    # 清理输出文件
    if os.path.exists(output_path):
        os.remove(output_path)

    return output_content

def base64_decode(content):
    try:
        content = content.strip()
        missing_padding = len(content) % 4
        if missing_padding: content += '=' * (4 - missing_padding)
        return base64.b64decode(content).decode('utf-8', 'ignore')
    except:
        return ""
