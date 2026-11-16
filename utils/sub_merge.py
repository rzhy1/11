#!/usr/bin/env python3
"""下载订阅及 Clash Proxy Provider 的原始内容，供后续程序处理。

本模块只负责 URL 展开、HTTP 下载和原始文件保存：
- 不解析/转换单个节点；
- 不过滤节点；
- 不去重或合并节点；
- 不生成 Base64 节点订阅。
"""

import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import requests


class merge:
    def __init__(self, file_dir, format_config=None):
        self.list_file = Path(file_dir['list_file'])
        self.download_dir = Path(file_dir.get('list_dir', './sub/list/'))
        self.manifest_file = Path(
            file_dir.get('manifest_file', './sub/provider_manifest.json')
        )
        self.format_config = format_config or {}
        self.url_list = self.read_list()
        self.download_sources()

    def read_list(self):
        with self.list_file.open('r', encoding='utf-8') as file:
            return [item for item in json.load(file) if item.get('enabled')]

    @staticmethod
    def _safe_name(value):
        value = re.sub(r'[^0-9A-Za-z._-]+', '_', str(value)).strip('._-')
        return value[:80] or 'source'

    @staticmethod
    def _extension(url, content_type=''):
        path = urlparse(url).path.lower()
        suffix = Path(path).suffix
        if suffix in ('.yaml', '.yml', '.json', '.txt', '.conf', '.list'):
            return suffix
        content_type = (content_type or '').lower()
        if 'yaml' in content_type or 'yml' in content_type:
            return '.yaml'
        if 'json' in content_type:
            return '.json'
        return '.txt'

    def _expand_sources(self):
        """把 Profile 项展开成缓存的 Provider URL；保留普通订阅项。"""
        sources = []
        for item in self.url_list:
            if item.get('type') != 'clash_profile':
                sources.append({
                    'id': item.get('id'),
                    'remarks': item.get('remarks', ''),
                    'url': item.get('url'),
                    'source_type': item.get('type', 'subscription'),
                    'provider': None
                })
                continue

            providers = item.get('providers') or []
            print(
                f"Clash Profile [ID: {item.get('id')}] "
                f"contains {len(providers)} cached Provider URLs."
            )
            for provider in providers:
                if not isinstance(provider, dict) or not provider.get('url'):
                    continue
                sources.append({
                    'id': item.get('id'),
                    'remarks': f"{item.get('remarks', 'Clash Profile')} / {provider.get('name', 'Provider')}",
                    'url': provider['url'],
                    'source_type': 'clash_provider',
                    'provider': provider
                })
        return sources

    def download_sources(self):
        self.download_dir.mkdir(parents=True, exist_ok=True)
        sources = self._expand_sources()
        manifest = []
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; SubscriptionContentFetcher/1.0)'
        })

        for index, item in enumerate(sources, start=1):
            url = item.get('url')
            if not isinstance(url, str) or not url.strip():
                continue

            source_id = item.get('id', 'unknown')
            remarks = item.get('remarks') or f'source_{index}'
            provider = item.get('provider') or {}
            label = provider.get('name') or remarks
            digest = hashlib.sha1(url.encode('utf-8')).hexdigest()[:10]
            stem = f"{self._safe_name(source_id)}_{self._safe_name(label)}_{digest}"

            print(f"Downloading [{source_id}] {remarks}: {url}")
            try:
                response = session.get(url, timeout=(8, 30))
                response.raise_for_status()
                content = response.content
                if not content:
                    raise ValueError('Downloaded content is empty.')

                extension = self._extension(response.url or url, response.headers.get('Content-Type', ''))
                filename = stem + extension
                output_path = self.download_dir / filename
                output_path.write_bytes(content)

                record = {
                    'id': source_id,
                    'remarks': remarks,
                    'source_type': item.get('source_type'),
                    'url': url,
                    'final_url': response.url,
                    'file': str(output_path.as_posix()),
                    'content_type': response.headers.get('Content-Type', ''),
                    'size': len(content)
                }
                if provider:
                    record['provider'] = provider
                manifest.append(record)
                print(f"  -> Saved raw response: {output_path} ({len(content)} bytes)")
            except Exception as error:
                print(f"  -> Download failed: {error}")
                manifest.append({
                    'id': source_id,
                    'remarks': remarks,
                    'source_type': item.get('source_type'),
                    'url': url,
                    'error': str(error)
                })

        self.manifest_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = self.manifest_file.with_suffix(self.manifest_file.suffix + '.tmp')
        temporary_file.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8'
        )
        temporary_file.replace(self.manifest_file)
        print(
            f"Finished downloading {sum(1 for item in manifest if 'file' in item)} "
            f"of {len(sources)} sources. Manifest: {self.manifest_file}"
        )


if __name__ == '__main__':
    file_dir = {
        'list_dir': './sub/list/',
        'list_file': './sub/sub_list.json',
        'merge_dir': './sub/',
        'manifest_file': './sub/provider_manifest.json'
    }
    merge(file_dir, {})
