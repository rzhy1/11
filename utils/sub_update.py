#!/usr/bin/env python3

from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import json, re
import requests
import yaml


class update():
    def __init__(self,config={'list_file': './sub/sub_list.json'}):
        self.list_file = config['list_file']
        with open(self.list_file, 'r', encoding='utf-8') as f: # 载入订阅链接
            raw_list = json.load(f)
            self.raw_list = raw_list
        self.update_main()

    def url_updated(self,url): # 判断远程链接是否已经更新
        s = requests.Session()
        try:
            resp = s.get(url, timeout=2)
            status = resp.status_code
        except Exception:
            status = 404
        if status == 200:
            url_updated = True
        else:
            url_updated = False
        return url_updated

    def update_main(self):
        for sub in self.raw_list:
            id = sub['id']
            current_url = sub['url']
            try:
                if sub['update_method'] != 'auto' and sub['enabled'] == True:
                    print(f'Finding available update for ID{id}')
                    if sub['update_method'] == 'change_date':
                        new_url = self.change_date(id,current_url)
                        if new_url == current_url:
                            print(f'No available update for ID{id}\n')
                        else:
                            sub['url'] = new_url
                            print(f'ID{id} url updated to {new_url}\n')
                    elif sub['update_method'] == 'page_release':
                        new_url = self.find_link(id,current_url)
                        if new_url == current_url:
                            print(f'No available update for ID{id}\n')
                        else:
                            sub['url'] = new_url
                            print(f'ID{id} url updated to {new_url}\n')
            except KeyError:
                print(f'{id} Url not changed! Please define update method.')
            
            updated_list = json.dumps(self.raw_list, sort_keys=False, indent=2, ensure_ascii=False)
            file = open(self.list_file, 'w', encoding='utf-8')
            file.write(updated_list)
            file.close()

        self.update_clash_profiles()

    def update_clash_profiles(self):
        """解析启用的 Clash Profile，递归收集远程 Provider 地址及元数据。"""
        profiles = [
            item for item in self.raw_list
            if item.get('enabled') and item.get('type') == 'clash_profile' and item.get('url')
        ]
        if not profiles:
            return

        changed = False
        for profile in profiles:
            try:
                providers = self._collect_clash_providers(profile['url'])
                if providers:
                    if profile.get('providers') != providers:
                        profile['providers'] = providers
                        changed = True
                    print(f"Clash Profile [{profile.get('id')}] discovered {len(providers)} remote providers.")
                else:
                    print(f"Clash Profile [{profile.get('id')}] has no providers; keeping cached provider list.")
            except Exception as e:
                print(f"Clash Profile [{profile.get('id')}] refresh failed; keeping cached provider list: {e}")

        if changed:
            updated_list = json.dumps(self.raw_list, sort_keys=False, indent=2, ensure_ascii=False)
            with open(self.list_file, 'w', encoding='utf-8') as file:
                file.write(updated_list)

    def _collect_clash_providers(self, profile_url, max_depth=4):
        """递归下载 YAML 配置以发现 proxy-providers；不解析节点内容。"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; SubscriptionProviderCollector/1.0)'
        }
        providers = []
        recorded = set()
        fetched_urls = set()

        def walk_config(config, source_url, depth):
            if depth > max_depth or not isinstance(config, dict):
                return

            provider_map = config.get('proxy-providers')
            if not isinstance(provider_map, dict):
                return

            for provider_name, provider_config in provider_map.items():
                if not isinstance(provider_config, dict):
                    continue

                provider_type = str(provider_config.get('type', 'http')).lower()
                raw_url = provider_config.get('url')
                if provider_type != 'http' or not isinstance(raw_url, str) or not raw_url.strip():
                    continue

                provider_url = urljoin(source_url, raw_url.strip())
                if not provider_url.lower().startswith(('http://', 'https://')):
                    continue

                override = provider_config.get('override') or {}
                if not isinstance(override, dict):
                    override = {}

                record_key = (str(provider_name), provider_url)
                if record_key not in recorded:
                    providers.append({
                        'name': str(provider_name),
                        'url': provider_url,
                        'type': provider_type,
                        'path': provider_config.get('path'),
                        'interval': provider_config.get('interval'),
                        'exclude_filter': provider_config.get('exclude-filter') or provider_config.get('exclude_filter'),
                        'filter': provider_config.get('filter'),
                        'exclude_type': provider_config.get('exclude-type') or provider_config.get('exclude_type') or [],
                        'header': provider_config.get('header') or {},
                        'additional_prefix': override.get('additional-prefix') or override.get('additional_prefix') or '',
                        'additional_suffix': override.get('additional-suffix') or override.get('additional_suffix') or '',
                        'proxy_name': override.get('proxy-name') or override.get('proxy_name') or {},
                        'source_url': source_url,
                        'depth': depth
                    })
                    recorded.add(record_key)

                if provider_url in fetched_urls or depth >= max_depth:
                    continue

                fetched_urls.add(provider_url)
                try:
                    response = requests.get(provider_url, headers=headers, timeout=(5, 20))
                    response.raise_for_status()
                    child_text = response.content.decode('utf-8-sig', errors='replace')
                    child_config = yaml.safe_load(child_text)
                    if isinstance(child_config, dict):
                        walk_config(child_config, response.url or provider_url, depth + 1)
                except Exception as e:
                    print(f"  Provider YAML discovery skipped [{provider_name}]: {e}")

        response = requests.get(profile_url, headers=headers, timeout=(5, 25))
        response.raise_for_status()
        profile_text = response.content.decode('utf-8-sig', errors='replace')
        profile_config = yaml.safe_load(profile_text)
        if not isinstance(profile_config, dict):
            raise ValueError("Clash Profile YAML root must be a mapping.")

        walk_config(profile_config, response.url or profile_url, 0)
        return providers

    def change_date(self,id,current_url):
        if id == 0:
            today = datetime.today().strftime('%m%d')
            url_front = 'https://raw.githubusercontent.com/pojiezhiyuanjun/freev2/master/'
            url_end = '.txt'
            new_url = url_front + today + url_end
            
        if id == 7:
            try:
                import requests
                import re
                from datetime import datetime, timedelta
        
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                }
                for delta in [0, 1]:
                    date_str = (datetime.today() - timedelta(days=delta)).strftime('%Y%m%d')
                    page_url = f'https://clashfreenode.com/a/fn{date_str}.html'
        
                    try:
                        res = requests.get(page_url, headers=headers, timeout=10)
                        if res.status_code == 200:
                            # 源码中的真实格式：https://nodebus.net/cfn/8568b1c0f1da79b3/20261012-v2ray.txt
                            pattern = rf'https://nodebus\.net/cfn/[a-f0-9]+/{date_str}-v2ray\.txt'
                            match = re.search(pattern, res.text)
        
                            if match:
                                new_url = match.group(0)
                                if self.url_updated(new_url):
                                    return new_url
                                break
                    except Exception:
                        continue
        
            except Exception as e:
                print(f"ID 7 获取最新链接失败: {e}")
            return current_url
            
        if id == 111:
            this_month = datetime.today().strftime('%m').lstrip('0')
            today = datetime.today().strftime('%d').lstrip('0')
            yesterday = (datetime.today() - timedelta(days=1)).strftime('%d').lstrip('0')
            url = f"https://agit.ai/231/123321312/src/branch/master/{this_month}"
            response = requests.get(url)
            soup = BeautifulSoup(response.content, "html.parser")
            latest_URL = None
            new_url = None
            new_url_today = None
            new_url_yesterday = None
            for row in soup.find_all("tr"):
                link = row.find("a")
                if link and f"{this_month}" in link.text and f"{today}" in link.text and "yml" not in link.text: 
                    latest_URL = f"{url}/{link.text}"
                    new_url_today = latest_URL.replace("/src/", "/raw/")
                else:
                    if link and f"{this_month}" in link.text and f"{yesterday}" in link.text and "yml" not in link.text: 
                        latest_URL = f"{url}/{link.text}"
                        new_url_yesterday = latest_URL.replace("/src/", "/raw/")
            if new_url_today:
                new_url = new_url_today
            else:
                new_url = new_url_yesterday
           
        if id == 28:
            url_date = datetime.today().strftime('%Y%m%d')
            url = "https://www.cfmem.com/"
            response = requests.get(url)
            soup = BeautifulSoup(response.text, "html.parser")
            link = soup.find("a", href=lambda href: href and url_date in href)
            new_url = None
            if link:
                link_url = link["href"]
                link_response = requests.get(link_url)
                link_soup = BeautifulSoup(link_response.text, "html.parser")
                new_url = None
                for string in link_soup.stripped_strings:
                    if string.startswith("v2ray订阅链接") and string.endswith(".txt"):
                        start = string.index("https://")
                        end = string.index(".txt") + 4
                        new_url = string[start:end]
                        break
        if id == 32:
            today = datetime.today().strftime('%Y%m%d')
            this_month = datetime.today().strftime('%m')
            this_year = datetime.today().strftime('%Y')
            url_front = 'https://nodefree.org/dy/'
            url_end = '.txt'
            new_url = url_front + this_year + '/' + this_month + '/' + today + url_end
        if id == 40:
            new_url = datetime.today().strftime('https://clashgithub.com/wp-content/uploads/rss/%Y%m%d.txt')
            if self.url_updated(new_url):
                return new_url
            else:
                return current_url
        if id == 36:
            today = datetime.today().strftime('%Y%m%d')
            this_month = datetime.today().strftime('%m')
            this_year = datetime.today().strftime('%Y')
            url_front = 'https://nodefree.org/dy/'
            url_end = '.txt'
            new_url = url_front + this_year + '/' + this_month + '/' + today + url_end

            if self.url_updated(new_url):
                return new_url
            else:
                return current_url

    def find_link(self, id, current_url):
  
        if id == 18:
            try:
                # 请求 GitHub API 获取文件列表
                api_url = "https://api.github.com/repos/free-nodes/v2rayfree/contents/"
                resp = requests.get(api_url, timeout=5)
                
                if resp.status_code == 200:
                    res_json = resp.json()
                    
                    # 筛选逻辑：
                    # 1. 排除 README.md
                    # 2. 根据数据特征，文件均以 'v' 开头 (如 v202602122)
                    target_files = [f for f in res_json if f['name'].startswith('v')]
                    
                    if target_files:
                        # 按文件名降序排列 (字符串排序: v202602122 > v202602121)
                        target_files.sort(key=lambda x: x['name'], reverse=True)
                        
                        # 返回最新文件的 raw 下载链接
                        return target_files[0]['download_url']
                    else:
                        return current_url
                return current_url
            except Exception:
                return current_url
                
        if id == 33:
            url_update = 'https://v2cross.com/archives/1884'

            if self.url_updated(url_update):
                try:
                    resp = requests.get(url_update, timeout=5)
                    raw_content = resp.text

                    raw_content = raw_content.replace('amp;', '')
                    pattern = re.compile(r'https://shadowshare.v2cross.com/publicserver/servers/temp/\w{16}')
                    
                    new_url = re.findall(pattern, raw_content)[0]
                    return new_url
                except Exception:
                    return current_url
            else:
                return current_url
                
        if id == 38:
            try:
                res_json = requests.get('https://api.github.com/repos/mianfeifq/share/contents/').json()
                for file in res_json:
                    if file['name'].startswith('data'):
                        return file['download_url'] 
                else:
                    return current_url
            except Exception:
                return current_url

if __name__ == '__main__':
    update()
