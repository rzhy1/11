import requests
import re
from packaging import version
import time

# 配置代理 (根据需要修改)
# 如果不需要代理，设置为 None 或注释掉
proxies = {
    "http": "http:127.0.0.1:1081",
    "https": "https:127.0.0.1:1081",
}
proxies = None  # 不使用代理

# 定义当前版本
current_versions = {
    "zlib": "1.3.1",
    "zstd": "1.5.6",
    "gmp": "6.3.0",
    "isl": "0.27",
    "mpfr": "4.2.1",
    "mpc": "1.3.1",
    "binutils": "2.44",
    "gcc": "14.2.0",
    "nettle": "3.10.1",
    "libtasn1": "4.20.0",
    "libunistring": "1.3",
    "gpg-error": "1.51",
    "libassuan": "3.0.1",
    "gpgme": "1.24.1",
    "c-ares": "1.34.4",
    "libiconv": "1.18",
    "libidn2": "2.3.0",
    "libpsl": "0.21.5",
    "pcre2": "10.45",
    "expat": "2.6.4",
    "libmetalink": "0.1.3",
    "gnutls": "3.8.8",
    "openssl": "1.1.1w", # 或 "3.4.0"，脚本中注释的是 3.4.0，实际下载的是 1.1.1w
}

## 重试函数 (支持代理)
def retry(func, url, max_retries=5, delay=2, proxies=None):
    attempts = 0
    while attempts < max_retries:
        try:
            response = func(url, proxies=proxies)  # 传递 proxies 参数给 requests.get
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            attempts += 1
            print(f"请求失败，重试中 ({attempts}/{max_retries})...")
            if attempts == max_retries:
                raise e
            time.sleep(delay)

# 获取最新版本的函数 (支持代理)
def get_latest_version(program, proxies=None):
    if program == "zlib":
        url = "https://api.github.com/repos/madler/zlib/releases/latest"
        response = retry(requests.get, url, proxies=proxies)
        data = response.json()
        latest_version = data["tag_name"].lstrip("v")
        download_url = data["assets"][0]["browser_download_url"]
        return latest_version, download_url

    elif program == "zstd":
        url = "https://api.github.com/repos/facebook/zstd/releases/latest"
        response = retry(requests.get, url, proxies=proxies)
        data = response.json()
        latest_version = data["tag_name"].lstrip("v")
        download_url = data["assets"][0]["browser_download_url"]
        return latest_version, download_url

    elif program == "gmp":
        url = "https://ftp.gnu.org/gnu/gmp/"
        response = retry(requests.get, url, proxies=proxies)
        matches = re.findall(r'href="gmp-([0-9.]+)\.tar\.(xz|gz)"', response.text)
        latest_version = max(matches, key=lambda x: version.parse(x[0]))[0]
        download_url = f"https://ftp.gnu.org/gnu/gmp/gmp-{latest_version}.tar.xz"
        return latest_version, download_url

    elif program == "isl":
        url = "https://libisl.sourceforge.io/"
        response = retry(requests.get, url, proxies=proxies)
        matches = re.findall(r'href="isl-([\d.]+)\.tar\.xz"', response.text)
        if not matches:
            return current_versions["isl"], f"https://libisl.sourceforge.io/isl-{current_versions['isl']}.tar.xz"
        latest_version = max(matches, key=version.parse)
        download_url = f"https://libisl.sourceforge.io/isl-{latest_version}.tar.xz"
        return latest_version, download_url

    elif program == "mpfr":
        url = "https://ftp.gnu.org/gnu/mpfr/"
        response = retry(requests.get, url, proxies=proxies)
        matches = re.findall(r'href="mpfr-([0-9.]+)\.tar\.(xz|gz)"', response.text)
        latest_version = max(matches, key=lambda x: version.parse(x[0]))[0]
        download_url = f"https://ftp.gnu.org/gnu/mpfr/mpfr-{latest_version}.tar.xz"
        return latest_version, download_url

    elif program == "mpc":
        url = "https://ftp.gnu.org/gnu/mpc/"
        response = retry(requests.get, url, proxies=proxies)
        matches = re.findall(r'href="mpc-([0-9.]+)\.tar\.(gz|xz)"', response.text)
        latest_version = max(matches, key=lambda x: version.parse(x[0]))[0]
        download_url = f"https://ftp.gnu.org/gnu/mpc/mpc-{latest_version}.tar.gz"
        return latest_version, download_url

    elif program == "binutils":
        url = "https://ftp.gnu.org/gnu/binutils/"
        response = retry(requests.get, url, proxies=proxies)
        matches = re.findall(r'href="binutils-([0-9.]+)\.tar\.(xz|gz)"', response.text)
        latest_version = max(matches, key=lambda x: version.parse(x[0]))[0]
        download_url = f"https://ftp.gnu.org/gnu/binutils/binutils-{latest_version}.tar.xz"
        return latest_version, download_url

    elif program == "gcc":
        url = "https://ftp.gnu.org/gnu/gcc/"
        response = retry(requests.get, url, proxies=proxies)
        matches = re.findall(r'href="gcc-([0-9.]+)/"', response.text)
        if not matches:
            return current_versions["gcc"], f"https://ftp.gnu.org/gnu/gcc/gcc-{current_versions['gcc']}/gcc-{current_versions['gcc']}.tar.xz"

        version_matches = [m for m in matches if re.match(r"^\d+(\.\d+)+$", m)]
        if not version_matches:
            return current_versions["gcc"], f"https://ftp.gnu.org/gnu/gcc/gcc-{current_versions['gcc']}/gcc-{current_versions['gcc']}.tar.xz"

        latest_version = max(version_matches, key=version.parse)
        download_url = f"https://ftp.gnu.org/gnu/gcc/gcc-{latest_version}/gcc-{latest_version}.tar.xz"
        return latest_version, download_url

    elif program == "nettle":
        url = "https://ftp.gnu.org/gnu/nettle/"
        response = retry(requests.get, url, proxies=proxies)
        matches = re.findall(r'href="nettle-([0-9.]+)\.tar\.(gz|xz)"', response.text)
        latest_version = max(matches, key=lambda x: version.parse(x[0]))[0]
        download_url = f"https://ftp.gnu.org/gnu/nettle/nettle-{latest_version}.tar.gz" # Correct URL - using latest_version
        return latest_version, download_url   
        

    elif program == "libtasn1":
        url = "https://ftp.gnu.org/gnu/libtasn1/"
        response = retry(requests.get, url, proxies=proxies)
        matches = re.findall(r'href="libtasn1-([0-9.]+)\.tar\.(gz|xz)"', response.text)
        latest_version = max(matches, key=lambda x: version.parse(x[0]))[0]
        download_url = f"https://ftp.gnu.org/gnu/libtasn1/libtasn1-{latest_version}.tar.gz" # Correct URL - using latest_version
        return latest_version, download_url

    elif program == "libunistring":
        url = "https://ftp.gnu.org/gnu/libunistring/"
        response = retry(requests.get, url, proxies=proxies)
        matches = re.findall(r'href="libunistring-([0-9.]+)\.tar\.(gz|xz)"', response.text)
        latest_version = max(matches, key=lambda x: version.parse(x[0]))[0]
        download_url = f"https://ftp.gnu.org/gnu/libunistring/libunistring-{latest_version}.tar.gz" # Correct URL - using latest_version
        return latest_version, download_url

    elif program == "gpg-error":
        url = "https://www.gnupg.org/ftp/gcrypt/libgpg-error/"
        response = retry(requests.get, url, proxies=proxies)
        matches = re.findall(r'href="libgpg-error-([0-9.]+)\.tar\.(gz|xz)"', response.text)
        latest_version = max(matches, key=lambda x: version.parse(x[0]))[0]
        download_url = f"https://www.gnupg.org/ftp/gcrypt/libgpg-error/libgpg-error-{latest_version}.tar.gz" # Correct URL - using latest_version
        return latest_version, download_url

    elif program == "libassuan":
        url = "https://www.gnupg.org/ftp/gcrypt/libassuan/"
        response = retry(requests.get, url, proxies=proxies)
        matches = re.findall(r'href="libassuan-([0-9.]+)\.tar\.(bz2|xz)"', response.text)
        latest_version = max(matches, key=lambda x: version.parse(x[0]))[0]
        download_url = f"https://www.gnupg.org/ftp/gcrypt/libassuan/libassuan-{latest_version}.tar.bz2" # Correct URL - using latest_version
        return latest_version, download_url

    elif program == "gpgme":
        url = "https://www.gnupg.org/ftp/gcrypt/gpgme/"
        response = retry(requests.get, url, proxies=proxies)
        matches = re.findall(r'href="gpgme-([0-9.]+)\.tar\.(bz2|xz)"', response.text)
        latest_version = max(matches, key=lambda x: version.parse(x[0]))[0]
        download_url = f"https://www.gnupg.org/ftp/gcrypt/gpgme/gpgme-{latest_version}.tar.bz2" # Correct URL - using latest_version
        return latest_version, download_url

    elif program == "c-ares":
        url = "https://api.github.com/repos/c-ares/c-ares/releases/latest"
        response = retry(requests.get, url, proxies=proxies)
        data = response.json()
        latest_version = data["tag_name"].lstrip("v")
        for asset in data["assets"]:
            if asset["name"].endswith(".tar.gz"):
                download_url = asset["browser_download_url"]
                return latest_version, download_url
        download_url = data["assets"][0]["browser_download_url"]
        return latest_version, download_url

    elif program == "libiconv":
        url = "https://ftp.gnu.org/gnu/libiconv/"
        response = retry(requests.get, url, proxies=proxies)
        matches = re.findall(r'href="libiconv-([0-9.]+)\.tar\.(gz|xz)"', response.text)
        latest_version = max(matches, key=lambda x: version.parse(x[0]))[0]
        download_url = f"https://ftp.gnu.org/gnu/libiconv/libiconv-{latest_version}.tar.gz" # Correct URL - using latest_version
        return latest_version, download_url

    elif program == "libidn2":
        url = "https://ftp.gnu.org/gnu/libidn/"
        response = retry(requests.get, url, proxies=proxies)
        matches = re.findall(r'href="libidn2-([0-9.]+)\.tar\.(gz|xz)"', response.text)
        latest_version = max(matches, key=lambda x: version.parse(x[0]))[0]
        download_url = f"https://ftp.gnu.org/gnu/libidn/libidn2-{latest_version}.tar.gz" # Correct URL - using latest_version
        return latest_version, download_url

    elif program == "libpsl":
        url = "https://api.github.com/repos/rockdaboot/libpsl/releases/latest"
        response = retry(requests.get, url, proxies=proxies)
        data = response.json()
        latest_version = data["tag_name"].lstrip("v")
        download_url = data["assets"][0]["browser_download_url"]
        return latest_version, download_url

    elif program == "pcre2":
        url = "https://api.github.com/repos/PCRE2Project/pcre2/releases/latest"
        response = retry(requests.get, url, proxies=proxies)
        data = response.json()
        latest_version = data["tag_name"].replace('pcre2-', '')
        download_url = data["assets"][0]["browser_download_url"]
        return latest_version, download_url

    elif program == "expat":
        url = "https://api.github.com/repos/libexpat/libexpat/releases/latest"
        response = retry(requests.get, url, proxies=proxies)
        data = response.json()
        latest_version = data["tag_name"].lstrip("R_").replace('_', '.')
        download_url = data["assets"][0]["browser_download_url"]
        return latest_version, download_url

    elif program == "libmetalink":
        url = "https://api.github.com/repos/metalink-dev/libmetalink/releases/latest"
        response = retry(requests.get, url, proxies=proxies)
        data = response.json()
        latest_version = data["tag_name"].lstrip("release-")
        download_url = data["assets"][0]["browser_download_url"]
        return latest_version, download_url

    elif program == "gnutls":
        base_url = "https://www.gnupg.org/ftp/gcrypt/gnutls/v3.8/" # Direct to v3.8 as base, will improve later if needed
        response = retry(requests.get, base_url, proxies=proxies) # Go directly to v3.8 for now
        matches = re.findall(r'href="gnutls-([\d.]+)\.tar\.xz"', response.text) # Regex in v3.8 dir
        if not matches:
             return current_versions["gnutls"], f"https://www.gnupg.org/ftp/gcrypt/gnutls/gnutls-{current_versions['gnutls']}.tar.xz"
        latest_version = max(matches, key=lambda x: version.parse(x))[0]
        download_url = f"https://www.gnupg.org/ftp/gcrypt/gnutls/v3.8/gnutls-{latest_version}.tar.xz" # Hardcoded v3.8 for now, if needed will improve
        return latest_version, download_url


    elif program == "openssl":
        base_url = "https://www.openssl.org/source/old/1.1.1/" # Direct to 1.1.1 as base, will improve later if needed
        response = retry(requests.get, base_url, proxies=proxies) # Go directly to 1.1.1 for now
        matches = re.findall(r'href="openssl-([\d.]+[a-z]?)\.tar\.gz"', response.text) # Regex for openssl versions, incl. letters
        if not matches:
            return current_versions["openssl"], f"https://www.openssl.org/source/old/openssl-{current_versions['openssl']}.tar.gz"
        # Custom version comparison for openssl, handling letter suffixes
        def openssl_version_key(v):
            parts = re.split(r'(\d+)', v) # Split by digits and non-digits to handle 'w' suffix
            version_parts = []
            for part in parts:
                if part.isdigit():
                    version_parts.append(int(part))
                elif part: # Handle non-digit suffixes like 'w'
                    version_parts.append(part)
            return tuple(version_parts)

        latest_version = max(matches, key=openssl_version_key) # Use custom key for max
        download_url = f"https://www.openssl.org/source/old/1.1.1/openssl-{latest_version}.tar.gz" # Hardcoded 1.1.1, improve later if needed
        return latest_version, download_url


    else:
        raise ValueError(f"Unsupported program: {program}")

# 检查更新
update_found = False

for program, current_version in current_versions.items():
    try:
        latest_version, download_url = get_latest_version(program)
        if version.parse(latest_version) > version.parse(current_version):
            print(f"- {program} 有最新版：{latest_version}  {download_url}")
            update_found = True
        else:
            print(f"- {program} {current_version} 已是最新版 {download_url}")
    except Exception as e:
        print(f"- {program} 获取最新版本失败: {e}")

# 如果没有发现更新
if not update_found:
    print("- 所有程序都没有更新的版本")
