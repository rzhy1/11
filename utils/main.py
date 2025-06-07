#!/usr/bin/env python3

import os, urllib
import configparser
import sys

# --- 核心修改：动态计算绝对路径 ---
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
from subconverter import base64_decode

# 使用绝对路径来读取配置文件
config_file = os.path.join(UTILS_DIR, 'config.ini')

def configparse(section):
    config = configparser.ConfigParser()
    config.read(config_file, encoding='utf-8')
    # --- 核心修改：将所有相对路径转换为绝对路径 ---
    parsed_config = dict(config[section])
    for key, value in parsed_config.items():
        # 检查是否是需要处理的路径字段
        if isinstance(value, str) and ('dir' in key or 'file' in key):
            # 将所有 ./sub/... 或 sub/... 形式的路径转换为基于项目根目录的绝对路径
            if value.startswith('./'):
                # 移除 './'
                value = value[2:]
            
            # 使用 os.path.join 来安全地拼接路径
            parsed_config[key] = os.path.join(PROJECT_ROOT, value)
            
    return parsed_config

if __name__ == '__main__':
    try:
        print('Downloading Country.mmdb...')
        country_mmdb_path = os.path.join(UTILS_DIR, 'Country.mmdb')
        urllib.request.urlretrieve('https://raw.githubusercontent.com/Loyalsoldier/geoip/release/Country.mmdb', country_mmdb_path)
        print('Success!\n')
    except Exception as e:
        print(f'Failed to download Country.mmdb: {e}\n')
        pass

    common_config = configparse('common')

    # 从 config.ini 读取的配置可能是字符串 'true' 或 'false'
    if common_config.get('update_enabled', 'false').lower() == 'true':
        print('--- Running Subscription Update ---')
        update(common_config)

    if common_config.get('merge_enabled', 'false').lower() == 'true':
        print('--- Running Subscription Merge ---')
        format_config = configparse('subconverter')
        # 将 common_config 和 format_config 合并，因为 merge 类需要它们
        # file_dir 参数现在由 common_config 提供
        merge(common_config, format_config)

    if configparse('common').getboolean('speedtest_enabled'):
        share_file = configparse('common')['share_file']
        share_file_clash = configparse('common')['share_file_clash']
        subscription = configparse('speedtest')['subscription']
        range = configparse('speedtest')['output_range']
        os.system(f'proxychains python3 ./utils/litespeedtest/speedtest.py --subscription \"../../{subscription}\" --range \"200,1100\" --path \"../../temp\"')

        east_asian_proxies = convert('../../temp','base64',{'deduplicate':False,'rename':'','include':'港|HK|Hong Kong|坡|SG|狮城|Singapore|日|JP|东京|大阪|埼玉|Japan|台|TW|新北|彰化|Taiwan|韩|KR|KOR|首尔|Korea','exclude':'','config':''})
        north_america_proxies = convert('../../temp','base64',{'deduplicate':False,'rename':'','include':'美|US|United States|加拿大|CA|Canada|波特兰|达拉斯|俄勒冈|凤凰城|费利蒙|硅谷|拉斯维加斯|洛杉矶|圣何塞|圣克拉拉|西雅图|芝加哥','exclude':'','config':''})
        other_country_proxies = convert('../../temp','base64',{'deduplicate':False,'rename':'','include':'','exclude':'US|HK|SG|JP|TW|KR|美|港|坡|日|台|韩|CA|加','config':''})
        area_proxies = {
            'east_asia': [east_asian_proxies, 45],
            'north_america': [north_america_proxies, 25],
            'other_area':[other_country_proxies, 25]
        }
        share_proxies = []
        for area in area_proxies.keys():
            with open('./temp', 'w', encoding='utf-8') as temp_file:
                temp_file.write(area_proxies[area][0])
            os.system(f'proxychains python3 ./utils/litespeedtest/speedtest.py --subscription \"../../temp\" --range \"{area_proxies[area][1]}\" --path \"../../temp\"')
            with open('./temp', 'r', encoding='utf-8') as temp_file:
                content = temp_file.read()
                share_proxies.append(base64_decode(content))
        with open('./temp', 'w', encoding='utf-8') as temp_file:
            temp_file.write(''.join(share_proxies))
        os.system(f'python3 ./utils/subconverter/subconvert.py --subscription \"../../temp\" --target \"base64\" --output \"../../{share_file}\"')
        os.system(f'python3 ./utils/subconverter/subconvert.py --subscription \"../../temp\" --target \"clash\" --output \"../../{share_file_clash}\"')
        os.remove('./temp')
