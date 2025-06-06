#!/usr/bin/env python3

import os
import configparser
import urllib.request  # 明确导入，避免潜在问题

# --- 核心修改：使用脚本的绝对路径来定位配置文件 ---
# __file__ 是当前脚本 (main.py) 的路径
# os.path.dirname(__file__) 是 main.py 所在的目录 (即 'utils/')
# os.path.abspath(...) 将其转换为绝对路径
UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(UTILS_DIR, 'config.ini')
# 这样无论从哪里运行 main.py, CONFIG_FILE 的路径总是正确的

def configparse(section):
    # 确保文件存在
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"Config file not found at: {CONFIG_FILE}")
        
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE, encoding='utf-8')
    
    # 检查 section 是否存在，避免 KeyError
    if section not in config:
        raise KeyError(f"Section '[{section}]' not found in {CONFIG_FILE}")
        
    return config[section]

if __name__ == '__main__':
    try:
        print('Downloading Country.mmdb...')
        country_mmdb_path = os.path.join(UTILS_DIR, 'Country.mmdb')
        urllib.request.urlretrieve('https://raw.githubusercontent.com/Loyalsoldier/geoip/release/Country.mmdb', country_mmdb_path)
        print('Success!\n')
    except Exception as e:
        print(f'Failed to download Country.mmdb: {e}\n')
        pass

    # 懒加载 merge 和 update, 仅在需要时导入
    try:
        common_config = configparse('common')
        
        if common_config.getboolean('update_enabled'):
            from sub_update import update
            print("--- Running Subscription Update ---")
            update(common_config)

        if common_config.getboolean('merge_enabled'):
            from sub_merge import merge
            print("\n--- Running Subscription Merge ---")
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
