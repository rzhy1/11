import os
import sys
import unittest
from unittest.mock import Mock, patch

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "utils"))
from sub_update import update


class ClashProviderDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.updater = update.__new__(update)

    def response(self, url, content):
        result = Mock()
        result.url = url
        result.content = content.encode("utf-8")
        result.raise_for_status = Mock()
        return result

    def test_nested_provider_urls_and_override_metadata_are_collected(self):
        profile_url = "https://example.com/profile.yaml"
        root_provider_url = "https://example.com/providers/root.yaml"
        nested_provider_url = "https://example.com/nested.txt"

        profile = {
            "proxy-providers": {
                "root": {
                    "type": "http",
                    "url": "./providers/root.yaml",
                    "path": "./root.yaml",
                    "interval": 3600,
                    "exclude-filter": "(?i)expired",
                    "filter": "HK",
                    "exclude-type": ["ss"],
                    "header": {"Authorization": "Bearer test"},
                    "override": {
                        "additional-prefix": "A-",
                        "additional-suffix": "-Z",
                        "proxy-name": [
                            {"pattern": "^HK-(.*)$", "target": "$1"}
                        ]
                    }
                }
            }
        }
        child = {
            "proxy-providers": {
                "nested": {
                    "type": "http",
                    "url": "../nested.txt",
                    "override": {"additional-prefix": "N-"}
                }
            }
        }
        responses = {
            profile_url: self.response(profile_url, yaml.safe_dump(profile)),
            root_provider_url: self.response(root_provider_url, yaml.safe_dump(child)),
            nested_provider_url: self.response(nested_provider_url, "vless://example.com:443")
        }

        with patch("sub_update.requests.get", side_effect=lambda url, **kwargs: responses[url]) as get:
            providers = self.updater._collect_clash_providers(profile_url)

        self.assertEqual(len(providers), 2)
        self.assertEqual([item["name"] for item in providers], ["root", "nested"])
        self.assertEqual([item["depth"] for item in providers], [0, 1])
        self.assertEqual(providers[0]["exclude_filter"], "(?i)expired")
        self.assertEqual(providers[0]["filter"], "HK")
        self.assertEqual(providers[0]["exclude_type"], ["ss"])
        self.assertEqual(providers[0]["header"], {"Authorization": "Bearer test"})
        self.assertEqual(providers[0]["additional_prefix"], "A-")
        self.assertEqual(providers[0]["additional_suffix"], "-Z")
        self.assertEqual(providers[0]["proxy_name"][0]["target"], "$1")
        self.assertEqual(providers[1]["additional_prefix"], "N-")
        self.assertEqual(get.call_count, 3)

    def test_max_depth_stops_nested_provider_discovery(self):
        profile_url = "https://example.com/profile.yaml"
        root_provider_url = "https://example.com/providers/root.yaml"
        profile = {"proxy-providers": {
            "root": {"type": "http", "url": "./providers/root.yaml"}
        }}
        child = {"proxy-providers": {
            "nested": {"type": "http", "url": "../nested.txt"}
        }}
        responses = {
            profile_url: self.response(profile_url, yaml.safe_dump(profile)),
            root_provider_url: self.response(root_provider_url, yaml.safe_dump(child))
        }
        with patch("sub_update.requests.get", side_effect=lambda url, **kwargs: responses[url]) as get:
            providers = self.updater._collect_clash_providers(profile_url, max_depth=0)

        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0]["depth"], 0)
        self.assertEqual(get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
