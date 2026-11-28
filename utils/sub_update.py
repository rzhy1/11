#!/usr/bin/env python3

from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import html
import ipaddress
import json
import os
import re
import socket
import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class update:
    DEFAULT_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    MAX_PROVIDER_BYTES = 10 * 1024 * 1024  # 10 MB

    def __init__(self, config=None):
        config = config if isinstance(config, dict) else {}
        self.list_file = config.get('list_file') or './sub/sub_list.json'
        self.allow_private_provider_urls = bool(config.get('allow_private_provider_urls', False))
        self._session = None
        self.raw_list = self._load_list()
        if not self.raw_list:
            return

        with self._build_session() as session:
            self._session = session
            try:
                self.update_main()
            finally:
                self._session = None

    def _load_list(self):
        if not os.path.exists(self.list_file):
            print(f"Error: Subscription list file not found: {self.list_file}")
            return []
        try:
            with open(self.list_file, 'r', encoding='utf-8') as f:
                raw_list = json.load(f)
        except Exception as e:
            print(f"Error: Failed to load {self.list_file}: {e}")
            return []

        if not isinstance(raw_list, list):
            print(f"Error: {self.list_file} top-level JSON must be a list.")
            return []
        return raw_list

    def _save_list(self):
        updated_list = json.dumps(self.raw_list, sort_keys=False, indent=2, ensure_ascii=False)
        temp_file = self.list_file + '.tmp'
        try:
            with open(temp_file, 'w', encoding='utf-8', newline='\n') as f:
                f.write(updated_list + '\n')
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file, self.list_file)
        finally:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError:
                    pass

    @staticmethod
    def _build_session():
        session = requests.Session()
        retry = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(('GET', 'HEAD')),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session

    def _get_session(self):
        return self._session if self._session is not None else requests

    @staticmethod
    def _is_disallowed_ip(ip_obj):
        if ip_obj.ipv4_mapped is not None:
            ip_obj = ip_obj.ipv4_mapped
        return (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        )

    def _is_safe_http_url(self, url):
        """校验 URL 仅使用 HTTP/HTTPS 且不指向本机、内网或保留地址（防 SSRF）。"""
        if not isinstance(url, str) or not url.strip():
            return False, 'empty_url'
        parsed = urlparse(url.strip())
        if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname:
            return False, 'unsupported_scheme_or_host'
        if self.allow_private_provider_urls:
            return True, None

        hostname = parsed.hostname.strip().lower()
        if hostname in ('localhost', 'localhost.localdomain') or hostname.endswith('.local'):
            return False, 'disallowed_local_hostname'

        port = parsed.port or (443 if parsed.scheme.lower() == 'https' else 80)
        try:
            ip_literal = ipaddress.ip_address(hostname)
            if self._is_disallowed_ip(ip_literal):
                return False, 'disallowed_ip_address'
            return True, None
        except ValueError:
            pass

        try:
            addr_infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            return False, f'dns_resolution_failed: {exc}'

        if not addr_infos:
            return False, 'dns_resolution_empty'

        for info in addr_infos:
            sockaddr = info[4]
            if not sockaddr:
                continue
            resolved_ip = sockaddr[0].split('%', 1)[0]
            try:
                ip_obj = ipaddress.ip_address(resolved_ip)
            except ValueError:
                return False, 'invalid_resolved_ip'
            if self._is_disallowed_ip(ip_obj):
                return False, 'disallowed_resolved_private_ip'
        return True, None

    def _safe_get_bytes(self, url, headers=None, timeout=(5, 20), max_bytes=MAX_PROVIDER_BYTES, check_ssrf=False):
        """支持重定向逐跳安全校验与流式体积限制的 GET 请求。"""
        session = self._get_session()
        current_url = url
        for _ in range(6):
            if check_ssrf:
                safe, reason = self._is_safe_http_url(current_url)
                if not safe:
                    raise ValueError(f"Blocked unsafe URL ({reason}): {current_url}")

            with session.get(
                current_url,
                headers=headers or self.DEFAULT_HEADERS,
                timeout=timeout,
                stream=True,
                allow_redirects=False,
            ) as resp:
                if 300 <= resp.status_code < 400 and resp.headers.get('Location'):
                    current_url = urljoin(current_url, resp.headers['Location'])
                    continue

                resp.raise_for_status()
                content_length = resp.headers.get('Content-Length')
                if content_length and content_length.isdigit() and int(content_length) > max_bytes:
                    raise ValueError(f"Response size ({content_length} bytes) exceeds limit ({max_bytes} bytes).")

                chunks = []
                total_bytes = 0
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    total_bytes += len(chunk)
                    if total_bytes > max_bytes:
                        raise ValueError(f"Downloaded content exceeds {max_bytes} bytes limit.")
                    chunks.append(chunk)
                return resp.status_code, current_url, b''.join(chunks)

        raise ValueError(f"Too many redirects fetching: {url}")

    def url_updated(self, url):
        """流式检查远程链接是否可用（只检查响应头与状态码，不下载整份正文）。"""
        if not isinstance(url, str) or not url.strip():
            return False
        session = self._get_session()
        try:
            with session.get(url, headers=self.DEFAULT_HEADERS, timeout=(5, 10), stream=True) as resp:
                if resp.status_code != 200:
                    return False
                content_length = resp.headers.get('Content-Length')
                if content_length and content_length.isdigit() and int(content_length) == 0:
                    return False
                return True
        except requests.RequestException:
            return False

    def update_main(self):
        changed = False
        for idx, sub in enumerate(self.raw_list):
            if not isinstance(sub, dict):
                print(f'Warning: Ignoring non-object entry at index {idx} in {self.list_file}.')
                continue

            sub_id = sub.get('id')
            current_url = sub.get('url')
            if sub_id is None or current_url is None:
                print(f'Warning: Entry at index {idx} missing id or url; skipping.')
                continue

            if not sub.get('enabled'):
                continue

            update_method = sub.get('update_method')
            if not update_method:
                if sub.get('type') != 'clash_profile':
                    print(f'{sub_id} Url not changed! Please define update method.')
                continue

            if update_method == 'auto':
                continue

            try:
                print(f'Finding available update for ID{sub_id}')
                if update_method == 'change_date':
                    new_url = self.change_date(sub_id, current_url)
                elif update_method == 'page_release':
                    new_url = self.find_link(sub_id, current_url)
                else:
                    print(f'ID{sub_id} has unknown update_method: {update_method}\n')
                    continue

                if not isinstance(new_url, str) or not new_url.strip():
                    print(f'ID{sub_id} update failed; keeping current URL.\n')
                elif new_url == current_url:
                    print(f'No available update for ID{sub_id}\n')
                else:
                    sub['url'] = new_url
                    changed = True
                    print(f'ID{sub_id} url updated to {new_url}\n')
            except Exception as e:
                print(f'ID{sub_id} update error ({e}); keeping current URL.\n')

        if changed:
            self._save_list()

        self.update_clash_profiles()

    def update_clash_profiles(self):
        """解析启用的 Clash Profile，递归收集远程 Provider 地址及元数据。"""
        profiles = [
            item for item in self.raw_list
            if isinstance(item, dict)
            and item.get('enabled')
            and item.get('type') == 'clash_profile'
            and item.get('url')
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
            self._save_list()

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

                provider_type = str(provider_config.get('type') or 'http').lower()
                raw_url = provider_config.get('url')
                if provider_type != 'http' or not isinstance(raw_url, str) or not raw_url.strip():
                    continue

                provider_url = urljoin(source_url, raw_url.strip())
                safe, reason = self._is_safe_http_url(provider_url)
                if not safe:
                    print(f"  Skipped unsafe Provider URL [{provider_name}]: {reason}")
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
                    _, final_url, child_bytes = self._safe_get_bytes(
                        provider_url,
                        headers=headers,
                        timeout=(5, 20),
                        check_ssrf=True,
                    )
                    child_text = child_bytes.decode('utf-8-sig', errors='replace')
                    # 普通节点/Base64 订阅不含 proxy-providers，直接跳过 YAML 解析以节省开销。
                    if 'proxy-providers' not in child_text:
                        continue
                    child_config = yaml.safe_load(child_text)
                    if isinstance(child_config, dict):
                        walk_config(child_config, final_url or provider_url, depth + 1)
                except Exception as e:
                    print(f"  Provider YAML discovery skipped [{provider_name}]: {e}")

        _, final_profile_url, profile_bytes = self._safe_get_bytes(
            profile_url,
            headers=headers,
            timeout=(5, 25),
            check_ssrf=True,
        )
        profile_text = profile_bytes.decode('utf-8-sig', errors='replace')
        profile_config = yaml.safe_load(profile_text)
        if not isinstance(profile_config, dict):
            raise ValueError("Clash Profile YAML root must be a mapping.")

        walk_config(profile_config, final_profile_url or profile_url, 0)
        return providers

    def change_date(self, sub_id, current_url):
        session = self._get_session()

        if sub_id == 0:
            today = datetime.today().strftime('%m%d')
            new_url = f'https://raw.githubusercontent.com/pojiezhiyuanjun/freev2/master/{today}.txt'
            return new_url if self.url_updated(new_url) else current_url

        if sub_id == 7:
            try:
                for delta in (0, 1):
                    date_str = (datetime.today() - timedelta(days=delta)).strftime('%Y%m%d')
                    page_url = f'https://clashfreenode.com/a/fn{date_str}.html'
                    try:
                        res = session.get(page_url, headers=self.DEFAULT_HEADERS, timeout=(5, 15))
                        if res.status_code == 200:
                            # 源码中的真实格式：https://nodebus.net/cfn/8568b1c0f1da79b3/20261012-v2ray.txt
                            pattern = rf'https://nodebus\.net/cfn/[a-f0-9]+/{date_str}-v2ray\.txt'
                            match = re.search(pattern, res.text)
                            if match:
                                new_url = match.group(0)
                                if self.url_updated(new_url):
                                    return new_url
                    except requests.RequestException:
                        continue
            except Exception as e:
                print(f"ID 7 获取最新链接失败: {e}")
            return current_url

        if sub_id == 111:
            try:
                now = datetime.today()
                yesterday_dt = now - timedelta(days=1)
                this_month = str(now.month)
                url = f"https://agit.ai/231/123321312/src/branch/master/{this_month}"
                response = session.get(url, headers=self.DEFAULT_HEADERS, timeout=(5, 15))
                response.raise_for_status()
                soup = BeautifulSoup(response.content, "html.parser")

                def date_matches(text, dt):
                    m = str(dt.month)
                    d = str(dt.day)
                    d_pad = f"{dt.day:02d}"
                    pattern = rf'(?<!\d){m}[._-]?({d_pad}|{d})(?!\d)'
                    return re.search(pattern, text) is not None

                new_url_today = None
                new_url_yesterday = None
                for row in soup.find_all("tr"):
                    link = row.find("a")
                    if not link or not link.get('href'):
                        continue
                    link_name = link.get_text(strip=True)
                    lowered_name = link_name.lower()
                    if not link_name or 'yml' in lowered_name or 'yaml' in lowered_name:
                        continue
                    candidate = urljoin(url + '/', link['href']).replace('/src/', '/raw/')
                    if date_matches(link_name, now):
                        new_url_today = candidate
                    elif date_matches(link_name, yesterday_dt):
                        new_url_yesterday = candidate

                for candidate in (new_url_today, new_url_yesterday):
                    if candidate and self.url_updated(candidate):
                        return candidate
            except Exception as e:
                print(f"ID 111 获取最新链接失败: {e}")
            return current_url

        if sub_id == 28:
            try:
                url_date = datetime.today().strftime('%Y%m%d')
                url = "https://www.cfmem.com/"
                response = session.get(url, headers=self.DEFAULT_HEADERS, timeout=(5, 15))
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                link = soup.find("a", href=lambda href: href and url_date in href)
                if link and link.get("href"):
                    link_url = urljoin(url, link["href"])
                    link_response = session.get(link_url, headers=self.DEFAULT_HEADERS, timeout=(5, 15))
                    link_response.raise_for_status()
                    link_soup = BeautifulSoup(link_response.text, "html.parser")
                    for text in link_soup.stripped_strings:
                        if "v2ray订阅链接" in text or text.lower().endswith(".txt"):
                            match = re.search(r'https?://[^\s<>"\']+?\.txt\b', text)
                            if match:
                                candidate = match.group(0)
                                if self.url_updated(candidate):
                                    return candidate
            except Exception as e:
                print(f"ID 28 获取最新链接失败: {e}")
            return current_url

        if sub_id in (32, 36):
            new_url = datetime.today().strftime('https://nodefree.org/dy/%Y/%m/%Y%m%d.txt')
            return new_url if self.url_updated(new_url) else current_url

        if sub_id == 40:
            new_url = datetime.today().strftime('https://clashgithub.com/wp-content/uploads/rss/%Y%m%d.txt')
            return new_url if self.url_updated(new_url) else current_url

        return current_url

    def find_link(self, sub_id, current_url):
        session = self._get_session()
        github_headers = {
            **self.DEFAULT_HEADERS,
            'Accept': 'application/vnd.github.v3+json',
        }

        if sub_id == 18:
            try:
                api_url = "https://api.github.com/repos/free-nodes/v2rayfree/contents/"
                resp = session.get(api_url, headers=github_headers, timeout=(5, 15))
                resp.raise_for_status()
                res_json = resp.json()
                if not isinstance(res_json, list):
                    return current_url
                target_files = [
                    f for f in res_json
                    if isinstance(f, dict)
                    and f.get('type') == 'file'
                    and str(f.get('name', '')).startswith('v')
                    and f.get('download_url')
                ]
                if target_files:
                    target_files.sort(key=lambda x: x['name'], reverse=True)
                    return target_files[0]['download_url']
            except Exception as e:
                print(f"ID 18 获取最新链接失败: {e}")
            return current_url

        if sub_id == 33:
            url_update = 'https://v2cross.com/archives/1884'
            try:
                resp = session.get(url_update, headers=self.DEFAULT_HEADERS, timeout=(5, 15))
                resp.raise_for_status()
                raw_content = html.unescape(resp.text).replace('amp;', '')
                pattern = re.compile(r'https://shadowshare\.v2cross\.com/publicserver/servers/temp/\w{16}')
                matches = re.findall(pattern, raw_content)
                if matches:
                    return matches[0]
            except Exception as e:
                print(f"ID 33 获取最新链接失败: {e}")
            return current_url

        if sub_id == 38:
            try:
                api_url = 'https://api.github.com/repos/mianfeifq/share/contents/'
                resp = session.get(api_url, headers=github_headers, timeout=(5, 15))
                resp.raise_for_status()
                res_json = resp.json()
                if not isinstance(res_json, list):
                    return current_url
                target_files = [
                    f for f in res_json
                    if isinstance(f, dict)
                    and f.get('type') == 'file'
                    and str(f.get('name', '')).startswith('data')
                    and f.get('download_url')
                ]
                if target_files:
                    target_files.sort(key=lambda x: x['name'], reverse=True)
                    return target_files[0]['download_url']
            except Exception as e:
                print(f"ID 38 获取最新链接失败: {e}")
            return current_url

        return current_url


if __name__ == '__main__':
    update()
