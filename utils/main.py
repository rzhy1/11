#!/usr/bin/env python3

import os, urllib
import configparser
import sys

# --- 动态计算绝对路径 ---
# 获取 main.py 所在的目录 (即 'utils' 目录)
UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
# 获取项目根目录 (即 'utils' 的上一级目录)
PROJECT_ROOT = os.path.dirname(UTILS_DIR)

# 将 utils 目录和项目根目录都加入到模块搜索路径，以防万一
sys.path.insert(0, UTILS_DIR)
sys.path.insert(0, PROJECT_ROOT)
# -----------------------------

# 导入我们自己的模块
from sub_merge import merge
from sub_update import update

# 使用绝对路径来读取配置文件
config_file = os.path.join(UTILS_DIR, 'config.ini')

def configparse(section):
    """
    读取指定 section 的配置，并返回一个 configparser 的 SectionProxy 对象。
    """
    config = configparser.ConfigParser()
    config.read(config_file, encoding='utf-8')
    # 检查 section 是否存在，避免 KeyErorr
    if section in config:
        return config[section]
    # 如果 section 不存在，返回一个空字典，让 .getboolean 等方法可以安全地使用 fallback
    return {}

def get_file_dir_config(config_section):
    """
    专门用于处理路径，将 config_section 转换为一个修复了路径的字典。
    """
    file_dir = {}
    for key, value in config_section.items():
        # 检查是否是需要处理的路径字段
        if isinstance(value, str) and ('dir' in key or 'file' in key):
            if value.startswith('./'):
                value = value[2:]
            file_dir[key] = os.path.join(PROJECT_ROOT, value)
        else:
            file_dir[key] = value
    return file_dir


if __name__ == '__main__':
    try:
        print('Downloading Country.mmdb...')
        country_mmdb_path = os.path.join(UTILS_DIR, 'Country.mmdb')
        urllib.request.urlretrieve('https://raw.githubusercontent.com/Loyalsoldier/geoip/release/Country.mmdb', country_mmdb_path)
        print('Success!\n')
    except Exception as e:
        print(f'Failed to download Country.mmdb: {e}\n')
        pass

    # 一次性读取所有需要的配置 sections
    common_config = configparse('common')
    subconverter_config = configparse('subconverter')

    # 使用 getboolean 方法，并提供 fallback 默认值
    if common_config.getboolean('update_enabled', fallback=False):
        print('--- Running Subscription Update ---')
        # 传递修复了路径的配置字典
        update(get_file_dir_config(common_config))

    if common_config.getboolean('merge_enabled', fallback=False):
        print('--- Running Subscription Merge ---')
        # 准备好传给 merge 类的参数
        file_dir = get_file_dir_config(common_config)
        format_config = dict(subconverter_config)
        merge(file_dir, format_config)

    # --- 所有与测速相关的代码已被完全删除 ---

    print("\nAll tasks completed.")
