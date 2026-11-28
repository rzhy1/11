#!/usr/bin/env python3

import os
import sys
import configparser
import urllib.request
import urllib.error

# --- 动态计算绝对路径 ---
UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(UTILS_DIR)

if UTILS_DIR not in sys.path:
    sys.path.insert(0, UTILS_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# -----------------------------

from sub_merge import merge
from sub_update import update

CONFIG_FILE = os.path.join(UTILS_DIR, 'config.ini')


def load_config(config_path):
    """一次性读取配置文件"""
    config = configparser.ConfigParser()
    if not os.path.exists(config_path):
        print(f"Warning: Config file not found at {config_path}")
        return config
    try:
        config.read(config_path, encoding='utf-8')
    except configparser.Error as e:
        print(f"Error: Failed to parse config file {config_path}: {e}")
        sys.exit(1)
    return config


def get_section(config, section):
    """安全获取 section，即使不存在也返回支持 .getboolean() 的空 SectionProxy"""
    if section in config:
        return config[section]
    return configparser.ConfigParser()['DEFAULT']


def get_file_dir_config(config_section):
    """将配置中的 *_dir / *_file 相对路径转换为基于项目根目录的规范路径"""
    file_dir = {}
    for key, value in config_section.items():
        if not isinstance(value, str):
            file_dir[key] = value
            continue
        cleaned = value.strip()
        if key.endswith(('_dir', '_file')):
            if not cleaned:
                continue
            file_dir[key] = os.path.normpath(os.path.join(PROJECT_ROOT, cleaned))
        else:
            file_dir[key] = cleaned
    return file_dir


def parse_format_config(config_section):
    """把 INI 字符串配置安全转为布尔/整数等原生类型，避免 bool('false') == True。"""
    parsed = {}
    for key, raw_value in config_section.items():
        if not isinstance(raw_value, str):
            parsed[key] = raw_value
            continue
        val = raw_value.strip()
        if val == '':
            continue
        lowered = val.lower()
        if lowered in ('true', 'yes', 'on'):
            parsed[key] = True
        elif lowered in ('false', 'no', 'off'):
            parsed[key] = False
        elif val.isdigit():
            parsed[key] = int(val)
        else:
            parsed[key] = val
    return parsed


def download_country_mmdb(save_path, timeout=15, chunk_size=65536):
    """带超时与原子替换的 Country.mmdb 下载，防止中断损坏已有文件"""
    url = 'https://raw.githubusercontent.com/Loyalsoldier/geoip/release/Country.mmdb'
    temp_path = save_path + '.tmp'
    try:
        print('Downloading Country.mmdb...')
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, 'status', 200) != 200:
                raise RuntimeError(f"Unexpected HTTP status: {resp.status}")
            with open(temp_path, 'wb') as out_file:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    out_file.write(chunk)
                out_file.flush()
                os.fsync(out_file.fileno())
        os.replace(temp_path, save_path)
        print('Success!\n')
        return True
    except (urllib.error.URLError, OSError, RuntimeError) as e:
        print(f'Failed to download Country.mmdb: {e}\n')
        return False
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


if __name__ == '__main__':
    config = load_config(CONFIG_FILE)
    common_config = get_section(config, 'common')
    subconverter_config = get_section(config, 'subconverter')

    file_dir = get_file_dir_config(common_config)
    update_enabled = common_config.getboolean('update_enabled', fallback=False)
    merge_enabled = common_config.getboolean('merge_enabled', fallback=False)

    # 仅在需要执行 update 且未显式关闭时下载 Country.mmdb
    if update_enabled and common_config.getboolean('download_mmdb', fallback=True):
        country_mmdb_path = os.path.join(UTILS_DIR, 'Country.mmdb')
        download_country_mmdb(country_mmdb_path)

    has_error = False

    if update_enabled:
        print('--- Running Subscription Update ---')
        try:
            update(file_dir)
        except Exception as e:
            has_error = True
            print(f'Subscription Update failed: {e}')

    if merge_enabled:
        required_keys = ('list_dir', 'list_file', 'merge_dir')
        missing = [k for k in required_keys if not file_dir.get(k)]
        if missing:
            print(f"Error: Missing required [common] config keys for merge: {', '.join(missing)}")
            sys.exit(1)

        print('--- Running Subscription Merge ---')
        format_config = parse_format_config(subconverter_config)
        merge_job = merge(file_dir, format_config)
        if not merge_job.merge_succeeded:
            has_error = True
            print('Subscription Merge did not succeed.')

    if has_error:
        print("\nTasks finished with errors.")
        sys.exit(1)

    print("\nAll tasks completed.")
