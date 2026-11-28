#!/usr/bin/env python3

import os
import re
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
    if input_type not in ('url', 'base64'):
        raise ValueError(f"Unsupported input_type: {input_type}")
    if not isinstance(target_format, str) or target_format.strip() not in ('clash', 'base64'):
        raise ValueError(f"Unsupported target_format: {target_format}")
    if not isinstance(input_content, str) or not input_content.strip():
        return ""

    config = config if isinstance(config, dict) else {}
    subconverter_dir = os.path.dirname(os.path.abspath(__file__))

    if sys.platform == 'win32':
        executable = 'subconverter-windows-amd64.exe'
    elif sys.platform.startswith('linux'):
        executable = 'subconverter-linux-amd64'
    else:
        print(f"  -> Unsupported platform for subconverter: {sys.platform}")
        return ""

    executable_path = os.path.join(subconverter_dir, executable)
    if not os.path.isfile(executable_path):
        print(f"  -> Subconverter executable not found: {executable_path}")
        return ""
    if sys.platform != 'win32' and not os.access(executable_path, os.X_OK):
        try:
            os.chmod(executable_path, os.stat(executable_path).st_mode | 0o111)
        except OSError as exc:
            print(f"  -> Subconverter is not executable ({executable_path}): {exc}")
            return ""

    try:
        max_output_bytes = int(config.get('max_output_bytes') or (20 * 1024 * 1024))
    except (TypeError, ValueError):
        max_output_bytes = 20 * 1024 * 1024

    def resolve_local_path(raw_path):
        cleaned = raw_path.strip()
        if '://' not in cleaned and '\n' not in cleaned and len(cleaned) < 4096:
            if os.path.exists(cleaned):
                return os.path.abspath(cleaned)
            candidate = os.path.join(subconverter_dir, cleaned)
            if os.path.exists(candidate):
                return os.path.abspath(candidate)
        return cleaned

    temp_output_file = None
    output = ""
    try:
        # 优先在 subconverter_dir 创建临时输出文件；若目录只读则回退到系统临时目录
        try:
            fd, temp_output_file = tempfile.mkstemp(
                prefix='subconv_', suffix='.tmp', dir=subconverter_dir
            )
        except OSError:
            fd, temp_output_file = tempfile.mkstemp(
                prefix='subconv_', suffix='.tmp'
            )
        os.close(fd)

        command = [
            executable_path,
            '--no-color',
            '--target', target_format.strip(),
            '--output', temp_output_file,
        ]

        if input_type == 'url':
            command.extend(['--url', resolve_local_path(input_content)])
            stdin_content = None
        else:
            # text=True 时 input 必须是 str，不能 encode 成 bytes
            stdin_content = input_content

        for flag, key in (('--rename', 'rename'), ('--include', 'include'), ('--exclude', 'exclude')):
            val = config.get(key)
            if val is None or val == '':
                continue
            if not isinstance(val, str):
                print(f"  -> Warning: Ignoring non-string subconverter option '{key}'.")
                continue
            command.extend([flag, val])

        cfg_path = config.get('config')
        if isinstance(cfg_path, str) and cfg_path.strip():
            command.extend(['--config', resolve_local_path(cfg_path)])
        elif cfg_path not in (None, ''):
            print("  -> Warning: Ignoring non-string subconverter option 'config'.")

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
            err_detail = (
                process.stderr.strip()
                or process.stdout.strip()
                or f"exit code {process.returncode}"
            )
            err_detail = re.sub(r'https?://\S+', '[REDACTED_URL]', err_detail)
            print(f"  -> Subconverter failed: {err_detail}")
            return ""

        if os.path.exists(temp_output_file):
            if os.path.getsize(temp_output_file) > max_output_bytes:
                print(f"  -> Subconverter output exceeds {max_output_bytes} bytes limit.")
                return ""
            with open(temp_output_file, 'r', encoding='utf-8', errors='replace') as f:
                output = f.read()
            if not output.strip():
                print("  -> Warning: Subconverter produced empty output.")
        else:
            print("  -> Warning: Output file is missing after subconverter finished.")

    except subprocess.TimeoutExpired:
        print("  -> Subconverter timed out processing the input.")
    except Exception as e:
        print(f"  -> An error occurred while running subconverter: {e}")
    finally:
        if temp_output_file and os.path.exists(temp_output_file):
            try:
                os.remove(temp_output_file)
            except OSError:
                pass

    return output


def base64_decode(content):
    if not isinstance(content, str):
        return ""
    try:
        cleaned = re.sub(r'\s+', '', content)
        if not cleaned:
            return ""
        cleaned = cleaned.replace('-', '+').replace('_', '/')
        missing_padding = len(cleaned) % 4
        if missing_padding:
            cleaned += '=' * (4 - missing_padding)
        return base64.b64decode(cleaned, validate=True).decode('utf-8', 'strict')
    except Exception:
        return ""
