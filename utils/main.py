#!/usr/bin/env python3

import os
import sys
import configparser
import urllib.request

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
    config.read(config_path, encoding='utf-8')
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
        if isinstance(value, str) and key.endswith(('_dir', '_file')) and value.strip():
            file_dir[key] = os.path.normpath(os.path.join(PROJECT_ROOT, value.strip()))
        else:
            file_dir[key] = value
    return file_dir


def download_country_mmdb(save_path, timeout=15):
    """带超时控制的 Country.mmdb 下载（若 sub_update 不用此文件可移除调用）"""
    url = 'https://raw.githubusercontent.com/Loyalsoldier/geoip/release/Country.mmdb'
    try:
        print('Downloading Country.mmdb...')
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(save_path, 'wb') as out_file:
            out_file.write(resp.read())
        print('Success!\n')
    except Exception as e:
        print(f'Failed to download Country.mmdb: {e}\n')


if __name__ == '__main__':
    # 如果 sub_update 不需要 Country.mmdb，可以直接注释掉下面这两行
    country_mmdb_path = os.path.join(UTILS_DIR, 'Country.mmdb')
    download_country_mmdb(country_mmdb_path)

    config = load_config(CONFIG_FILE)
    common_config = get_section(config, 'common')
    subconverter_config = get_section(config, 'subconverter')

    file_dir = get_file_dir_config(common_config)

    if common_config.getboolean('update_enabled', fallback=False):
        print('--- Running Subscription Update ---')
        update(file_dir)

    if common_config.getboolean('merge_enabled', fallback=False):
        print('--- Running Subscription Merge ---')
        format_config = dict(subconverter_config)
        merge(file_dir, format_config)

    print("\nAll tasks completed.")
