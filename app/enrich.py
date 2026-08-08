# -*- coding: utf-8 -*-
"""
加工层。把原始条目变成可读的：直译中文标题 + 地区归属。

    export ANTHROPIC_API_KEY=sk-ant-xxxx
    python3 enrich.py            # 处理所有还没加工的条目
    python3 enrich.py --dry      # 只看要处理多少条、大概多少钱，不调用

规矩（已经写进 prompt，别改松了）：
  · 只直译，不概括、不改写、不加评价、不加背景
  · 专有名词按通行译法；拿不准的人名保留原文
  · 原标题永远保留，卡片上一直挂着，点进去是原文

地区判断的是**内容涉及谁**，不是**谁报的**。
BBC 报中美贸易战 → region=CN, region2=US，跟 BBC 是英国媒体无关。
既不中也不美也不欧的（中东、乌克兰、非洲……）一律 OTHER，显示成灰色。
硬把它们塞进红蓝绿里，比不上色更糟。

成本：Haiku，一次 20 条，每条大约 0.0001 美元量级。
一天 100 条新增，一个月不到 1 块钱。真正贵的是 X，不是这里。
"""

import os
import re
import sys
import json
import time
import sqlite3
import urllib.request

DB = "watch.db"
API = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"   # 标题直译够用。要更稳可换 claude-sonnet-4-6
BATCH = 20

SYSTEM = """你是新闻监测系统的翻译与标注模块。给你一批新闻标题，逐条处理。

对每条输出：
1. zh —— 标题的中文直译。严格直译：
   - 不概括、不改写、不润色、不加背景、不加评价
   - 保留原句的语序和信息量，原文没说的一个字都不许加
   - 专有名词用通行译法；拿不准的人名、机构名保留原文不译
   - 原文本身是中文的，原样返回
2. region —— 这条新闻**内容涉及**的主要地区，四选一：
   CN（中国）US（美国）EU（欧洲，含英国及欧洲国家）OTHER（其他一切）
   判断依据是新闻讲的是谁，不是谁报道的。
3. region2 —— 次要涉及地区，同样四选一。只涉及一个地区时填 null。
   中美、中欧、美欧这类双边新闻必须填全两个。

只返回 JSON 数组，不要 markdown 代码块，不要任何解释。
格式：[{"i":0,"zh":"...","region":"CN","region2":"US"}, ...]

JSON 转义规则（很重要，之前在这里出过错）：
- zh 字段里如果要用引号，一律用中文引号 「」或""，绝不要用英文双引号 "
- 原标题里的英文单双引号，译文中改成中文引号
- 不要在字符串里放换行"""


def check_key():
    """请求头只能是 ASCII。key 里混进中文/全角字符会炸在 urllib 里，
    报出来的 latin-1 错误跟真实原因隔了两层，所以这里提前拦住。"""
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "没有 ANTHROPIC_API_KEY。先 export，注意要用真实的 key，"
            "不要照抄示例里的占位文字。")
    bad = [(i, c) for i, c in enumerate(key) if ord(c) > 127]
    if bad:
        raise RuntimeError(
            f"key 里有非 ASCII 字符（第 {bad[0][0]} 位是 '{bad[0][1]}'）。"
            "多半是把示例里的占位文字一起复制了，换成真实 key。")
    if not key.startswith("sk-ant-"):
        raise RuntimeError(f"key 格式不像（开头是 '{key[:8]}'），应该以 sk-ant- 开头。")
    return key


def call(titles):
    key = check_key()
    payload = json.dumps({
        "model": MODEL,
        "max_tokens": 4000,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": json.dumps(
            [{"i": i, "title": t} for i, t in enumerate(titles)], ensure_ascii=False)}],
    }).encode("utf-8")
    req = urllib.request.Request(API, data=payload, headers={
        "content-type": "application/json",
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
    })
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.loads(r.read().decode("utf-8"))
    text = "".join(b.get("text", "") for b in data.get("content", []))
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 整块解析失败，通常是某一条的译文里混了没转义的引号。
        # 逐个对象抢救——坏掉一条不该让同批另外 19 条陪葬。
        out = []
        for m in re.finditer(r"\{[^{}]*\}", text):
            try:
                out.append(json.loads(m.group()))
            except json.JSONDecodeError:
                continue
        if not out:
            raise
        print(f"    （本批 JSON 有破损，抢救回 {len(out)} 条）")
        return out


def migrate(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(items)")}
    for c, t in (("title_zh", "TEXT"), ("region", "TEXT"),
                 ("region2", "TEXT"), ("enriched", "INTEGER DEFAULT 0")):
        if c not in cols:
            con.execute(f"ALTER TABLE items ADD COLUMN {c} {t}")
    con.commit()


def main(dry=False):
    if not dry:
        check_key()      # 先验 key，别等跑到一半才发现
    con = sqlite3.connect(DB)
    migrate(con)
    rows = con.execute(
        "SELECT id, title FROM items WHERE enriched IS NULL OR enriched = 0").fetchall()
    print(f"待加工 {len(rows)} 条，{(len(rows) + BATCH - 1) // BATCH} 次调用")
    if dry or not rows:
        return

    done = 0
    for k in range(0, len(rows), BATCH):
        chunk = rows[k:k + BATCH]
        try:
            res = call([t for _, t in chunk])
        except Exception as e:
            print(f"  批 {k // BATCH + 1} 失败：{type(e).__name__}: {str(e)[:70]}")
            time.sleep(2)
            continue
        for r in res:
            i = r.get("i")
            if i is None or i >= len(chunk):
                continue
            r2 = r.get("region2")
            r2 = None if r2 in ("null", "", "NONE") else r2
            con.execute(
                "UPDATE items SET title_zh=?, region=?, region2=?, enriched=1 WHERE id=?",
                (r.get("zh"), r.get("region") or "OTHER", r2, chunk[i][0]))
            done += 1
        con.commit()
        print(f"  批 {k // BATCH + 1}/{(len(rows) + BATCH - 1) // BATCH} 完成")

    print(f"\n加工完成 {done}/{len(rows)} 条")
    # 没成功的下次还会被捞出来重试，不会丢
    con.close()


if __name__ == "__main__":
    main(dry="--dry" in sys.argv)
