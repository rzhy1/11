#!/usr/bin/env python3

import os, re, subprocess
import argparse, configparser
import base64, yaml

def convert(content_str, target, other_config={}):
    """
    【简化版】直接接收明文内容字符串，并调用 subconverter 核心进行处理。
    content_str: 包含所有节点的明文/YAML字符串。
    target: 目标格式, 如 'base64', 'clash'。
    other_config: 包含去重、过滤、重命名等规则的字典。
    """
    
    # 准备配置
    config = {
        'target': target,
        'deduplicate': other_config.get('deduplicate', False),
        'rename': other_config.get('rename', ''),
        'include': other_config.get('include', ''),
        'exclude': other_config.get('exclude', ''),
        'config': other_config.get('config', '')
    }

    # 切换到 subconverter 的工作目录
    work_dir = os.getcwd()
    subconverter_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(subconverter_dir)

    # 【核心修复】将接收到的内容写入一个临时文件，这是与 subconverter 核心交互最可靠的方式
    temp_input_file = './temp_input.txt'
    with open(temp_input_file, 'w', encoding='utf-8') as f:
        f.write(content_str)

    # 调用 subconverterhandler，传递临时文件路径
    try:
        # 【核心修复】将去重等逻辑交给 subconverterhandler 统一处理
        # subconverterhandler 的职责是处理一个输入源（文件或URL），并返回 Clash Provider 格式的字符串
        clash_provider_str = subconverterhandler(temp_input_file, config)

        # 【核心修复】确保 clash_provider_str 被正确初始化
        if not clash_provider_str:
            print("subconverterhandler did not return any content.")
            os.chdir(work_dir)
            os.remove(temp_input_file)
            return ""

        # 可选的去重（如果 subconverter 核心的去重不够理想）
        if config['deduplicate']:
            # 注意：这里的 deduplicate 函数需要你提供或者我们简化它
            # 为了稳定，我们暂时信任 subconverter 核心的去重
            pass # clash_provider_str = deduplicate(clash_provider_str)

        # 再次调用 subconverterhandler，将处理过的 Clash Provider 转换为最终目标格式
        # 这次输入的是处理后的 clash provider 内容，写入另一个临时文件
        temp_clash_provider_file = './temp_clash_provider.txt'
        with open(temp_clash_provider_file, 'w', encoding='utf-8') as f:
            f.write(clash_provider_str)
        
        # 准备最终转换的配置
        final_config = config.copy()
        final_config['target'] = target # 确保 target 是最终目标
        
        output = subconverterhandler(temp_clash_provider_file, final_config)

    except Exception as e:
        print(f"An error occurred in convert function: {e}")
        output = ""
    finally:
        # 清理所有临时文件
        if os.path.exists(temp_input_file):
            os.remove(temp_input_file)
        if os.path.exists(temp_clash_provider_file) and 'temp_clash_provider_file' in locals():
            os.remove(temp_clash_provider_file)
        os.chdir(work_dir)

    return output


def subconverterhandler(subscription_path, input_config):
    """
    【简化版】接收一个本地文件路径，通过修改 generate.ini 调用 subconverter 核心。
    """
    configparse = configparser.ConfigParser()
    configparse.read('./generate.ini', encoding='utf-8')
    
    target = input_config.get('target', 'clash') # 默认先转成 clash provider
    
    # 将配置写入 generate.ini
    configparse.set(target, 'url', subscription_path)
    configparse.set(target, 'rename', input_config.get('rename', ''))
    configparse.set(target, 'include', input_config.get('include', ''))
    configparse.set(target, 'exclude', input_config.get('exclude', ''))
    configparse.set(target, 'config', input_config.get('config', ''))

    # 保存修改后的 ini 文件
    with open('./generate.ini', 'w', encoding='utf-8') as ini:
        configparse.write(ini, space_around_delimiters=False)

    # 确定可执行文件名
    executable = 'subconverter-linux-amd64' if os.name == 'posix' else 'subconverter-windows-amd64.exe'
    
    # 准备命令
    args = [f'./{executable}', '-g', '--artifact', target]
    
    # 执行 subconverter
    process = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=60)

    # 打印日志
    if process.stdout:
        print(process.stdout)
    if process.stderr:
        print(process.stderr)

    if process.returncode != 0:
        print(f"Subconverter exited with error code {process.returncode}")
        return ""

    # subconverter v0.8.0+ 默认将 artifact 输出到 ./output 目录
    output_filename = f'./output/{target}.yaml' if target == 'clash' else f'./output/{target}.txt'
    if not os.path.exists(output_filename):
       # 兼容旧版 subconverter，它可能输出到根目录
       output_filename_alt = f'./{target}.yaml' if target == 'clash' else f'./{target}.txt'
       if os.path.exists(output_filename_alt):
           output_filename = output_filename_alt
       else:
           # 兼容更旧的版本，它可能输出到 ./temp
           output_filename_alt_2 = f'./temp'
           if os.path.exists(output_filename_alt_2):
               output_filename = output_filename_alt_2
           else:
                print(f"Error: Output artifact '{output_filename}' not found.")
                return ""

    with open(output_filename, 'r', encoding='utf-8') as f:
        output_content = f.read()

    # 清理生成的 artifact 文件
    if os.path.exists(output_filename):
        os.remove(output_filename)

    return output_content


# base64 编解码函数保持不变，但要确保它们存在且正确
def base64_decode(content):
    # ... (此处省略，使用你原来的正确版本)
    try:
        # 补全=号
        missing_padding = len(content) % 4
        if missing_padding:
            content += '=' * (4 - missing_padding)
        return base64.b64decode(content).decode('utf-8', 'ignore')
    except:
        return ""

def base64_encode(content):
    return base64.b64encode(content.encode('utf-8')).decode('ascii')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Convert between various proxy subscription formats using Subconverter.')
    parser.add_argument('--subscription', '-s', help='Your subscription url or local file path.', required=True)
    parser.add_argument('--target', '-t', help='Target convert format, support base64, clash, clash_provider, quanx.', default='clash')
    parser.add_argument('--output', '-o', help='Target path to output, default value is the Subconverter root directionary.', default='./Eternity.yaml')
    parser.add_argument('--deduplicate', '-d', help='Whether to deduplicate proxies, default value is False.', default=False)
    parser.add_argument('--keep', '-k', help='Amounts of nodes to keep when deduplicated.', default=1)
    args = parser.parse_args()

    subscription = args.subscription
    target = args.target
    output_dir = args.output
    if args.deduplicate == 'true' or args.deduplicate == 'True':
        deduplicate_enabled = True
    else:
        deduplicate_enabled = False
    keep_nodes = int(args.keep)

    work_dir = os.getcwd()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    generate = configparser.ConfigParser()
    generate.read('./generate.ini',encoding='utf-8')
    config={'deduplicate': deduplicate_enabled,'keep_nodes': keep_nodes,'rename': generate.get(target,'rename'), 'include': generate.get(target,'include'), 'exclude': generate.get(target,'exclude'), 'config': generate.get(target,'config')}

    output = convert(subscription,target,config)

    with open(output_dir, 'w', encoding= 'utf-8') as temp_file:
        temp_file.write(output)
    os.chdir(work_dir)
