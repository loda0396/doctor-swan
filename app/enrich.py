# -*- coding: utf-8 -*-
"""
加工层。给每条新闻判断**内容涉及哪个地区**。只做这一件事。

曾经这里还负责把标题直译成中文，2026-10 去掉了：标题展示原文，
译文这一环不再需要。顺带解决了一个长期的毛病——以前批量失败多半是
译文里混进英文引号把 JSON 撑破了，现在输出里没有自由文本，不会再有。

去掉翻译但**必须保留分类**：地区着色（中红/美蓝/欧绿/其他灰）和顶部
的地区筛选全靠 region 字段，它跟翻译本来是同一次调用做的，
一起删掉的话整个配色体系会跟着消失。

    export ANTHROPIC_API_KEY=sk-ant-xxxx
    python3 enrich.py            # 处理所有还没加工的条目
    python3 enrich.py --dry      # 只看要处理多少条、大概多少钱，不调用

地区判断的是**内容涉及谁**，不是**谁报的**。
BBC 报中美贸易战 → region=CN, region2=US，跟 BBC 是英国媒体无关。
既不中也不美也不欧的（中东、乌克兰、非洲……）一律 OTHER，显示成灰色。
硬把它们塞进红蓝绿里，比不上色更糟。

成本：比带翻译时更低——输出从「一句译文 + 两个标签」缩到只剩两个标签，
输出 token 降一个量级。一天几百条，一个月几毛钱。
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
MODEL = "claude-haiku-4-5-20251001"   # 判断地区够用
BATCH = 40   # 不再输出译文，每条的输出变得很短，一批可以塞更多

SYSTEM = """你是新闻监测系统的地区标注模块。给你一批新闻标题，逐条判断它涉及哪个地区。

对每条输出：
1. region —— 这条新闻**内容涉及**的主要地区，四选一：
   CN（中国）US（美国）EU（欧洲，含英国及欧洲国家）OTHER（其他一切）
   判断依据是新闻讲的是谁，不是谁报道的。
   BBC 报中美贸易战 → CN，跟 BBC 是英国媒体无关。
2. region2 —— 次要涉及地区，同样四选一。只涉及一个地区时填 null。
   中美、中欧、美欧这类双边新闻必须填全两个。

中东、乌克兰、非洲、拉美这些既不中也不美也不欧的，一律 OTHER。
硬塞进红蓝绿里比不上色更糟——OTHER 显示成灰色，那是诚实的。

只返回 JSON 数组，不要 markdown 代码块，不要任何解释，不要翻译标题。
格式：[{"i":0,"region":"CN","region2":"US"}, ...]"""


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
        # 整块解析失败时逐个对象抢救。去掉译文后输出里没有自由文本，
        # 这条路基本不会再走到，但留着不碍事。
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
    print(f"待分类 {len(rows)} 条，{(len(rows) + BATCH - 1) // BATCH} 次调用")
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
            # title_zh 这一列留着不动：老数据里的译文还在，只是不再写新的，
            # 前端也不再读它。要彻底清掉就单独跑一次 UPDATE，不急。
            con.execute(
                "UPDATE items SET region=?, region2=?, enriched=1 WHERE id=?",
                (r.get("region") or "OTHER", r2, chunk[i][0]))
            done += 1
        con.commit()
        print(f"  批 {k // BATCH + 1}/{(len(rows) + BATCH - 1) // BATCH} 完成")

    print(f"\n分类完成 {done}/{len(rows)} 条")
    # 没成功的下次还会被捞出来重试，不会丢
    con.close()


if __name__ == "__main__":
    main(dry="--dry" in sys.argv)
