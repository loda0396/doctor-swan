# -*- coding: utf-8 -*-
"""
爬虫层。给没有 RSS 的站用（主要是中国政府网站）。

不写死解析逻辑，全靠 sources.py 里的 CSS 选择器驱动。
因为这些站会改版，改版时改一行配置比改代码快。

    python3 scrape.py probe mofcom    # 探针：把页面里的链接按 URL 模式分组打出来
    python3 scrape.py test mofcom     # 用当前配置试抓，打印结果不入库

工作流：先 probe，看哪一组是新闻列表，把那组的 URL 特征填进 sources.py 的
link_pat，再 test 验证，最后 collect.py 就能正常用了。
"""

import re
import sys
import urllib.request
import urllib.parse
from collections import Counter

from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "identity",
    })
    raw = urllib.request.urlopen(req, timeout=timeout).read()
    # 政府站常见 utf-8 / gb18030 混用，试两次
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def links(url):
    """页面里所有像新闻的链接：文字 8–80 字，有 href。"""
    soup = BeautifulSoup(get(url), "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text(strip=True).split())
        if 8 <= len(text) <= 80:
            out.append((text, urllib.parse.urljoin(url, a["href"])))
    return out


def probe(src):
    """把链接按 URL 路径模式分组。新闻列表通常是数量最多、模式最整齐的那组。"""
    ls = links(src["url"])
    print(f"{src['name']}  {src['url']}")
    print(f"共 {len(ls)} 个候选链接\n")

    pat = Counter()
    for _, u in ls:
        p = urllib.parse.urlparse(u).path
        # 把数字段替换掉，看结构
        key = re.sub(r"\d{4,}", "N", re.sub(r"/\d+", "/N", p))
        pat[key.rsplit("/", 1)[0] + "/"] += 1

    print("URL 模式（按数量排）：")
    for k, c in pat.most_common(12):
        sample = next((t for t, u in ls if urllib.parse.urlparse(u).path.startswith(
            k.replace("N", ""))), "")
        print(f"  {c:>3}  {k:<45}{sample[:34]}")

    print("\n前 15 条链接原文：")
    for t, u in ls[:15]:
        print(f"  {t[:44]:<46}{urllib.parse.urlparse(u).path[:44]}")
    print("\n把上面这段贴回给 Claude，让它填 sources.py 里的 link_pat。")


def fetch_scrape(src, layer):
    """按配置抓。link_pat 是 URL 路径里必须包含的片段。"""
    pat = src.get("link_pat")
    if not pat:
        raise NotImplementedError(f"{src['id']} 还没配 link_pat，先跑 scrape.py probe {src['id']}")

    rows, seen = [], set()
    for text, url in links(src["url"]):
        if pat not in url:
            continue
        if url in seen:
            continue
        seen.add(url)
        rows.append(dict(title=text, url=url))
        if len(rows) >= src.get("top_n", 15):
            break
    return rows


def _find(sid):
    from sources import MEDIA, OFFICIAL, VOICES, TICKER
    for s in MEDIA + OFFICIAL + VOICES + TICKER:
        if s["id"] == sid:
            return s
    raise SystemExit(f"sources.py 里没有 id={sid}")


if __name__ == "__main__":
    cmd, sid = sys.argv[1], sys.argv[2]
    src = _find(sid)
    if cmd == "probe":
        probe(src)
    elif cmd == "test":
        for r in fetch_scrape(src, "official"):
            print(f"  {r['title'][:50]:<52}{r['url']}")
