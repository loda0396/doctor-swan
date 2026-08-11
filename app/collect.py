# -*- coding: utf-8 -*-
"""
采集层。抓快照 → 落 SQLite。只做这个。

    python3 collect.py check      # feed 体检
    python3 collect.py xcheck     # X 账号体检（会花几分钱）
    python3 collect.py run        # 抓一次快照（含 X）
    python3 collect.py run --no-x # 抓一次，跳过 X（不花钱）
    python3 collect.py stats

固定快照，布鲁塞尔时间：
    0 7,13,19 * * * cd ~/Desktop/learn/watch && /usr/bin/python3 collect.py run
"""

import os
import re
import sys
import time
import json
import sqlite3
import hashlib
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta, timezone

import feedparser

from sources import MEDIA, OFFICIAL, VOICES, TICKER, X_ACCOUNTS, X_TOP_N

DB = "watch.db"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) newsroom-watch/0.2"
FR_API = "https://www.federalregister.gov/api/v1/documents.json"
X_API = "https://api.x.com/2"
XID_CACHE = ".x_ids.json"   # user id 查一次 $0.010，缓存起来，别重复查


# ------------------------------------------------------------------ 存储 ----

def db():
    con = sqlite3.connect(DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id          TEXT PRIMARY KEY,
            layer       TEXT NOT NULL,   -- media | official
            channel     TEXT NOT NULL,   -- web | x
            source_id   TEXT NOT NULL,
            source_name TEXT NOT NULL,
            seat        INTEGER,
            bloc        TEXT,            -- CN | US | EU
            title       TEXT NOT NULL,
            url         TEXT,
            summary     TEXT,
            lang        TEXT,
            published   TEXT,
            rank        INTEGER,
            first_seen  TEXT NOT NULL,
            last_seen   TEXT,
            snapshot    TEXT NOT NULL
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_layer ON items(layer, first_seen)")
    # 老库升级：last_seen 缺省等于 first_seen
    if "last_seen" not in {r[1] for r in con.execute("PRAGMA table_info(items)")}:
        con.execute("ALTER TABLE items ADD COLUMN last_seen TEXT")
    con.execute("UPDATE items SET last_seen=first_seen WHERE last_seen IS NULL")
    con.execute("CREATE INDEX IF NOT EXISTS idx_last ON items(layer, last_seen)")
    con.commit()
    return con


# 快讯层保留多久。财联社 20 条/半小时，一天近千条，
# 而每轮 Actions 都会把整个数据库提交进 git —— 不清理的话仓库一个月涨几百 MB。
# 48 小时之外的快讯没有回看价值，直接删。
TICKER_KEEP_H = 48


def prune(con):
    """删掉过期的快讯。只动 ticker 层，其余三层的历史都留着——
    媒体和官方的历史将来要用来画席位曲线，删了就重建不了。"""
    cut = (datetime.now(timezone.utc) - timedelta(hours=TICKER_KEEP_H)).isoformat()
    n = con.execute(
        "DELETE FROM items WHERE layer='ticker' AND COALESCE(published, first_seen) < ?",
        (cut,)).rowcount
    if n:
        con.commit()
        con.execute("VACUUM")   # 真正回收磁盘空间，否则文件大小不降
    return n


def item_id(source_id, url, title):
    return hashlib.sha1(f"{source_id}|{url or title}".encode("utf-8")).hexdigest()[:16]


def save(con, rows, snapshot):
    """新条目插入；已见过的只更新 last_seen 和位置。

    first_seen = 第一次出现，last_seen = 最后一次还在源里。
    这两个必须分开：BBC 19:00 的头条 22:00 还挂在首页上，
    读 3 小时窗口时该算它在，不该因为"第一次看见是 3 小时前"就消失。
    """
    new = 0
    for r in rows:
        try:
            con.execute(
                "INSERT INTO items (id,layer,channel,source_id,source_name,seat,bloc,"
                "title,url,summary,lang,published,rank,first_seen,last_seen,snapshot) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["id"], r["layer"], r.get("channel", "web"), r["source_id"], r["source_name"],
                 r.get("seat"), r.get("bloc"), r["title"], r.get("url"), r.get("summary"),
                 r.get("lang"), r.get("published"), r.get("rank"), snapshot, snapshot, snapshot))
            new += 1
        except sqlite3.IntegrityError:
            # rank 用当前值，不用历史最好值。
            # 曾经上过头条 ≠ 现在还在头条。用 MIN 会让老新闻永远压着新新闻。
            con.execute("UPDATE items SET last_seen=?, rank=? WHERE id=?",
                        (snapshot, r.get("rank", 99), r["id"]))
    con.commit()
    return new


def _get(url, headers=None, timeout=25):
    # 从 GitHub Actions（美国数据中心 IP）访问时，部分站点会拒绝看起来像
    # 脚本的请求。补齐浏览器会发的那几个头，能过掉一部分简单的检查。
    # 过不掉的（Cloudflare 那类看 TLS 指纹的）只能认，别硬钻。
    h = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "identity",
        "Cache-Control": "no-cache",
    }
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ------------------------------------------------------------- 网页信源 ----

def fetch_rss(src, layer):
    feed = feedparser.parse(_get(src["url"]))
    rows = []
    for i, e in enumerate(feed.entries[: src.get("top_n", 10)]):
        title = (e.get("title") or "").strip()
        if not title:
            continue
        url = e.get("link")
        rows.append(dict(
            id=item_id(src["id"], url, title), layer=layer, channel="web",
            source_id=src["id"], source_name=src["name"], seat=src.get("seat"),
            bloc=src.get("bloc"), title=title, url=url,
            summary=(e.get("summary") or "")[:300],   # 只留一截，我们要的是标题
            lang=src.get("lang"), published=e.get("published") or e.get("updated"), rank=i))
    return rows


def fetch_federal_register(src, layer):
    """读取不需要 API key。type 字段很关键：Rule=已生效，Notice=多为清单类。"""
    params = [("per_page", str(src.get("top_n", 20))), ("order", "newest")]
    for f in ("document_number", "title", "html_url", "publication_date", "type"):
        params.append(("fields[]", f))
    for a in src["agencies"]:
        params.append(("conditions[agencies][]", a))
    data = json.loads(_get(FR_API + "?" + urllib.parse.urlencode(params)).decode("utf-8"))

    rows = []
    for i, d in enumerate(data.get("results", [])):
        title = (d.get("title") or "").strip()
        if not title:
            continue
        rows.append(dict(
            id=item_id(src["id"], d.get("html_url"), title), layer=layer, channel="web",
            source_id=src["id"], source_name=src["name"], bloc=src.get("bloc"),
            title=title, url=d.get("html_url"), summary=d.get("type") or "",
            lang="en", published=d.get("publication_date"), rank=i))
    return rows


WEIBO_API = "https://m.weibo.cn/api/container/getIndex"


def fetch_weibo(src, layer):
    """m.weibo.cn 的容器接口。containerid = 107603 + uid 是"微博"这个 tab。
    不需要登录，但请求太密会被限流——限流时返回空列表而不是报错，
    所以抓到 0 条要当异常看，不要当"今天没发"。"""
    q = urllib.parse.urlencode({
        "type": "uid", "value": src["uid"],
        "containerid": "107603" + src["uid"],
    })
    raw = _get(f"{WEIBO_API}?{q}", {
        "Referer": f"https://m.weibo.cn/u/{src['uid']}",
        "X-Requested-With": "XMLHttpRequest",
        "MWeibo-Pwa": "1",
        "Accept": "application/json, text/plain, */*",
    })
    text = raw.decode("utf-8", errors="replace")
    if not text.lstrip().startswith("{"):
        # 拿到的不是 JSON。多半是验证页或跳转页——把开头打出来才好判断，
        # 别让它变成一个没有线索的 JSONDecodeError。
        raise RuntimeError("微博没返回 JSON，实际开头：" + text.lstrip()[:120].replace("\n", " "))
    data = json.loads(text)
    cards = [c for c in (data.get("data", {}).get("cards") or []) if c.get("card_type") == 9]

    rows = []
    for i, c in enumerate(cards[: src.get("top_n", 8)]):
        mb = c.get("mblog") or {}
        text = re.sub(r"<[^>]+>", "", mb.get("text") or "").strip()
        if not text:
            continue
        url = f"https://m.weibo.cn/detail/{mb.get('id')}"
        rows.append(dict(
            id=item_id(src["id"], url, text), layer=layer, channel="web",
            source_id=src["id"], source_name=src["name"], bloc=src.get("bloc"),
            title=text[:280], url=url, summary="", lang="zh",
            published=mb.get("created_at"), rank=i))
    if not rows:
        raise RuntimeError("微博返回空——多半被限流了，不是没发微博")
    return rows


CLS_API = "https://www.cls.cn/v1/roll/get_roll_list"


def fetch_cls(src, layer):
    """财联社电报。页面是纯前端渲染，静态爬虫抓不到，走它自己的后端接口。

    接口有签名，但算法是固定的：md5(sha1(参数按键名排序后拼接))，
    没有盐也没有密钥。所以可以自己算，用当前时间戳取最新的一批。
    （抓到的 sign 是绑死参数的，直接复用只能永远拿到那一刻的 20 条。）

    这个签名方式随时可能被改。哪天返回 errno != 0，先怀疑这里。
    """
    params = {
        "app": "CailianpressWeb",
        "last_time": str(int(time.time())),
        "os": "web",
        "refresh_type": "1",
        "rn": str(src.get("top_n", 20)),
        "sv": "8.7.9",
    }
    raw = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    params["sign"] = hashlib.md5(
        hashlib.sha1(raw.encode()).hexdigest().encode()).hexdigest()

    url = f"{CLS_API}?{urllib.parse.urlencode(sorted(params.items()))}"
    data = json.loads(_get(url, {"Referer": "https://www.cls.cn/telegraph"}).decode("utf-8"))
    if data.get("errno"):
        raise RuntimeError(f"财联社接口返回 errno={data['errno']}，签名算法可能变了")

    rows = []
    for i, x in enumerate(data.get("data", {}).get("roll_data") or []):
        title = (x.get("title") or x.get("content") or "").strip()
        if not title:
            continue
        ts = x.get("ctime")
        rows.append(dict(
            id=item_id(src["id"], x.get("shareurl") or str(x.get("id")), title),
            layer=layer, channel="web", source_id=src["id"], source_name=src["name"],
            bloc=src.get("bloc"), title=title[:200],
            url=x.get("shareurl") or f"https://www.cls.cn/detail/{x.get('id')}",
            summary="", lang="zh",
            published=datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None,
            rank=i))
    return rows


def fetch(src, layer):
    k = src["kind"]
    if k == "rss":
        return fetch_rss(src, layer)
    if k == "federal_register":
        return fetch_federal_register(src, layer)
    if k == "weibo":
        return fetch_weibo(src, layer)
    if k == "cls":
        return fetch_cls(src, layer)
    if k == "scrape":
        import scrape
        rows = []
        for i, r in enumerate(scrape.fetch_scrape(src, layer)):
            rows.append(dict(
                id=item_id(src["id"], r["url"], r["title"]), layer=layer, channel="web",
                source_id=src["id"], source_name=src["name"], seat=src.get("seat"),
                bloc=src.get("bloc"), title=r["title"], url=r["url"], summary="",
                lang=src.get("lang"), published=None, rank=i))
        return rows
    raise ValueError(f"未知 kind: {k}")


# ------------------------------------------------------------------- X ----

def x_token():
    t = os.environ.get("X_BEARER_TOKEN")
    if not t:
        raise RuntimeError("没有 X_BEARER_TOKEN 环境变量。export 一下，或者用 run --no-x")
    return t


def x_user_ids(handles):
    """handle → id。查一次缓存到本地，之后不再花钱。"""
    cache = {}
    if os.path.exists(XID_CACHE):
        cache = json.load(open(XID_CACHE, encoding="utf-8"))
    missing = [h for h in handles if h not in cache]
    if missing:
        hdr = {"Authorization": f"Bearer {x_token()}"}
        for chunk in [missing[i:i + 100] for i in range(0, len(missing), 100)]:
            url = f"{X_API}/users/by?usernames={','.join(chunk)}"
            data = json.loads(_get(url, hdr).decode("utf-8"))
            for u in data.get("data", []):
                cache[u["username"]] = u["id"]
            for err in data.get("errors", []):
                print(f"  X 账号无效: {err.get('value')} — {err.get('detail','')[:60]}")
        json.dump(cache, open(XID_CACHE, "w", encoding="utf-8"))
    return cache


def fetch_x():
    handles = [a["handle"] for a in X_ACCOUNTS]
    ids = x_user_ids(handles)
    hdr = {"Authorization": f"Bearer {x_token()}"}
    rows = []
    for acc in X_ACCOUNTS:
        uid = ids.get(acc["handle"])
        if not uid:
            continue
        q = urllib.parse.urlencode({
            "max_results": max(5, X_TOP_N),
            "tweet.fields": "created_at",
            "exclude": "retweets,replies",   # 转推和回复不算发布，别花这个钱
        })
        try:
            data = json.loads(_get(f"{X_API}/users/{uid}/tweets?{q}", hdr).decode("utf-8"))
        except urllib.error.HTTPError as e:
            print(f"  X {acc['handle']}: HTTP {e.code}")
            continue
        for i, t in enumerate((data.get("data") or [])[:X_TOP_N]):
            text = (t.get("text") or "").strip()
            if not text:
                continue
            url = f"https://x.com/{acc['handle']}/status/{t['id']}"
            rows.append(dict(
                id=item_id("x_" + acc["handle"], url, text), layer="voice", channel="x",
                source_id="x_" + acc["handle"], source_name=acc["name"], bloc=acc["bloc"],
                title=text[:280], url=url, summary="@" + acc["handle"],
                lang="en", published=t.get("created_at"), rank=i))
    return rows


def fetch_voice_rss():
    """观点栏里走 RSS 的部分：newsletter、自媒体。免费，先跑这些。"""
    rows = []
    for src in VOICES:
        if src["kind"] != "rss":
            continue
        try:
            rows += fetch_rss(src, "voice")
        except Exception as e:
            print(f"  跳过 {src['name']}: {type(e).__name__}")
    for r in rows:
        r["channel"] = "post"
    return rows


# ------------------------------------------------------------------ 命令 ----

def cmd_check():
    print(f"{'源':<16}{'层':<10}{'条数':<7}首条")
    print("-" * 80)
    dead = []
    voice_rss = [v for v in VOICES if v["kind"] == "rss"]
    for layer, group in (("media", MEDIA), ("official", OFFICIAL),
                         ("voice", voice_rss), ("ticker", TICKER)):
        for src in group:
            try:
                rows = fetch(src, layer)
                if not rows:
                    dead.append(src["id"])
                    print(f"{src['name']:<16}{layer:<10}{'0':<7}空 feed，检查 URL")
                else:
                    print(f"{src['name']:<16}{layer:<10}{len(rows):<7}{rows[0]['title'][:42]}")
            except NotImplementedError as e:
                dead.append(src["id"])
                print(f"{src['name']:<16}{layer:<10}{'TODO':<7}{e}")
            except Exception as e:
                dead.append(src["id"])
                print(f"{src['name']:<16}{layer:<10}{'FAIL':<7}{type(e).__name__}: {str(e)[:38]}")
    print("-" * 80)
    if dead:
        print("需要处理：" + ", ".join(dead))
        print("媒体层每死一个席位，'缺席即信号'就少一分可信度。修好或换人，别留空席位。")
    else:
        print("全部正常。")


def cmd_xcheck():
    print(f"要验 {len(X_ACCOUNTS)} 个账号，约 ${len(X_ACCOUNTS) * 0.010:.2f}")
    if input("继续？[y/N] ").strip().lower() != "y":
        return
    ids = x_user_ids([a["handle"] for a in X_ACCOUNTS])
    for a in X_ACCOUNTS:
        mark = "ok  " if a["handle"] in ids else "失效"
        print(f"  {mark} @{a['handle']:<20}{a['name']}")


def cmd_run(with_x=True):
    snapshot = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    con = db()
    total = 0
    voice_rss = [v for v in VOICES if v["kind"] == "rss"]
    for layer, group in (("media", MEDIA), ("official", OFFICIAL),
                         ("voice", voice_rss), ("ticker", TICKER)):
        for src in group:
            try:
                rows = fetch(src, layer)
            except Exception as e:
                print(f"  跳过 {src['name']}: {type(e).__name__}")
                continue
            if layer == "voice":
                for r in rows:
                    r["channel"] = "post"
            n = save(con, rows, snapshot)
            total += n
            print(f"  {src['name']:<16}抓 {len(rows):>2}  新 {n:>2}")
    if with_x:
        try:
            rows = fetch_x()
            n = save(con, rows, snapshot)
            total += n
            print(f"  {'X':<16}抓 {len(rows):>2}  新 {n:>2}  ≈ ${len(rows) * 0.005:.2f}")
        except Exception as e:
            print(f"  跳过 X: {e}")
    gone = prune(con)
    if gone:
        print(f"  {'清理':<16}删除 {gone} 条过期快讯")
    print(f"\n快照 {snapshot}，新增 {total} 条")
    con.close()


def cmd_stats():
    con = db()
    for layer in ("media", "official", "voice", "ticker"):
        n = con.execute("SELECT COUNT(*) FROM items WHERE layer=?", (layer,)).fetchone()[0]
        print(f"{layer:<10}{n} 条")
    print()
    for name, c in con.execute(
            "SELECT source_name, COUNT(*) c FROM items GROUP BY source_id ORDER BY c DESC"):
        print(f"  {name:<18}{c}")
    snaps = con.execute("SELECT COUNT(DISTINCT snapshot) FROM items").fetchone()[0]
    print(f"\n共 {snaps} 次快照")
    con.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else "check"
    if cmd == "run":
        cmd_run(with_x="--no-x" not in args)
    else:
        {"check": cmd_check, "xcheck": cmd_xcheck, "stats": cmd_stats}[cmd]()
