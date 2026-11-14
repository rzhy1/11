import os
import sys
import subprocess
import base64
import tempfile


def convert(input_content, input_type, target_format, config=None):
    """
    接收输入内容和类型，调用 subconverter 核心，并返回输出内容。
    - input_content: URL, 本地文件路径, 或 Base64 编码的字符串
    - input_type: 'url' 或 'base64'
    - target_format: 'clash' 或 'base64'
    - config: 包含过滤、重命名规则的字典
    """
    config = config or {}
    subconverter_dir = os.path.dirname(os.path.abspath(__file__))

    executable = (
        'subconverter-windows-amd64.exe'
        if sys.platform == 'win32'
        else 'subconverter-linux-amd64'
    )
    executable_path = os.path.join(subconverter_dir, executable)

    # 生成唯一的临时输出文件，避免并发冲突
    fd, temp_output_file = tempfile.mkstemp(
        prefix='subconv_', suffix='.tmp', dir=subconverter_dir
    )
    os.close(fd)

    output = ""
    try:
        command = [
            executable_path,
            '--no-color',
            '--target', target_format,
            '--output', temp_output_file,
        ]

        if input_type == 'url':
            # 如果是存在的本地文件，转为绝对路径，避免受 cwd 影响
            if os.path.exists(input_content):
                input_content = os.path.abspath(input_content)
            command.extend(['--url', input_content])
            stdin_content = None
        elif input_type == 'base64':
            # text=True 时 input 必须是 str，不能 encode 成 bytes
            stdin_content = input_content
        else:
            raise ValueError(f"Unsupported input_type: {input_type}")

        if config.get('rename'):
            command.extend(['--rename', config['rename']])
        if config.get('include'):
            command.extend(['--include', config['include']])
        if config.get('exclude'):
            command.extend(['--exclude', config['exclude']])
        if config.get('config'):
            cfg_path = config['config']
            if os.path.exists(cfg_path):
                cfg_path = os.path.abspath(cfg_path)
            command.extend(['--config', cfg_path])

        process = subprocess.run(
            command,
            cwd=subconverter_dir,
            input=stdin_content,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=120,
        )

        if process.returncode != 0:
            print(f"  -> Subconverter failed. Stderr: {process.stderr.strip()}")
            return ""

        if os.path.exists(temp_output_file):
            with open(temp_output_file, 'r', encoding='utf-8', errors='ignore') as f:
                output = f.read()
        else:
            print("  -> Warning: Output file was not created by subconverter.")

    except subprocess.TimeoutExpired:
        print("  -> Subconverter timed out processing the input.")
    except Exception as e:
        print(f"  -> An error occurred while running subconverter: {e}")
    finally:
        if os.path.exists(temp_output_file):
            try:
                os.remove(temp_output_file)
            except OSError:
                pass

    return output


def base64_decode(content):
    try:
        content = content.strip().replace('-', '+').replace('_', '/')
        missing_padding = len(content) % 4
        if missing_padding:
            content += '=' * (4 - missing_padding)
        return base64.b64decode(content).decode('utf-8', 'ignore')
    except Exception:
        return ""
