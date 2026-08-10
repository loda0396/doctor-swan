# -*- coding: utf-8 -*-
"""
生成层。卡片网格，两大类。

  媒体关注   一个故事簇 = 一张卡，卡上带席位条
  官方发布   一条 = 一张卡

配色按新闻**内容涉及的地区**：中红 / 美蓝 / 欧绿 / 其他灰。
双边新闻（中美、中欧…）顶条做两段拼色。

    python3 build.py
    python3 build.py --hours 12
    python3 build.py --demo
"""

import re
import sys
import html
import sqlite3
from datetime import datetime, timezone, timedelta

from sources import MEDIA, VOICES, OFFICIAL, TICKER

DB, OUT = "watch.db", "dashboard.html"

# 格子数跟席位数走。写死 10 而实际只有 9 席时，第十格永远靠补位卡撑着——
# 那一格从设计上就注定是填充物，不是信号。
MEDIA_SLOTS = len(MEDIA)
# 官方发布：按发布方分名额。中美各 3 格才装得下"贸易+外交+关税"三条线，
# 2 格的话每天最新两条一压，其余全看不见。数字随时可改。
OFFICIAL_QUOTA = [("CN", 3), ("US", 3), ("EU", 2)]
SEATS = sorted(MEDIA, key=lambda s: s["seat"])
COMPARABLE = {s["id"] for s in SEATS if s["lang"] == "en"}
# 付费墙：点进去要不要花力气，点之前就该知道
PAYWALL = {x["id"]: x["paywall"] for x in MEDIA + VOICES if x.get("paywall")}
PW_LABEL = {"hard": "付费墙", "metered": "限次"}
# 只显示当前配置里还留着的源。删掉的源，历史数据还在库里，但不该再出现。
LIVE_IDS = ({m["id"] for m in MEDIA} | {o["id"] for o in OFFICIAL}
            | {v["id"] for v in VOICES} | {t["id"] for t in TICKER})
# 四层的时间尺度完全不同，用同一个窗口是错的：
VOICE_WINDOW_H  = 24 * 7   # 观点：周更的 newsletter，一周窗口
MEDIA_WINDOW_H  = 48       # 媒体：48 小时上限，过期的头条只是噪音
TICKER_WINDOW_H = 0.5      # 快讯：30 分钟，它的全部价值就是"刚刚"

REGION = {
    "CN":    dict(label="中", color="#E0524A"),
    "US":    dict(label="美", color="#5B9DDB"),
    "EU":    dict(label="欧", color="#55B98A"),
    "OTHER": dict(label="其他", color="#6C757D"),
}

STOP = set("""a an the and or but of in on at to for from with by as is are was were be been
being it its this that these those has have had will would can could should may might do does
did not no new says said say after before over under about into out up down more most than then
who what when where why how his her their our your they them he she we you i""".split())


# ------------------------------------------------------------------ 聚类 ----

def tokens(t):
    return {w for w in re.sub(r"[^\w\s'-]", " ", t.lower()).split()
            if len(w) > 2 and w not in STOP}


def propers(t):
    w = re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", t)
    return set(w[1:]) if w else set()


def similar(a, b):
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    j = len(ta & tb) / len(ta | tb)
    if j >= 0.28:
        return True
    return len(propers(a) & propers(b)) >= 2 and j >= 0.14


def cluster(items):
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i]["source_id"] == items[j]["source_id"]:
                continue
            if similar(items[i]["title"], items[j]["title"]):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
    g = {}
    for i, it in enumerate(items):
        g.setdefault(find(i), []).append(it)
    return list(g.values())


def load(con, layer, hours):
    """三层的时间语义不一样，不能用同一个窗口：

      media    看 last_seen —— "过去 N 小时里它还挂在人家首页上"。
               用 first_seen 是错的：19:00 抓到的头条 22:00 还在，
               但"第一次看见"在窗口外，席位条就会凭空少掉一格。
      official 不设窗口 —— BIS 三天前的实体清单今天仍是最新的一条。
               该问的是"各方最新动作是什么"，不是"这三小时发生了什么"。
      voice    一周窗口 —— 周更的 newsletter 在三小时窗口里必然为空。
    """
    cols = {r[1] for r in con.execute("PRAGMA table_info(items)")}
    extra = ",".join(c for c in ("title_zh", "region", "region2", "last_seen") if c in cols)
    sel = ("source_id,source_name,channel,seat,bloc,title,url,summary,lang,"
           "published,rank,first_seen") + ("," + extra if extra else "")

    if layer == "official":
        # 官方层不设窗口。它回答的是"各方最新立场是什么"，不是"最近发生了什么"。
        # 外交部上一条谈话答问可能是三周前，但只要没发新的，那就仍是当前状态。
        # 设上限会让中国那几格经常空着，你会误读成"中方没动静"。
        # 陈旧用标记表达（"23 天前"），不用消失表达。
        q, args = f"SELECT {sel} FROM items WHERE layer=?", ("official",)
    else:
        h = {"voice": VOICE_WINDOW_H,
             "media": MEDIA_WINDOW_H,
             "ticker": TICKER_WINDOW_H}.get(layer, float(hours))
        since = (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()

        if layer == "ticker":
            # 快讯按**发布时间**筛，不按 last_seen。
            # 财联社每次返回最新 20 条，12 点那条只要还在这 20 条里，
            # last_seen 就一直被刷新，会永远赖在 30 分钟窗口里。
            # 窗口要问的是"它什么时候发生"，不是"我们什么时候看到它"。
            q = f"SELECT {sel} FROM items WHERE layer=? AND published >= ?"
        else:
            # 媒体相反：要的是"过去 N 小时它还挂在人家首页上"，所以看 last_seen。
            field = "last_seen" if "last_seen" in cols else "first_seen"
            q = (f"SELECT {sel} FROM items WHERE layer=? "
                 f"AND COALESCE({field}, first_seen) >= ?")
        args = (layer, since)

    cur = con.execute(q + " ORDER BY first_seen DESC, rank ASC", args)
    names = [d[0] for d in cur.description]
    rows = [dict(zip(names, r)) for r in cur.fetchall()]
    return [r for r in rows if r["source_id"] in LIVE_IDS]


def when(it):
    """published 的格式三种混用（ISO / 日期 / RFC822），统一成可排序的日期串。
    解析不出来就退回 first_seen —— 宁可退化排序，不要把条目丢掉。"""
    p = (it.get("published") or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", p):
        return p[:19]
    m = re.match(r"^[A-Za-z]{3},\s*(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", p)
    if m:
        mon = ["Jan","Feb","Mar","Apr","May","Jun",
               "Jul","Aug","Sep","Oct","Nov","Dec"].index(m.group(2)) + 1
        return f"{m.group(3)}-{mon:02d}-{int(m.group(1)):02d}"
    return (it.get("first_seen") or "")[:19]


# ------------------------------------------------------------------ 样式 ----

CSS = """
:root{
  --ground:#101316; --card:#191D21; --line:#272D33; --line2:#333A41;
  --ink:#E9E7E2; --dim:#9AA1A8; --faint:#616970;
  --cn:#E0524A; --us:#5B9DDB; --eu:#55B98A; --other:#6C757D;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Noto Sans CJK SC",sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}
.wrap{max-width:1400px;margin:0 auto;padding:22px 18px 70px}
header{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;
  flex-wrap:wrap;border-bottom:1px solid var(--line);padding-bottom:13px;margin-bottom:16px}
.brand{display:flex;align-items:flex-end;gap:11px}
.brand svg{flex:none;margin-bottom:3px}
/* 整页只有名字用衬线体。仪表盘是冷的，名字是暖的——这一处对比是刻意的。 */
h1{margin:0;font-family:Didot,"Bodoni 72","Hoefler Text",Baskerville,Georgia,serif;
  font-size:27px;font-weight:400;letter-spacing:.055em;line-height:1;color:var(--ink)}
h1 em{font-style:italic;letter-spacing:.02em}
.sub{font-family:var(--mono);font-size:9.5px;letter-spacing:.24em;color:var(--faint);
  text-transform:uppercase;margin:0 0 4px}
.stamp{font-family:var(--mono);font-size:11px;color:var(--faint)}

.filters{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:26px}
.f{font-family:var(--mono);font-size:11px;letter-spacing:.06em;padding:5px 12px;
  border:1px solid var(--line2);border-radius:3px;background:none;color:var(--dim);
  cursor:pointer}
.f:hover{color:var(--ink)}
.f[aria-pressed="true"]{background:var(--ink);border-color:var(--ink);color:var(--ground);
  font-weight:600}
.f[data-r="CN"]{border-color:var(--cn);color:var(--cn)}
.f[data-r="US"]{border-color:var(--us);color:var(--us)}
.f[data-r="EU"]{border-color:var(--eu);color:var(--eu)}
.f[data-r="CN"][aria-pressed="true"]{background:var(--cn);border-color:var(--cn);color:#101316}
.f[data-r="US"][aria-pressed="true"]{background:var(--us);border-color:var(--us);color:#101316}
.f[data-r="EU"][aria-pressed="true"]{background:var(--eu);border-color:var(--eu);color:#101316}

h2{font-size:11px;font-weight:600;letter-spacing:.16em;text-transform:uppercase;
  color:var(--dim);margin:0 0 4px;font-family:var(--mono)}
section+section{margin-top:44px}
.note{font-size:12px;color:var(--faint);margin:0 0 14px}

.layout{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:26px;align-items:start}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}

/* 右侧观点栏。跟左边不是一回事：那边是事实和注意力，这边是观点。 */
.rail{position:sticky;top:16px;max-height:calc(100vh - 32px);overflow-y:auto;
  padding-right:4px;scrollbar-width:thin}
.rail h2{margin-bottom:4px}
.v{border-left:3px solid var(--c1);padding:9px 0 9px 10px;margin-bottom:2px;
  border-bottom:1px solid var(--line)}
.v.dual{border-image:linear-gradient(180deg,var(--c1) 0 50%,var(--c2) 50% 100%) 1;
  border-left-width:3px;border-bottom:1px solid var(--line)}
.v:last-child{border-bottom:none}
.v .who{font-family:var(--mono);font-size:9.5px;color:var(--dim);letter-spacing:.05em;
  display:flex;gap:6px;align-items:center;margin-bottom:4px}
.v .who .h{color:var(--faint)}
.v .who .dot{width:5px;height:5px;border-radius:50%;background:var(--c1);flex:none}
.v .zh2{font-size:13px;line-height:1.42;margin:0 0 4px}
.v .zh2 a{color:var(--ink);text-decoration:none}
.v .zh2 a:hover{color:var(--c1)}
.v .orig2{font-size:10.5px;line-height:1.4;color:var(--faint);font-family:var(--mono);
  margin:0 0 4px}
.v time{font-family:var(--mono);font-size:9px;color:var(--faint)}

.card{background:var(--card);border:1px solid var(--line);border-radius:4px;
  padding:13px 14px 12px;position:relative;overflow:hidden}
.card::before{content:"";position:absolute;inset:0 0 auto 0;height:3px;background:var(--c1)}
.card.dual::before{background:linear-gradient(90deg,var(--c1) 0 50%,var(--c2) 50% 100%)}
.card.x{border-style:dashed}          /* 虚线边＝X，实线＝机构发布 */

.tags{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:2px 0 8px}
.tag{font-family:var(--mono);font-size:9.5px;letter-spacing:.07em;padding:2px 6px;
  border-radius:2px;background:var(--c1);color:#101316;font-weight:600}
.tag.b{background:none;border:1px solid var(--line2);color:var(--dim);font-weight:400}
.tag.hits{background:none;border:1px solid var(--ink);color:var(--ink);font-weight:600}
.tag.solo{background:none;border:1px dashed var(--faint);color:var(--faint);font-weight:400}
.tag.pw{background:none;border:1px solid var(--faint);color:var(--faint);font-weight:400}
.v .pw2{font-size:8.5px;color:var(--faint);border:1px solid var(--line2);
  border-radius:2px;padding:0 3px}
.card.solo{background:#15181B}
.card.solo .zh{font-weight:400;font-size:14px}
.card.hollow{background:none;border-style:dashed;opacity:.5}
.card.hollow .zh{color:var(--faint)}

.zh{font-size:15px;line-height:1.4;margin:0 0 6px;font-weight:500}
.zh a{color:var(--ink);text-decoration:none}
.zh a:hover{color:var(--c1)}
.orig{font-size:11.5px;line-height:1.4;color:var(--faint);margin:0 0 9px;
  font-family:var(--mono)}
.foot{display:flex;justify-content:space-between;align-items:center;gap:8px;
  font-family:var(--mono);font-size:9.5px;color:var(--faint);letter-spacing:.04em;
  border-top:1px solid var(--line);padding-top:8px;margin-top:2px}
.foot a{color:var(--dim);text-decoration:none}
.foot a:hover{color:var(--ink)}

.seats{display:flex;gap:2px;flex-wrap:wrap;margin:0 0 9px}
.seat{min-width:40px;height:18px;padding:0 3px;border:1px solid var(--line2);border-radius:2px;
  font-family:var(--mono);font-size:8.5px;display:flex;align-items:center;
  justify-content:center;color:var(--faint)}
.seat.on{background:var(--ink);border-color:var(--ink);color:var(--card);font-weight:600}
.seat.unknown{border-style:dashed}
.alt{margin:0 0 9px;padding:0;list-style:none;border-left:1px solid var(--line2);
  padding-left:9px}
.alt li{font-size:11.5px;color:var(--dim);padding:1px 0}
.alt .s{font-family:var(--mono);font-size:9px;color:var(--faint);margin-right:6px}
.alt a{color:inherit;text-decoration:none}
.alt a:hover{color:var(--ink)}

/* 快讯带：紧挨官方发布，同是"发生了什么"，但频率高一个量级，
   所以给窄条不给卡片，密度换视觉重量。 */
.ticker{border-left:3px solid var(--cn);background:var(--card);border-radius:0 4px 4px 0;
  max-height:290px;overflow-y:auto;scrollbar-width:thin}
.tick{display:flex;gap:10px;padding:7px 12px;border-bottom:1px solid var(--line);
  font-size:12.5px;line-height:1.4}
.tick:last-child{border-bottom:none}
.tick time{font-family:var(--mono);font-size:9.5px;color:var(--faint);flex:none;
  padding-top:2px;min-width:34px}
.tick a{color:var(--ink);text-decoration:none}
.tick a:hover{color:var(--cn)}
/* 陈旧标记：越久越暗，但不用红色——"三天没发布"是常态不是故障 */
.age{margin-left:7px;padding:1px 5px;border:1px solid var(--line2);border-radius:2px;
  color:var(--faint);font-size:9px}
.empty{color:var(--faint);font-size:12.5px}
@media (max-width:980px){.layout{grid-template-columns:1fr}
  .rail{position:static;max-height:none;margin-top:38px}}
@media (max-width:560px){
  .wrap{padding:16px 13px 60px}
  h1{font-size:23px}
  .grid{grid-template-columns:1fr;gap:10px}
  /* 11 格席位条在窄屏上必须缩，否则换行三次，图形读不出来 */
  .seat{min-width:0;flex:1 1 0;height:17px;padding:0 2px;font-size:7.5px}
  .card{padding:11px 12px 10px}
  .zh{font-size:15px}
  .filters{position:sticky;top:0;z-index:5;background:var(--ground);
    padding:8px 0;margin-bottom:16px}
  header{align-items:flex-start}
}
footer{margin-top:50px;padding-top:13px;border-top:1px solid var(--line);
  font-size:11.5px;color:var(--faint);line-height:1.75}
"""

JS = """
const btns=document.querySelectorAll('.f');
btns.forEach(b=>b.addEventListener('click',()=>{
  btns.forEach(o=>o.setAttribute('aria-pressed',o===b));
  const r=b.dataset.r;
  document.querySelectorAll('.card,.v').forEach(c=>{
    c.style.display=(r==='ALL'||c.dataset.r1===r||c.dataset.r2===r)?'':'none';
  });
}));
"""


def esc(s):
    return html.escape(s or "")


def rcolor(r):
    return REGION.get(r or "OTHER", REGION["OTHER"])["color"]


def card_open(r1, r2, extra=""):
    dual = bool(r2) and r2 != r1
    cls = "card dual" if dual else "card"
    style = f"--c1:{rcolor(r1)};--c2:{rcolor(r2)}"
    return (f'<article class="{cls} {extra}" style="{style}" '
            f'data-r1="{r1 or "OTHER"}" data-r2="{r2 or ""}">')


def region_tags(r1, r2):
    out = [f'<span class="tag">{REGION.get(r1 or "OTHER", REGION["OTHER"])["label"]}</span>']
    if r2 and r2 != r1:
        out.append(f'<span class="tag" style="background:{rcolor(r2)}">'
                   f'{REGION.get(r2, REGION["OTHER"])["label"]}</span>')
    return "".join(out)


def seat_bar(present):
    c = []
    for s in SEATS:
        lbl = esc(s["name"][:11])
        if s["id"] in present:
            c.append(f'<span class="seat on" title="{esc(s["name"])}：上了头条">{lbl}</span>')
        elif s["id"] in COMPARABLE:
            c.append(f'<span class="seat" title="{esc(s["name"])}：没上头条">{lbl}</span>')
        else:
            c.append(f'<span class="seat unknown" title="{esc(s["name"])}：无法比对">{lbl}</span>')
    return '<div class="seats">' + "".join(c) + "</div>"


def pw_tag(source_id):
    m = PAYWALL.get(source_id)
    return f'<span class="tag pw">{PW_LABEL[m]}</span>' if m else ""


def zh_of(it):
    """有译文用译文，没有就退回原文——绝不留空，也绝不假装翻过。"""
    return it.get("title_zh") or it["title"]


def _neg_time(it):
    """把时间串变成可以"越新越小"的排序键。"""
    return tuple(-ord(c) for c in (it.get("last_seen") or it["first_seen"])[:19])


def render_media(items):
    """固定 MEDIA_SLOTS 格。共识簇优先，不够用单家头条补位。
    返回 (html, 共识组数, 补位数) —— 组数本身是信号，要显示出来。"""
    if not items:
        return '<p class="empty">这个时间窗里没有媒体条目。先跑 collect.py run。</p>', 0, 0

    groups = cluster(items)
    consensus = [g for g in groups if len({i["source_id"] for i in g}) >= 2]
    # 同样家数的，新的排前面
    consensus.sort(key=lambda g: (-len({i["source_id"] for i in g}),
                                  min(i["rank"] for i in g),
                                  _neg_time(max(g, key=lambda i: i.get("last_seen") or ""))))
    consensus = consensus[:MEDIA_SLOTS]

    # 补位规则：每家最多补一条，按它在自己源里的位置排（越靠前越像头条）。
    # 已进共识簇的不重复出现。
    used = {id(i) for g in consensus for i in g}
    seen, fillers = set(), []
    # 排序：先看当前位置，同位置比新鲜度——**新的优先**。
    # 之前这里 first_seen 用的升序，等于让每个源最老的那条头条一直占着格子，
    # 页面因此几小时不动。
    for it in sorted(items, key=lambda i: (i["rank"], _neg_time(i))):
        if len(consensus) + len(fillers) >= MEDIA_SLOTS:
            break
        if id(it) in used or it["source_id"] in seen:
            continue
        seen.add(it["source_id"])
        fillers.append(it)

    out = []
    for g in consensus:
        ids = {i["source_id"] for i in g}
        lead = min(g, key=lambda i: i["rank"])
        alt = "".join(
            f'<li><span class="s">{esc(o["source_name"])}</span>'
            f'<a href="{esc(o["url"])}" target="_blank" rel="noopener">{esc(zh_of(o))}</a></li>'
            for o in [i for i in g if i is not lead][:4])
        out.append(
            card_open(lead.get("region"), lead.get("region2"))
            + f'<div class="tags"><span class="tag hits">{len(ids)}/{len(SEATS)} 家</span>'
            + region_tags(lead.get("region"), lead.get("region2"))
            + pw_tag(lead["source_id"]) + '</div>'
            + f'<p class="zh"><a href="{esc(lead["url"])}" target="_blank" rel="noopener">'
              f'{esc(zh_of(lead))}</a></p>'
            + f'<p class="orig">{esc(lead["title"])}</p>' + seat_bar(ids)
            + (f'<ul class="alt">{alt}</ul>' if alt else "")
            + f'<div class="foot"><span>{esc(lead["source_name"])}</span>'
              f'<a href="{esc(lead["url"])}" target="_blank" rel="noopener">查看原文 ↗</a></div>'
            + '</article>')

    for it in fillers:
        out.append(
            card_open(it.get("region"), it.get("region2"), "solo")
            + '<div class="tags"><span class="tag solo">单家</span>'
            + region_tags(it.get("region"), it.get("region2"))
            + pw_tag(it["source_id"]) + '</div>'
            + f'<p class="zh"><a href="{esc(it["url"])}" target="_blank" rel="noopener">'
              f'{esc(zh_of(it))}</a></p>'
            + f'<p class="orig">{esc(it["title"])}</p>' + seat_bar({it["source_id"]})
            + f'<div class="foot"><span>{esc(it["source_name"])}</span>'
              f'<a href="{esc(it["url"])}" target="_blank" rel="noopener">查看原文 ↗</a></div>'
            + '</article>')

    return f'<div class="grid">{"".join(out)}</div>', len(consensus), len(fillers)


def render_official(items):
    """固定 5 格，中2美2欧1，按**发布方**（bloc）分名额。颜色仍按内容涉及的地区。"""
    def card(it):
        # 官方发布的地区不该靠模型猜——发布方是谁我们本来就知道。
        # 「每日新闻 07/08/2026」这种标题不含任何地区线索，模型只能归 OTHER，
        # 但它明明是欧委会发的。所以 bloc 优先，模型判断只用来补第二地区。
        r1 = it.get("bloc") or it.get("region")
        r2 = it.get("region2")
        # 模型判的主地区如果跟发布方不同，那才是有信息的——挪到第二格。
        # 例：BIS 增列中国实体 → 主蓝（华盛顿发的）副红（针对中国）
        mr = it.get("region")
        if mr and mr != r1 and mr != "OTHER" and not r2:
            r2 = mr
        if r2 in ("OTHER", r1):
            r2 = None
        kind = (it.get("summary") or "").strip()
        # Rule=已生效  Notice=多为清单类  Proposed Rule=还没定
        badge = kind if kind in ("Rule", "Notice", "Proposed Rule",
                                 "Presidential Document") else ""
        date = when(it)[:10]
        # "这栏三天不动"到底是没发生还是抓不到？现在一眼能分。
        # 分不清这两者的代价很高——你会怀疑系统，然后只能去查数据库。
        age = ""
        try:
            d = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            days = (datetime.now(timezone.utc) - d).days
            if days >= 1:
                age = f'<span class="age">{days} 天前</span>'
        except ValueError:
            pass
        return (card_open(r1, r2)
                + '<div class="tags">' + region_tags(r1, r2)
                + f'<span class="tag b">{esc(it["source_name"])}</span>'
                + (f'<span class="tag b">{esc(badge)}</span>' if badge else "") + '</div>'
                + f'<p class="zh"><a href="{esc(it["url"])}" target="_blank" rel="noopener">'
                  f'{esc(zh_of(it))}</a></p>'
                + (f'<p class="orig">{esc(it["title"])}</p>'
                   if zh_of(it) != it["title"] else "")
                + f'<div class="foot"><span>{date}{age}</span>'
                  f'<a href="{esc(it["url"])}" target="_blank" rel="noopener">查看原文 ↗</a></div>'
                + '</article>')

    out = []
    for bloc, n in OFFICIAL_QUOTA:
        pool = sorted([i for i in items if i.get("bloc") == bloc],
                      key=when, reverse=True)[:n]
        out += [card(i) for i in pool]
        # 名额空着就明说，绝不拿别国的顶替
        for _ in range(n - len(pool)):
            out.append(f'<article class="card hollow" style="--c1:{rcolor(bloc)}" '
                       f'data-r1="{bloc}" data-r2="">'
                       f'<div class="tags">{region_tags(bloc, None)}</div>'
                       f'<p class="zh">暂无</p>'
                       f'<p class="orig">这一格没有可用信源，不用其他来源顶替</p></article>')
    return f'<div class="grid">{"".join(out)}</div>'


def render_ticker(items):
    if not items:
        return '<p class="empty">快讯带还没有数据。先跑 scrape.py probe cls 配 link_pat。</p>'
    items = sorted(items, key=when, reverse=True)
    out = []
    for it in items[:30]:
        t = (it.get("published") or it["first_seen"])[11:16] or when(it)[5:10]
        out.append(f'<div class="tick"><time>{esc(t)}</time>'
                   f'<a href="{esc(it["url"])}" target="_blank" rel="noopener">'
                   f'{esc(zh_of(it))}</a></div>')
    return f'<div class="ticker">{"".join(out)}</div>'


def render_voices(items):
    if not items:
        return '<p class="empty">还没有观点条目。名单填进 sources.py 的 VOICES。</p>'
    items = sorted(items, key=when, reverse=True)
    out = []
    for it in items[:40]:
        r1, r2 = it.get("region"), it.get("region2")
        dual = bool(r2) and r2 != r1
        handle = (it.get("summary") or "").strip()
        handle = handle if handle.startswith("@") else ""
        date = when(it)[:10]
        out.append(
            f'<div class="v{" dual" if dual else ""}" '
            f'style="--c1:{rcolor(r1)};--c2:{rcolor(r2)}" '
            f'data-r1="{r1 or "OTHER"}" data-r2="{r2 or ""}">'
            f'<div class="who"><span class="dot"></span>{esc(it["source_name"])}'
            + (f'<span class="h">{esc(handle)}</span>' if handle else "") + '</div>'
            + f'<p class="zh2"><a href="{esc(it["url"])}" target="_blank" rel="noopener">'
              f'{esc(zh_of(it))}</a></p>'
            + (f'<p class="orig2">{esc(it["title"])}</p>' if zh_of(it) != it["title"] else "")
            + f'<time>{date}</time></div>')
    return "".join(out)


def build(db_path=DB, hours=24, out=OUT):
    con = sqlite3.connect(db_path)
    media, official = load(con, "media", hours), load(con, "official", hours)
    voices = load(con, "voice", hours)
    ticker = load(con, "ticker", hours)
    con.close()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    live = len({m["source_id"] for m in media})
    todo = sum(1 for i in media + official + voices if not i.get("title_zh"))
    media_html, n_con, n_solo = render_media(media)
    _q = "、".join(f"{ {'CN':'中国','US':'美国','EU':'欧洲'}[b] } {n}" for b, n in OFFICIAL_QUOTA)
    official_note = (f'<p class="note">固定 {sum(n for _, n in OFFICIAL_QUOTA)} 格，'
                     f'按发布方分配：{_q}，各取最新。不设时间窗——官方动作是低频的，'
                     f'三天前的实体清单公告今天仍然是最新一条。名额空着显示"暂无"，'
                     f'不拿别国顶替。</p>')

    page = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow">
<meta name="theme-color" content="#101316">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Doctor Swan">
<title>Doctor Swan · {now}</title><style>{CSS}</style></head>
<body><div class="wrap">
<header>
  <div class="brand">
    <svg width="26" height="30" viewBox="0 0 26 30" fill="none" aria-hidden="true">
      <path d="M4 27c0-8.5 3.2-13 8-14.4 3.4-1 5.4-2.6 5.4-5.2C17.4 4.6 15.6 3 13.4 3
               c-2 0-3.4 1.2-3.4 2.8" stroke="var(--dim)" stroke-width="1.3"
               stroke-linecap="round"/>
      <circle cx="9.4" cy="6" r="1.05" fill="var(--dim)"/>
      <path d="M4 27h18" stroke="var(--line2)" stroke-width="1.3" stroke-linecap="round"/>
    </svg>
    <div>
      <p class="sub">Daily Watch</p>
      <h1>Doctor <em>Swan</em></h1>
    </div>
  </div>
  <span class="stamp">{now} · 媒体 {MEDIA_WINDOW_H}h · 快讯 {int(TICKER_WINDOW_H*60)}min · 席位 {live}/{len(SEATS)}
    {f"· 待译 {todo}" if todo else ""}</span>
</header>

<div class="filters">
  <button class="f" data-r="ALL" aria-pressed="true">全部</button>
  <button class="f" data-r="CN">中国</button>
  <button class="f" data-r="US">美国</button>
  <button class="f" data-r="EU">欧洲</button>
  <button class="f" data-r="OTHER">其他</button>
</div>

<div class="layout"><main>

<section>
<h2>媒体关注</h2>
<p class="note">西方主流大报大社 {len(SEATS)} 个固定席位，按同时上头条的家数排序。
固定 {MEDIA_SLOTS} 格：<b style="color:var(--ink)">{n_con} 组共识</b>（两家以上同时上头条）
＋ {n_solo} 条单家补位。共识组数本身就是信号——数字低说明今天各家版面分散。</p>
{media_html}
</section>

<section>
<h2>财联社快讯</h2>
<p class="note">中文财经快讯，滚动。速度是它的价值——不进席位表，不参与共识计算。</p>
{render_ticker(ticker)}
</section>

<section>
<h2>官方发布</h2>
{official_note}
{render_official(official)}
</section>

</main>
<aside class="rail">
<h2>观点</h2>
<p class="note">推特 · newsletter · 自媒体。这一栏是观点，不是事实，
读的时候跟左边两栏分开算。</p>
{render_voices(voices)}
</aside>
</div>

<footer>
中文标题为机器直译，不做概括改写；原文标题一直挂在下方，点标题进原文。判断请以原文为准。<br>
标"付费墙""限次"的来源需要订阅才能读全文，标题与摘要通常已足够判断值不值得追。<br>
RSS 返回时间序而非版面序，"头条"取每源前 N 条，是近似值。<br>
路透（服务器拒绝）、AP 与法新社（版面由 JS 渲染，静态抓取只得到固定骨架）均无法接入。
三大通讯社在席位表上缺席，突发类事件的席位数会系统性偏低——别人转的都是它们的稿子。
</footer>
</div><script>{JS}</script></body></html>"""
    open(out, "w", encoding="utf-8").write(page)
    print(f"已生成 {out}：媒体 {len(media)} / 官方 {len(official)} / 观点 {len(voices)} 条"
          + (f"，其中 {todo} 条还没翻译（跑 enrich.py）" if todo else ""))


# ------------------------------------------------------------------ demo ----

def demo():
    import collect, enrich
    collect.DB = "demo.db"
    con = collect.db()
    enrich.migrate(con)
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    m = [("bbc", "BBC", 0, "EU and China clash over rare earth export controls",
          "欧盟与中国就稀土出口管制发生冲突", "CN", "EU", 0),
         ("guardian", "Guardian", 1, "Brussels weighs response to China rare earth controls",
          "布鲁塞尔权衡对中国稀土管制的回应", "EU", "CN", 1),
         ("nyt", "NYT", 2, "China Tightens Rare Earth Export Controls, Rattling Europe",
          "中国收紧稀土出口管制，令欧洲不安", "CN", "EU", 0),
         ("politico", "POLITICO EU", 9, "China rare earth controls draw European Union rebuke",
          "中国稀土管制招致欧盟指责", "CN", "EU", 2),
         ("ft", "FT", 5, "Fed holds rates, signals patience on cuts",
          "美联储按兵不动，暗示对降息保持耐心", "US", None, 0),
         ("wsj", "WSJ", 4, "Fed Holds Rates Steady as Labor Market Cools",
          "劳动力市场降温，美联储维持利率不变", "US", None, 1),
         ("wapo", "WaPo", 3, "Fed holds rates steady amid cooling labor market",
          "劳动力市场趋冷，美联储维持利率", "US", None, 2),
         ("bbc", "BBC", 0, "Ceasefire talks resume in Geneva",
          "停火谈判在日内瓦重启", "OTHER", None, 3),
         ("economist", "Economist", 6, "Ceasefire talks resume in Geneva after week of strikes",
          "空袭持续一周后，停火谈判在日内瓦重启", "OTHER", None, 1),
         ("spiegel", "Spiegel", 8, "Germany's coalition splits over defense spending",
          "德国执政联盟因国防开支分裂", "EU", None, 0),
         ("lemonde", "Le Monde", 7, "France's debt costs threaten the budget",
          "法国债务成本威胁预算", "EU", None, 0),
         ("wapo", "WaPo", 3, "Hiroshima marks 81st anniversary",
          "广岛纪念原爆81周年", "OTHER", None, 0),
         ("guardian", "Guardian", 1, "Ebola outbreak spreads in DRC",
          "埃博拉疫情在刚果（金）扩散", "OTHER", None, 0),
         ("bbc", "BBC", 0, "Meta fined $567m over child safety",
          "Meta因儿童安全问题被罚5.67亿美元", "US", "EU", 0),
         ("nyt", "NYT", 2, "Bond market reacts to Fed decision",
          "债市对美联储决定作出反应", "US", None, 4),
         ("scmp", "SCMP", 10, "Beijing signals flexibility ahead of trade talks",
          "北京在贸易谈判前释放灵活信号", "CN", "US", 0)]
    for sid, name, seat, t, zh, r1, r2, rank in m:
        rows.append(dict(id=collect.item_id(sid, None, t), layer="media", channel="web",
                         source_id=sid, source_name=name, seat=seat, bloc=None, title=t,
                         url="https://example.com", summary="", lang="en",
                         published=now, rank=rank))
    o = [("mofcom", "商务部", "CN", "商务部新闻发言人就稀土相关出口管制措施答记者问",
          "商务部新闻发言人就稀土相关出口管制措施答记者问", "CN", None, "", "web"),
         ("fr_bis", "BIS 商务部", "US", "Additions to the Entity List",
          "增列实体清单", "US", "CN", "Rule", "web"),
         ("fr_ofac", "OFAC 财政部", "US", "Sanctions Actions Pursuant to E.O. 13224",
          "依据第13224号行政令采取的制裁行动", "US", "OTHER", "Notice", "web"),
         ("ec", "欧委会", "EU", "Commission opens consultation on critical raw materials stockpiling",
          "欧委会就关键原材料储备启动咨询", "EU", None, "", "web"),
         ("ep", "欧洲议会", "EU", "Parliament backs tougher screening of foreign investment",
          "议会支持收紧外国投资审查", "EU", "CN", "", "web"),
         ("wh", "白宫", "US", "Nominations Sent to the Senate",
          "提名已送交参议院", "US", None, "", "web")]

    v = [("x_POTUS", "美国总统", "We will not allow this to stand.",
          "我们不会容许此事就这样过去。", "US", None, "@POTUS"),
         ("x_MFA_China", "中国外交部", "China firmly opposes unilateral coercive measures.",
          "中方坚决反对单边强制措施。", "CN", "US", "@MFA_China"),
         ("x_vonderleyen", "冯德莱恩", "Europe will diversify its supply chains.",
          "欧洲将实现供应链多元化。", "EU", "CN", "@vonderleyen"),
         ("sinocism", "Sinocism", "Rare earths, the Politburo meeting, and the trade talks",
          "稀土、政治局会议与贸易谈判", "CN", "US", ""),
         ("chinatalk", "ChinaTalk", "What Beijing's export control playbook actually says",
          "北京的出口管制手册究竟写了什么", "CN", None, "")]
    for sid, name, t, zh, r1, r2, h in v:
        rows.append(dict(id=collect.item_id(sid, None, t), layer="voice",
                         channel="x" if sid.startswith("x_") else "post",
                         source_id=sid, source_name=name, seat=None, bloc=None, title=t,
                         url="https://example.com", summary=h, lang="en",
                         published=now[:16], rank=0))
    for sid, name, bloc, t, zh, r1, r2, tag, ch in o:
        pub = "2026-08-04" if sid == "wh" else now[:10]   # 造一条旧的，验证陈旧标记
        rows.append(dict(id=collect.item_id(sid, None, t), layer="official", channel=ch,
                         source_id=sid, source_name=name, seat=None, bloc=bloc, title=t,
                         url="https://example.com", summary=tag, lang="en",
                         published=pub, rank=0))
    collect.save(con, rows, now)
    # 补上假的译文和地区
    for sid, name, seat, t, zh, r1, r2, rank in m:
        con.execute("UPDATE items SET title_zh=?,region=?,region2=?,enriched=1 WHERE id=?",
                    (zh, r1, r2, collect.item_id(sid, None, t)))
    for sid, name, bloc, t, zh, r1, r2, tag, ch in o:
        con.execute("UPDATE items SET title_zh=?,region=?,region2=?,enriched=1 WHERE id=?",
                    (zh, r1, r2, collect.item_id(sid, None, t)))
    for sid, name, t, zh, r1, r2, h in v:
        con.execute("UPDATE items SET title_zh=?,region=?,region2=?,enriched=1 WHERE id=?",
                    (zh, r1, r2, collect.item_id(sid, None, t)))
    con.commit()
    con.close()
    build(db_path="demo.db", hours=24, out="demo.html")


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--demo" in a:
        demo()
    else:
        build(hours=float(a[a.index("--hours") + 1]) if "--hours" in a else 24)
