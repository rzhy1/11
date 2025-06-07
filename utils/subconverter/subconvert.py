# utils/subconverter/subconvert.py 最终高效版

import os, subprocess, base64

def convert(input_content, input_type, target_format, config={}):
    """
    【高效版】接收输入内容和类型，调用 subconverter 核心，并返回输出内容。
    - input_content: URL, 本地文件路径, 或 Base64 编码的字符串
    - input_type: 'url' 或 'base64'
    - target_format: 'clash' 或 'base64'
    - config: 包含过滤、重命名规则的字典
    """
    work_dir = os.getcwd()
    subconverter_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(subconverter_dir)

    # 准备一个临时的输出文件
    temp_output_file = './temp_output_artifact.tmp'
    
    output = ""
    try:
        executable = 'subconverter-linux-amd64' if os.name == 'posix' else 'subconverter-windows-amd64.exe'
        command = [
            f'./{executable}',
            '--no-color',
            '--target', target_format,
            '--output', temp_output_file
        ]

        # 根据输入类型构建命令
        # 注意：对于 'url' 类型，input_content 就是 URL 或文件路径
        # 对于 'base64' 类型，subconverter 期望从 stdin 读取
        if input_type == 'url':
            command.extend(['--url', input_content])
            stdin_content = None
        elif input_type == 'base64':
            stdin_content = input_content.encode('utf-8')
        else:
            raise ValueError(f"Unsupported input_type: {input_type}")

        # 添加其他配置
        if config.get('rename'): command.extend(['--rename', config['rename']])
        if config.get('include'): command.extend(['--include', config['include']])
        if config.get('exclude'): command.extend(['--exclude', config['exclude']])
        if config.get('config'): command.extend(['--config', config['config']])
        
        process = subprocess.run(
            command,
            input=stdin_content,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=120 # 单次转换超时2分钟，足够了
        )

        if process.returncode != 0:
            print(f"  -> Subconverter failed for input. Stderr: {process.stderr.strip()}")
            return ""

        if os.path.exists(temp_output_file):
            with open(temp_output_file, 'r', encoding='utf-8', errors='ignore') as f:
                output = f.read()
            os.remove(temp_output_file)
        else:
             print(f"  -> Warning: Output file was not created by subconverter.")

    except subprocess.TimeoutExpired:
        print(f"  -> Subconverter timed out processing the input.")
    except Exception as e:
        print(f"  -> An error occurred while running subconverter: {e}")
    finally:
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
