# -*- coding: utf-8 -*-
"""
信源质量体检。check 只验"通不通"，这个验"抓到的是不是该抓的东西"。

一个源可以完美返回 8 条毫不相干的内容，check 全绿，但它在席位表上
一直投废票 —— 在场却从不参与共识，系统性压低共识组数。

    python3 audit.py           # 过去 48 小时
    python3 audit.py 168       # 过去一周

看两列：
  重合率  这个源有多少条被别家也报了。长期为 0 的源要么换 feed，要么删。
  条数    明显低于其他家的，多半 feed 选错了栏目。
"""

import sys
import sqlite3
from datetime import datetime, timezone, timedelta

import build

hours = float(sys.argv[1]) if len(sys.argv) > 1 else 48
con = sqlite3.connect("watch.db")
since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
cur = con.execute(
    "SELECT source_id, source_name, title, rank, first_seen FROM items "
    "WHERE layer='media' AND COALESCE(last_seen, first_seen) >= ?", (since,))
items = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]

groups = build.cluster(items)
paired = set()
for g in groups:
    if len({i["source_id"] for i in g}) >= 2:
        for i in g:
            paired.add(id(i))

by_src = {}
for it in items:
    by_src.setdefault((it["source_id"], it["source_name"]), []).append(it)

print(f"过去 {hours:g} 小时，共 {len(items)} 条\n")
print(f"{'源':<14}{'条数':>5}{'参与共识':>9}{'重合率':>8}")
print("-" * 42)
rows = []
for (sid, name), lst in by_src.items():
    hit = sum(1 for i in lst if id(i) in paired)
    rows.append((hit / len(lst), name, len(lst), hit))
for rate, name, n, hit in sorted(rows, reverse=True):
    flag = "  ← 可疑" if rate == 0 or n < 5 else ""
    print(f"{name:<14}{n:>5}{hit:>9}{rate:>7.0%}{flag}")

missing = {m["name"] for m in build.SEATS} - {n for _, n, _, _ in rows}
if missing:
    print(f"\n完全没有数据：{', '.join(missing)}")
print("\n重合率长期为 0 = 这个席位在投废票，换 feed 或者删掉。")
