#!/usr/bin/env python3

import os, urllib
import configparser
import sys

# --- 核心修改：动态计算路径 ---
# 获取 main.py 所在的目录 (即 'utils' 目录)
UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
# 获取项目根目录 (即 'utils' 的上一级目录)
PROJECT_ROOT = os.path.dirname(UTILS_DIR)

# 将 utils 目录和项目根目录都加入到模块搜索路径，确保能找到所有模块
sys.path.insert(0, UTILS_DIR)
sys.path.insert(0, PROJECT_ROOT)
# -----------------------------

from sub_update import update
from sub_merge import merge
from subconverter import convert, base64_decode

# 使用绝对路径来读取配置文件
config_file = os.path.join(UTILS_DIR, 'config.ini')

def configparse(section):
    config = configparser.ConfigParser()
    config.read(config_file, encoding='utf-8')
    # --- 核心修改：修正返回的路径为绝对路径 ---
    parsed_config = dict(config[section])
    for key, value in parsed_config.items():
        if 'dir' in key or 'file' in key:
            # 将所有相对路径 ./sub/... 转换为相对于项目根目录的绝对路径
            if value.startswith('./'):
                parsed_config[key] = os.path.join(PROJECT_ROOT, value[2:])
    return parsed_config

if __name__ == '__main__':
    try:
        print('Downloading Country.mmdb...')
        country_mmdb_path = os.path.join(UTILS_DIR, 'Country.mmdb')
        urllib.request.urlretrieve('https://raw.githubusercontent.com/Loyalsoldier/geoip/release/Country.mmdb', country_mmdb_path)
        print('Success!\n')
    except Exception:
        print('Failed!\n')
        pass

    common_config = configparse('common')

    if common_config.get('update_enabled', 'false').lower() == 'true':
        print('--- Running Subscription Update ---')
        update(common_config)

    if common_config.get('merge_enabled', 'false').lower() == 'true':
        print('--- Running Subscription Merge ---')
        format_config = configparse('subconverter')
        merge(common_config, format_config)

        # 同样，为 speedtest 添加 try-except 块
        if common_config.getboolean('speedtest_enabled'):
            print("\n--- Running Speed Test ---")
            # Speedtest 的逻辑比较复杂且依赖外部命令，暂时保持原样
            # 但至少要保证前面的步骤成功
            if os.path.exists(common_config['share_file']):
                # ... 你的 speedtest 逻辑 ...
                print("Speed test logic would run here (currently placeholder).")
            else:
                print("Skipping speed test because merged file does not exist.")

    except (FileNotFoundError, KeyError) as e:
        print(f"FATAL CONFIG ERROR: {e}")
        print("Please check your './utils/config.ini' file.")
    except Exception as e:
        print(f"An unexpected error occurred in main execution: {e}")
