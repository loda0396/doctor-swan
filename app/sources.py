# -*- coding: utf-8 -*-
"""
信源配置。改这个文件就够了，别的不用动。

两大类：
  media    媒体关注 —— 只要西方主流大报大社。看的是"谁把什么抬上头条"。
  official 官方发布 —— 中/美/欧官方机构 + 重要人物的 X。看的是"发生了什么"。

阵营配色（贯穿整个前端）：
  CN 红 / US 蓝 / EU 绿
"""

BLOC_ORDER = ["CN", "US", "EU"]

BLOC = {
    "CN": dict(label="北京", color="#E0524A", tag="CN"),
    "US": dict(label="华盛顿", color="#5B9DDB", tag="US"),
    "EU": dict(label="布鲁塞尔", color="#55B98A", tag="EU"),
}

# ---------------------------------------------------------------- 媒体关注 ----
# 10 个固定席位。全部英文 feed —— 这是刻意的：同语种词汇聚类才有效，
# 席位条上就不会再出现"无法比对"的虚格，空格就是真的空格。
# seat 是固定位置，别改，位置不变缺席才看得出来。
#
# 缺口要说清楚：路透、AP、法新社都没有可用的官方 RSS。三大通讯社在这张
# 席位表上是缺席的，这会让"突发"类事件的席位数偏低。心里要有数。

MEDIA = [
    dict(id="bbc",      name="BBC",        seat=0, kind="rss", lang="en", top_n=8, status="ok",
         url="https://feeds.bbci.co.uk/news/world/rss.xml"),
    # /world/rss 是次级栏目：更新稀疏（一天两三条），且重大国际新闻不走这个口。
    # 2026-08-09 全网都在报以色列拒绝加沙和平计划，这个 feed 一条都没有，
    # 抓到的全是软新闻。等于这个席位一直在投废票，系统性压低共识组数。
    # 改用国际版首页 feed。
    dict(id="guardian", name="Guardian",   seat=1, kind="rss", lang="en", top_n=8,
         status="unverified", url="https://www.theguardian.com/international/rss"),
    dict(paywall="hard", id="nyt",      name="NYT",        seat=2, kind="rss", lang="en", top_n=8, status="ok",
         url="https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"),
    # 这个 feed 一直只返回 4 条，其他家都是 8 条 —— 同样可疑，先记着。
    dict(paywall="hard", id="wapo",     name="WaPo",       seat=3, kind="rss", lang="en", top_n=8, status="unverified",
         url="https://feeds.washingtonpost.com/rss/world"),
    dict(paywall="hard", id="ft",       name="FT",         seat=4, kind="rss", lang="en", top_n=8, status="unverified",
         url="https://www.ft.com/rss/home"),
    # 英文版，不是法文版 —— 为了能跟其他席位聚类
    dict(paywall="metered", id="lemonde",  name="Le Monde",   seat=5, kind="rss", lang="en", top_n=8, status="unverified",
         url="https://www.lemonde.fr/en/rss/une.xml"),
    # 你在布鲁塞尔，这一席比再加一家美国报纸有用
    dict(id="politico", name="POLITICO EU", seat=6, kind="rss", lang="en", top_n=8, status="ok",
         url="https://www.politico.eu/feed/"),
    # 第 11 席。注意：加了 SCMP 之后，这张席位表就不纯是"西方主流"了——
    # 它常常先于西方媒体报中国相关的事。这是优点，但读席位条时要记得：
    # SCMP 亮着而其他十家都空，不等于"世界在关注"，等于"只有香港在关注"。
    # 备用地址：https://www.scmp.com/rss/4/feed（综合新闻）
    dict(paywall="metered", id="scmp", name="SCMP", seat=7, kind="rss", lang="en",
         top_n=8, status="unverified", url="https://www.scmp.com/rss/318198/feed"),

    # 第 12 席：快讯型。Axios 报了才说明议题进入了华盛顿的日常对话——
    # NYT 报了只说明它重要，Axios 报了说明它已经在被谈论。这是"破圈"的指标。
    dict(id="axios", name="Axios", seat=8, kind="rss", lang="en", top_n=8,
         status="unverified", url="https://api.axios.com/feed/"),

    # 13–15 席：三大通讯社。都没有官方 RSS（网上能搜到的全是第三方生成器，
    # 这本身就是证据），只能爬首页。跑 scrape.py probe 拿 link_pat。
    #
    # 它们在这张表上缺席，会让突发类事件的席位数系统性偏低——因为别人转的
    # 都是它们的稿子。补齐之后共识组数应该会明显上来。
    # 路透在服务器层就 401 —— Akamai 那类防护，检测 TLS 指纹，改 header 没用。
    # 要绕得上无头浏览器，为一个席位不值得。先空着，席位号留给它。
    # 它的稿子大量被 BBC/Guardian/SCMP 转载，内容其实间接进来了，
    # 缺的只是独立投票权。
    # dict(id="reuters", name="Reuters", seat=12, ...),
    # AP 也放弃：/、/hub/ap-top-news、/politics 三个页面返回完全相同的八条软新闻
    # （酒吧、卡皮巴拉、鲸鱼），连顺序都一样——说明它给所有非浏览器请求发同一份
    # 静态骨架，真实版面全在 JS 里。法新社大概率同理。
    #
    # 三大通讯社全部缺席。这是这张席位表最大的结构性偏差，读数时必须记得：
    # 突发类事件的席位数会系统性偏低，因为别人转的都是它们的稿子。
    # 反过来说，它们的内容通过 BBC/Guardian/SCMP 的转载已经间接进来了，
    # 缺的只是独立投票权和几十分钟的时间差。
    # 要补齐只能上无头浏览器（Playwright + Chromium），那是持续维护的负担，
    # 为一个席位不划算。
]

# ---------------------------------------------------------------- 官方发布 ----

OFFICIAL = [
    # ---- 中国。RSS 时好时坏，落到爬虫。status=todo，check 会明确报出来 ----
    # link_pat = 新闻链接 URL 里必须包含的片段。填法：先跑
    #   python3 scrape.py probe mofcom
    # 看它打出来的 URL 模式，挑出新闻列表那一组的共同片段填进来，再 test 验证。
    # 留空就报 NotImplementedError，不会静默抓到空。
    # 商务部 xwfb 页面下有五个栏目，各 6 条。分成两个源：
    #   xwfyrth = 新闻发言人谈话，反制动作最先落地的文本形态，优先级最高
    #   bldhd   = 部领导活动，王文涛的会谈/签署，对 EU-China 这条线同样关键
    # 另外三个（ldrhd 领导人活动 / rcxwfb 日常发布 / sjfzrfb 司局发布）暂不收，
    # ldrhd 是新华社通稿转载，你本来就有；要加照抄一行改 link_pat 即可。
    dict(id="mofcom", name="商务部发言人", bloc="CN", kind="scrape", lang="zh", top_n=6,
         status="ok", link_pat="/xwfb/xwfyrth/",
         url="https://www.mofcom.gov.cn/xwfb/index.html"),
    dict(id="mofcom_ld", name="商务部部领导", bloc="CN", kind="scrape", lang="zh", top_n=6,
         status="ok", link_pat="/xwfb/bldhd/",
         url="https://www.mofcom.gov.cn/xwfb/index.html"),
    # 「发言人表态」页下两组内容，各 8 条。页面里还有 32 个驻外机构导航链接
    # （/web/zwjg_…）和一堆页脚，link_pat 精确到栏目就能滤干净。
    #   dhdw   = 谈话答问，单条表态，中方反制/回应最先落地的形态
    #   jzhsl  = 例行记者会实录，很长但密度高
    dict(id="fmprc", name="外交部发言人", bloc="CN", kind="scrape", lang="zh", top_n=8,
         status="ok", link_pat="/dhdw_",
         url="https://www.fmprc.gov.cn/fyrbt_673021/"),
    dict(id="fmprc_jzh", name="外交部记者会", bloc="CN", kind="scrape", lang="zh", top_n=4,
         status="ok", link_pat="/jzhsl_",
         url="https://www.fmprc.gov.cn/fyrbt_673021/"),
    # ---- 微博。发布通常早于官网，是"更及时"这条路的实际解法。
    # uid 从 weibo.com/u/XXXX 的地址里取。走 m.weibo.cn 的 JSON 接口，
    # 不用登录不用验证码，但会限流——半小时一次是安全的，别更密。
    # 关税税则委：加征/取消关税的公告在这里落地，是中方最"不可逆"的一类动作。
    # 更新频率低（一个月两三条），但每条都重要，所以 top_n 给 6 就够。
    dict(id="gwyswgg", name="关税税则委", bloc="CN", kind="scrape", lang="zh", top_n=6,
         status="ok", link_pat="/gzdt/zhengcefabu/2",
         url="https://gss.mof.gov.cn/gzdt/zhengcefabu/"),

    # ---- 美国。Federal Register 读取不需要 key，行政动作在这里落地 ----
    dict(id="fr_bis", name="BIS 商务部", bloc="US", kind="federal_register", lang="en",
         agencies=["industry-and-security-bureau"], top_n=20, status="ok"),
    dict(id="fr_ofac", name="OFAC 财政部", bloc="US", kind="federal_register", lang="en",
         agencies=["foreign-assets-control-office"], top_n=20, status="ok"),
    dict(id="fr_ustr", name="USTR", bloc="US", kind="federal_register", lang="en",
         agencies=["trade-representative-office-of-united-states"], top_n=20, status="ok"),
    dict(id="wh", name="白宫", bloc="US", kind="rss", lang="en", top_n=10, status="ok",
         url="https://www.whitehouse.gov/presidential-actions/feed/"),
    # 国务院也放弃：232 个链接全是导航和社交图标，/press-releases/ 那 11 条里
    # 第一条是「Skip to content」——稿件列表由 JS 渲染，跟 AP 同一个情况。
    # 美国这三格已有 BIS/OFAC/USTR/白宫四个源供货，缺它不致命。

    # ---- 欧盟。presscorner 是唯一把新闻稿/表态/每日简报都塞进一个 RSS 的 ----
    dict(id="ec", name="欧委会", bloc="EU", kind="rss", lang="en", top_n=20, status="ok",
         url="https://ec.europa.eu/commission/presscorner/api/rss"),
    # 欧洲议会：从 GitHub 的美国 IP 访问返回空 feed（本地能拿到 10 条）。
    # 同一个地址对不同来源返回不同内容，这类源不可靠，删。
    # 欧洲这两格由欧委会 presscorner 撑着——它覆盖 press release、statement、
    # Daily News、speech，本来就是欧盟侧信息量最大的一个口子。
]

# ---------------------------------------------------------------- 观点栏 ----
# 右侧竖栏。推特、newsletter、自媒体 —— 性质跟前两类不一样：
#   官方发布是事实，媒体头条是注意力，这一栏是观点。所以单独一层，不混排。
# 颜色还是按内容涉及的地区（enrich.py 判断），不按作者立场。
#
# kind="rss"  任何 Substack 都是在域名后加 /feed，比如
#             https://sinocism.com/feed —— 免费且稳定，优先用这个
# kind="x"    走 X API，按次收费，见下面的成本说明
#
# 下面全是占位，等你的名单，直接改这里就行。
# 重要人物的 X。全部按机构/职位选，不按个人选 —— 人会换，账号不会。
# handle 我没法在这里替你核实，跑 `python collect.py xcheck` 会逐个验，
# 失效的直接报出来。不要凭印象留着一个死账号。
#
# 成本必须先算清楚（2026 年 7 月核实的价）：
#   X 官方 API 已经取消免费层，改成按次计费，读一条约 $0.005，
#   用户信息查询约 $0.010。老的 $200/月 Basic 档对新注册者已关闭。
#   下面 12 个账号 × 每次拉 5 条 × 每天 3 次 ≈ 180 次读/天 ≈ $27/月。
#   user id 只查一次并缓存，别每次都查。
# 第三方桥接便宜两个数量级，但对你这个身份不建议用 —— 稳定性和合规都不划算。

VOICES = [
    # 标准不是覆盖面，是信噪比。这一栏要回答的问题是：
    # 「这段时间西方主流在关注什么、讨论什么」。
    # 所以中国视角的信源（Pekingnology、Ginger River、Baiguan 等）全部剔除——
    # 它们是好东西，但答的是另一个问题，放这儿会稀释掉主线。

    # —— 分析文章 ——
    dict(paywall="hard", id="stratechery", name="Stratechery",    kind="rss", top_n=3, status="ok",
         url="https://stratechery.com/feed/"),          # 科技与商业战略
    dict(id="noahpinion",  name="Noahpinion",     kind="rss", top_n=3, status="ok",
         url="https://www.noahpinion.blog/feed"),       # 经济
    dict(id="lawfare",     name="Lawfare",        kind="rss", top_n=3, status="ok",
         url="https://www.lawfaremedia.org/feeds/articles"),   # 美国法律与国安
    dict(id="warontherocks", name="War on the Rocks", kind="rss", top_n=3, status="ok",
         url="https://warontherocks.com/feed/"),        # 防务与地缘
    # Bruegel 和 The Long Game 都被 Cloudflare 那类防护拦在数据中心 IP 之外，
    # 补 header 没用（它看的是 TLS 指纹，不是请求头）。要绕只能上无头浏览器，
    # 不值得。ECFR 覆盖欧盟政策，Lawfare 和 President's Inbox 覆盖前官员视角。
    dict(id="ecfr",        name="ECFR",           kind="rss", top_n=3, status="ok",
         url="https://ecfr.eu/feed/"),                  # 欧盟外交政策

    # —— 播客 ——
    # 播客的 feed 地址是托管商生成的，猜不出来。用：
    #     python3 podcast.py "All-In"
    # 查到真实地址再填进来。
    #
    # 播客在这里的价值不在音频，在**节目标题和章节列表**——那就是一份
    # 「本周西方精英选择讨论的议题清单」，比任何摘要都直接。
    # top_n 给 2 就够，周更节目多了会刷屏。
    #
    # The Long Game（沙利文 + Jon Finer）—— 位置极好但 Substack 拦数据中心 IP。
    # 如果哪天想要，只能在本地跑。地址：thelonggame.substack.com/feed

    # —— 以下地址是推测，跑 check 验证。挂了的要么修要么删，别留着。——
    dict(id="platformer", name="Platformer", kind="rss", top_n=3, status="unverified",
         url="https://www.platformer.news/feed"),
    dict(id="semafor", name="Semafor", kind="rss", top_n=4, status="unverified",
         url="https://www.semafor.com/rss.xml"),
    # Carnegie Europe 的 RSS 地址我猜错了（那串 solr 参数是拼的，返回空）。
    # 欧洲侧现在只有 Bruegel 和 ECFR，确实偏薄，但宁可空着也不放一个死源——
    # 死源在 check 里天天报错，看久了会麻木，那才是真正的风险。
    # 要补的话去 carnegieendowment.org 页面底部找真实的 RSS 链接。

    # —— 播客：地址是托管商生成的乱码串，必须本地查。——
    # 跑 python3 podcast.py "名字"，把查到的 url 填到对应行，再把 # 去掉。
    #
    # All-In —— 节目标题就是本周硅谷精英的议题清单，比任何摘要都直接。
    # 周更，top_n=2 足够；给多了会把右栏刷满。
    dict(id="allin", name="All-In", kind="rss", top_n=2, status="unverified",
         url="https://rss.libsyn.com/shows/254861/destinations/1928300.xml"),
    # dict(id="psw",       name="Pod Save the World",  kind="rss", top_n=2, url=""),
    dict(id="prezinbox", name="The President's Inbox", kind="rss", top_n=2,
         status="unverified", url="https://feed.podbean.com/thepresidentsinbox/feed.xml"),
    # Sharp China —— 主持人是 Andrew Sharp 和 Sinocism 的 Bill Bishop。
    # Sinocism 本身从名单里删了（细分领域，不是"世界在关心什么"），
    # 但 Bishop 从播客这条腿回来更合适：拿到的是他每周挑出来的议题，
    # 不是他的全部日更。
    dict(id="sharpchina", name="Sharp China", kind="rss", top_n=2,
         status="unverified", url="https://sharpchina.fm/feed/podcast"),
    # 主播客（Ryan Evans）。他们还有个 Cogs of War 分支做国防工业，更新更勤，
    # 需要的话地址是 rss.libsyn.com/shows/580325/destinations/5030860.xml
    dict(id="wotr_pod", name="WOTR 播客", kind="rss", top_n=2, status="unverified",
         url="https://rss.libsyn.com/shows/70702/destinations/298196.xml"),
    dict(id="hardfork", name="Hard Fork", kind="rss", top_n=2, status="unverified",
         url="https://feeds.simplecast.com/6HKOhNgS"),
    #
    # Money Stuff（Matt Levine）没有公开 RSS —— 彭博几年前就关了，
    # 网上流传的都是第三方镜像，稳定性和合规都不行。只能订阅邮件，不配。
]

# ---------------------------------------------------------------- 快讯带 ----
# 财联社。中文财经快讯，速度是它的全部价值——比中文官媒早，比英文媒体早得多。
#
# 单独成一层，不进席位表。理由：中文标题跟英文在词汇层面配不上对，
# 放进共识计算就是一张永远的废票（跟 Guardian/WSJ 一个性质）。
# 它要回答的问题不是"几家同时在报"，是"中国财经侧刚刚发生了什么"。
#
# 展示位置：官方发布下面一条窄滚动带。节奏跟官方通报同类（都是"发生了什么"），
# 但频率高一个量级，所以给它自己的空间，不跟八格卡片抢视觉。
#
# 页面是纯前端渲染，静态爬虫抓不到（probe 只返回三个页脚备案号链接）。
# 走它自己的后端接口 /v1/roll/get_roll_list。接口有签名，但算法是
# md5(sha1(参数按键排序拼接))，无盐无密钥，可以自己算——见 collect.py。

TICKER = [
    dict(id="cls", name="财联社", bloc="CN", kind="cls", lang="zh", top_n=20,
         status="ok"),
]


# ---- X 账号 ----
X_ACCOUNTS = [
    dict(handle="POTUS",         name="美国总统",       bloc="US"),
    dict(handle="WhiteHouse",    name="白宫",           bloc="US"),
    dict(handle="StateDept",     name="美国国务院",      bloc="US"),
    dict(handle="USTradeRep",    name="USTR",          bloc="US"),
    dict(handle="USTreasury",    name="美国财政部",      bloc="US"),

    dict(handle="MOFCOM_China",  name="中国商务部",      bloc="CN"),
    dict(handle="MFA_China",     name="中国外交部",      bloc="CN"),
    dict(handle="SpokespersonCHN", name="外交部发言人",   bloc="CN"),
    dict(handle="ChinaEUMission", name="中国驻欧盟使团",  bloc="CN"),

    dict(handle="vonderleyen",   name="冯德莱恩",        bloc="EU"),
    dict(handle="MarosSefcovic", name="谢夫乔维奇（贸易）", bloc="EU"),
    dict(handle="eu_eeas",       name="欧盟对外行动署",   bloc="EU"),
    dict(handle="EUCouncilPress", name="欧盟理事会",     bloc="EU"),
]

X_TOP_N = 5   # 每个账号每次拉几条。这个数直接乘进账单里。

# X 账号统一并进观点栏
for _a in X_ACCOUNTS:
    VOICES.append(dict(id="x_" + _a["handle"], name=_a["name"], kind="x",
                       handle=_a["handle"], bloc=_a.get("bloc"), top_n=X_TOP_N,
                       status="unverified"))
