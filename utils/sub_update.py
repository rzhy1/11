#!/usr/bin/env python3

from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import json, re
import requests


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

    def change_date(self,id,current_url):
        if id == 0:
            today = datetime.today().strftime('%m%d')
            url_front = 'https://raw.githubusercontent.com/pojiezhiyuanjun/freev2/master/'
            url_end = '.txt'
            new_url = url_front + today + url_end
            
        if id == 7:
            new_url = datetime.today().strftime('https://clashfreenode.com/feed/v2ray-%Y%m%d.txt')
            if self.url_updated(new_url):
                return new_url
            else:
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
