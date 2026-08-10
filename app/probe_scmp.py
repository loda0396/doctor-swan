# -*- coding: utf-8 -*-
"""挨个试 SCMP 的候选 feed，看哪个真的是涉华报道。
别猜地址——让每个候选自己把内容吐出来，肉眼一秒能判断。"""
import urllib.request
import feedparser

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"

CANDIDATES = [
    ("现在用的",   "https://www.scmp.com/rss/91/feed"),
    ("综合新闻",   "https://www.scmp.com/rss/4/feed"),
    ("China",     "https://www.scmp.com/rss/4/feed?ch=china"),
    ("China 频道", "https://www.scmp.com/rss/318198/feed"),
    ("Asia",      "https://www.scmp.com/rss/3/feed"),
    ("Business",  "https://www.scmp.com/rss/92/feed"),
    ("Economy",   "https://www.scmp.com/rss/5/feed"),
]

for name, url in CANDIDATES:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        f = feedparser.parse(urllib.request.urlopen(req, timeout=20).read())
        n = len(f.entries)
        print(f"\n=== {name}  ({n} 条)  {url}")
        for e in f.entries[:5]:
            print("    " + (e.get("title") or "")[:66])
        if n == 0:
            print("    —— 空")
    except Exception as e:
        print(f"\n=== {name}  FAIL {type(e).__name__}  {url}")
