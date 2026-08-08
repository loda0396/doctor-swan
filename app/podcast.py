# -*- coding: utf-8 -*-
"""
播客 RSS 查找器。播客的 feed 地址是托管商生成的，猜不出来，用苹果的
公开检索接口查（免费、不要 key）。

    python3 podcast.py "All-In"
    python3 podcast.py "The Long Game"

打印候选节目和它们的 RSS 地址，挑对的那个，把 url 填进 sources.py 的 VOICES。

同名节目很多，注意看 作者 和 最新更新时间 —— 停更的节目更新时间会很旧。
"""

import sys
import json
import urllib.parse
import urllib.request

API = "https://itunes.apple.com/search"


def find(term, limit=6):
    q = urllib.parse.urlencode({
        "term": term, "entity": "podcast", "limit": limit, "country": "US"})
    with urllib.request.urlopen(f"{API}?{q}", timeout=25) as r:
        data = json.loads(r.read().decode("utf-8"))

    hits = [x for x in data.get("results", []) if x.get("feedUrl")]
    if not hits:
        print(f"没找到「{term}」，换个说法试试")
        return

    for x in hits:
        print(f"\n  {x.get('collectionName')}")
        print(f"    作者   {x.get('artistName')}")
        print(f"    更新   {(x.get('releaseDate') or '')[:10]}   共 {x.get('trackCount')} 期")
        print(f"    RSS    {x['feedUrl']}")
    print("\n把对的那条 RSS 地址填进 sources.py 的 VOICES。")


if __name__ == "__main__":
    find(" ".join(sys.argv[1:]) or "news")
