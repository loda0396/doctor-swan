# -*- coding: utf-8 -*-
"""
地区分类：纯关键词规则，不调模型，不花钱。

原来这活儿是 enrich.py 调 Haiku 做的。2026-10 停掉 API 之后改成规则。
依据很朴素：标题里的专有名词本身就是最强的地区信号。

两层判断：
  1. 关键词打分 —— 命中一个算一分，分最高的是主地区，第二名作次地区
  2. 来源偏置 —— 一个关键词都没命中时，才看这条是谁发的。
     只给题材窄到没有歧义的源（POLITICO EU 只写欧盟，SCMP 用的是 China 频道），
     而且只在规则完全没话说的时候才用。
     这不违背"按内容不按来源"那条原则：有内容信号时永远听内容的。

写模式时注意两件事（第一版在这儿栽过）：
  · 不要用 \\b 收尾。\\bTaiwan\\b 匹配不到 Taiwanese，
    \\bRepublican\\b 匹配不到 Republicans —— 一个词尾就漏掉成百上千条。
    所以一律写成词头锚定的词干：r"\\bTaiwan"。
  · US、EU、UK 这种两字母词必须两头都收 \\b，否则会在别的单词里误中。

调准确率就往下面的表里加词，加完跑 `python3 regions.py <库路径>` 看分数。

实测（拿停用前模型标注的 6357 条媒体/观点条目当标准答案）：
    规则判为 CN  准确 75%      实际是 CN 的抓到 91%
    规则判为 US  准确 87%      实际是 US 的抓到 75%
    规则判为 EU  准确 89%      实际是 EU 的抓到 80%
中国新闻抓得最全，这是这个盘子最在意的一类；美欧判得准，漏的那些落进
灰色 OTHER，所以灰格会偏多——但不会把美国新闻染成中国红，错的方向是安全的。

注意标准答案本身有噪音：同样是乌克兰的新闻，模型有时标 EU 有时标 OTHER。
所以不要为了把分数从 78% 推到 80% 一直加词，那是在拟合噪音。
"""

import re

# —— 词干，词头锚定，允许任意词尾（Chinese / Taiwanese / Republicans 都能中）——
KEYWORDS = {
    "CN": [
        r"\bChin(a|ese)", r"\bBeijing", r"\bShanghai", r"\bShenzhen", r"\bGuangdong",
        r"\bHong Kong", r"\bMacau", r"\bTaiwan", r"\bTaipei", r"\bXinjiang", r"\bTibet",
        r"\bXi Jinping", r"\bLi Qiang", r"\bWang Yi", r"\bPolitburo",
        r"\bCommunist Party", r"\bCCP\b", r"\bPLA\b", r"\byuan\b", r"\brenminbi",
        r"\bRMB\b", r"\bSinic", r"\bSino-",
        r"\bHuawei", r"\bByteDance", r"\bTikTok", r"\bAlibaba", r"\bTencent",
        r"\bBYD\b", r"\bCATL\b", r"\bSMIC\b", r"\bXiaomi", r"\bDeepSeek", r"\bCOSCO",
        r"\bNio\b", r"\bBaidu", r"\bAnt Group", r"\bCOMAC", r"\bChang'?an",
        r"\brare earth",
        r"中国", r"中方", r"中美", r"中欧", r"北京", r"上海", r"深圳", r"广东",
        r"香港", r"澳门", r"台湾", r"台海", r"新疆", r"西藏",
        r"习近平", r"李强", r"王毅", r"人民币", r"商务部", r"外交部", r"国务院",
        r"发改委", r"央行", r"海关总署", r"稀土", r"A股", r"沪深", r"工信部",
    ],
    "US": [
        r"\bU\.?S\.?\b", r"\bUnited States", r"\bAmerica", r"\bWashington",
        r"\bTrump", r"\bWhite House", r"\bPentagon", r"\bCongress", r"\bSenat(e|or)",
        r"\bHouse (of Representatives|Republican|Democrat|speaker)", r"\bGOP\b",
        r"\bRepublican", r"\bDemocrat", r"\bFederal Reserve", r"\bthe Fed\b",
        r"\bFed\b", r"\bWall Street", r"\bNew York", r"\bCalifornia", r"\bTexas",
        r"\bFlorida", r"\bTennessee", r"\bOhio", r"\bMichigan", r"\bGeorgia\b",
        r"\bPennsylvania", r"\bArizona", r"\bVirginia", r"\bIllinois", r"\bChicago",
        r"\bLos Angeles", r"\bSan Francisco", r"\bSilicon Valley", r"\bBoston",
        r"\bSupreme Court", r"\bFBI\b", r"\bCIA\b", r"\bICE\b", r"\bDOJ\b",
        r"\bSEC\b", r"\bFTC\b", r"\bFAA\b", r"\bNASA\b", r"\bIRS\b", r"\bNSA\b",
        r"\bTreasury", r"\bUSTR\b", r"\bMedicaid", r"\bMedicare", r"\bObamacare",
        r"\bSchumer", r"\bVance\b", r"\bRubio", r"\bBessent", r"\bPowell\b",
        r"\bWarsh", r"\bNewsom", r"\bDeSantis", r"\bAOC\b", r"\bMamdani",
        r"\bBiden", r"\bHarris\b", r"\bMusk\b", r"\bElon",
        r"\bMeta\b", r"\bGoogle", r"\bApple\b", r"\bAmazon\b", r"\bMicrosoft",
        r"\bTesla", r"\bNvidia", r"\bOpenAI", r"\bAnthropic", r"\bBoeing",
        r"\bWalmart", r"\bIntel\b", r"\bAnduril", r"\bSpaceX",
        r"\bdollar", r"\bTreasuries", r"\bNasdaq", r"\bS&P 500",
        # 美国国内新闻的标题常常一个 US / America 都不出现（"Weak Jobs Report"、
        # "Prosecutor Sues Justice Dept."），全靠这组本土词汇把它们捞回来。
        r"\bJustice Dep(t|artment)", r"\bAttorney General", r"\bjobs report",
        r"\blabor market", r"\bNBA\b", r"\bNFL\b", r"\bMLB\b", r"\bHollywood",
        r"\bGovernor\b", r"\bstate legislature", r"\bgrand jury", r"\bDOGE\b",
        r"\bCapitol", r"\bNational Guard", r"\bprosecutor", r"\bindict",
        r"\bSocial Security",
        r"美国", r"美方", r"华盛顿", r"特朗普", r"美联储", r"白宫", r"纽约",
        r"美元", r"硅谷", r"国会",
    ],
    "EU": [
        r"\bEU\b", r"\bE\.U\.", r"\bEuropean", r"\bEurope\b", r"\bEurozone",
        r"\bBrussels", r"\bECB\b", r"\beuro\b", r"\bNATO\b",
        r"\bCommission(er)?\b", r"\bStrasbourg", r"\bSchengen",
        r"\bGerman", r"\bBerlin", r"\bFrance\b", r"\bFrench", r"\bParis",
        r"\bMacron", r"\bItal(y|ian)", r"\bRome\b", r"\bMeloni",
        r"\bSpain", r"\bSpanish", r"\bMadrid", r"\bCeuta", r"\bCatalon",
        r"\bNetherlands", r"\bDutch", r"\bAmsterdam", r"\bBelgi(um|an)",
        r"\bPol(and|ish)", r"\bWarsaw", r"\bSwed(en|ish)", r"\bDenmark", r"\bDanish",
        r"\bNorway", r"\bNorwegian", r"\bFinland", r"\bFinnish", r"\bAustria",
        r"\bGreece", r"\bGreek", r"\bPortug", r"\bIreland", r"\bIrish",
        r"\bHungar", r"\bOrban", r"\bCzech", r"\bSlovak", r"\bRomania",
        r"\bBulgaria", r"\bCroatia", r"\bBaltic", r"\bLatvia", r"\bLithuania",
        r"\bEstonia", r"\bSwitzerland", r"\bSwiss",
        r"\bBritain", r"\bBritish", r"\bU\.?K\.?\b", r"\bLondon", r"\bEngland",
        r"\bScotland", r"\bWestminster", r"\bDowning Street", r"\bStarmer",
        r"\bvon der Leyen", r"\bMerz\b", r"\bScholz", r"\bSefcovic", r"\bKallas",
        r"\bCosta\b", r"\bVerhofstadt", r"\bLe Pen", r"\bAfD\b",
        r"欧盟", r"欧洲", r"布鲁塞尔", r"德国", r"法国", r"英国", r"意大利",
        r"西班牙", r"荷兰", r"波兰", r"欧元", r"冯德莱恩", r"欧委会",
    ],
}

# 来源偏置：只给题材窄到没有歧义的源，且只在关键词一个都没中时才生效。
SOURCE_BIAS = {
    "politico": "EU",      # POLITICO Europe，只写欧盟
    "scmp": "CN",          # 用的是 China 频道
    "ec": "EU", "ep": "EU",
    "cls": "CN",           # 财联社
    "sharpchina": "CN", "sinocism": "CN", "chinatalk": "CN",
    "axios": "US",         # 美国政治快讯
    "wh": "US", "fr_bis": "US", "fr_ofac": "US", "fr_ustr": "US",
    "mofcom": "CN", "mofcom_ld": "CN", "fmprc": "CN",
    "fmprc_jzh": "CN", "gwyswgg": "CN",
    "bruegel": "EU", "ecfr": "EU",
}

_COMPILED = {k: [re.compile(p, re.I) for p in v] for k, v in KEYWORDS.items()}


def classify(title, source_id=None):
    """标题 → (主地区, 次地区)。次地区没有就是 None。

    命中一个关键词算一分。最高分是主地区；第二名只要也命中过就作次地区——
    中美、中欧这类双边新闻必须两个都标出来，那恰恰是这个盘子最该看见的。
    全没命中时才退回来源偏置；再没有就是 OTHER（中东、乌克兰、非洲、
    拉美都落在这里，显示成灰色，那是诚实的）。
    """
    if not title:
        return (SOURCE_BIAS.get(source_id) or "OTHER"), None
    score = {k: sum(1 for p in pats if p.search(title)) for k, pats in _COMPILED.items()}
    ranked = sorted(score.items(), key=lambda kv: -kv[1])
    if ranked[0][1] == 0:
        return (SOURCE_BIAS.get(source_id) or "OTHER"), None
    r1 = ranked[0][0]
    r2 = ranked[1][0] if ranked[1][1] > 0 else None
    return r1, r2


if __name__ == "__main__":
    import sqlite3
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else "watch.db"
    con = sqlite3.connect(db)
    # 只对照媒体和观点两层：官方层的颜色一直是按发布方（bloc）定的，
    # 不走这里，拿它来评分会把分数算歪。
    rows = con.execute("SELECT title, region, region2, source_id FROM items "
                       "WHERE region IS NOT NULL AND layer IN ('media','voice')").fetchall()
    hit = both = 0
    for t, r1, r2, sid in rows:
        g1, g2 = classify(t, sid)
        if g1 == r1:
            hit += 1
            both += (g2 or "") == (r2 or "")
    n = len(rows)
    print(f"对照 {n} 条媒体/观点条目（标准答案＝之前的模型标注）")
    print(f"  主地区一致   {hit/n:.1%}   ({hit}/{n})")
    print(f"  主+次都一致  {both/n:.1%}   ({both}/{n})")
