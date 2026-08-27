"""
越野车行业四源爬虫 —— GitHub Actions 定时版

四个权威源：
  源1 工信部         —— 汽车申报/公告（CMS 动态加载，走接口）
  源2 缺陷产品召回中心 —— 国内汽车召回备案（静态 HTML）
  源3 全国汽标委 CATARC —— 标准发布/解读/制修订（静态 HTML）
  源4 国家标准委     —— 强制性/推荐性国标（静态 HTML）

本脚本只做「抓取 + 落盘」，不做 Dify 上传（本地 localhost 在云端访问不到）：
  spider_result.json —— 结构化数据（程序用）
  spider_result.md   —— 人可读报告（人看）
"""

import json
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup

# 源3/源4 用了 verify=False，把 urllib3 告警压掉，让 Actions 日志干净
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ====================== 配置区 ======================
# 列表/正文是工信部 CMS 动态加载的，页面静态 HTML 里没有列表，改走接口
LIST_API = "https://www.miit.gov.cn/api-gateway/jpaas-publish-server/front/page/build/unit"
LIST_PARAMS = {
    "parseType": "buildstatic",
    "webId": "8d828e408d90447786ddbe128d495e9e",
    "tplSetId": "209741b2109044b5b7695700b2bec37e",
    "pageType": "column",
    "tagId": "当前栏目_list",
    "editType": "null",
    "pageId": "c52d8862a87d454582ed7c46513978d9",
}

# 缺陷产品召回中心（国家市监总局汽车召回官方备案平台），纯静态 HTML
RECALL_LIST_URL = "https://www.samrdprc.org.cn/qczh/gnzhqc/"
RECALL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.samrdprc.org.cn/",
}

# 全国汽车标准化技术委员会（CATARC），标准动态（工作动态栏目）
CATARC_LIST_URL = "https://www.catarc.org.cn/xwdt/gzdt/index.html"
CATARC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.catarc.org.cn/",
}

# 国家标准委（国标全文公开系统），强制性/推荐性国标列表
GB_LIST_URL = "https://openstd.samr.gov.cn/bzgk/std/std_list_type"
GB_DETAIL_TMPL = "https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno={hcno}"
# 只保留汽车/机动车相关的国标（过滤化妆品、养老、水龙头等无关标准）
GB_AUTO_KEYWORDS = ("汽车", "机动车", "车辆", "车用", "客车", "货车", "挂车", "摩托车",
                    "轮胎", "制动", "转向", "汽油", "柴油", "天然气", "电池", "充电",
                    "智能网联", "自动驾驶", "排放", "道路", "运输", "交通", "越野", "燃油")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.miit.gov.cn/",
}

# 只抓取最近 N 天
WINDOW_DAYS = 30
# =====================================================================


def _cutoff() -> str:
    return (datetime.now() - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")


def _get_with_retry(url, params=None, headers=None, timeout=30, verify=True, retries=3):
    """带重试的 GET，应对境外机房访问国内政府网站偶发超时/连接失败"""
    for attempt in range(retries):
        try:
            return requests.get(url, params=params, headers=headers, timeout=timeout, verify=verify)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt  # 1s / 2s / 4s
            print(f"[RETRY] {url} 第 {attempt + 1} 次失败（{type(e).__name__}），{wait}s 后重试")
            time.sleep(wait)


# ====================== 源1 工信部 ======================
def get_notice_list():
    """通过工信部接口获取列表，返回[{title,pub_date,detail_url}]"""
    resp = _get_with_retry(LIST_API, params=LIST_PARAMS, headers=HEADERS, timeout=60)
    resp.encoding = "utf-8"
    data = resp.json()
    html = data.get("data", {}).get("html", "")
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for li in soup.select(".page-content ul li"):
        a_tag = li.find("a")
        if not a_tag:
            continue
        title = a_tag.get("title") or a_tag.get_text(strip=True)
        href = a_tag.get("href", "")
        detail_url = ("https://www.miit.gov.cn" + href) if href.startswith("/") else href
        date_span = li.find("span")
        pub_date = date_span.get_text(strip=True) if date_span else ""
        items.append({"title": title, "pub_date": pub_date, "detail_url": detail_url})
    items = [it for it in items if it["pub_date"] >= _cutoff()]
    return items


def get_detail(url):
    """抓取工信部详情页正文"""
    time.sleep(1.2)
    resp = _get_with_retry(url, headers=HEADERS, timeout=60)
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    content_div = soup.select_one("#con_con") or soup.select_one(".ccontent")
    if not content_div:
        return ""
    return content_div.get_text("\n", strip=True)


# ====================== 源2 缺陷产品召回中心 ======================
def get_recall_list():
    """抓取召回中心「国内汽车召回」列表，返回[{title,pub_date,detail_url}]"""
    resp = _get_with_retry(RECALL_LIST_URL, headers=RECALL_HEADERS, timeout=30)
    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "html.parser")
    items = []
    for li in soup.select("li"):
        a_tag = li.find("a", href=True)
        if not a_tag:
            continue
        href = a_tag.get("href", "")
        # 只处理召回详情链接（形如 /202608/t20260821_115914.html），过滤导航项
        if not re.search(r"/t\d{8}_\d+\.html", href):
            continue
        title = a_tag.get("title") or a_tag.get_text(strip=True)
        date_span = li.find("span")
        date_text = date_span.get_text(strip=True) if date_span else ""
        m = re.search(r"\d{4}-\d{2}-\d{2}", date_text)
        pub_date = m.group(0) if m else ""
        detail_url = urljoin(RECALL_LIST_URL, href)
        items.append({"title": title, "pub_date": pub_date, "detail_url": detail_url})
    items = [it for it in items if it["pub_date"] >= _cutoff()]
    return items


def get_recall_detail(url):
    """抓取召回详情页正文"""
    time.sleep(1.2)
    resp = _get_with_retry(url, headers=RECALL_HEADERS, timeout=30)
    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "html.parser")
    content_div = soup.select_one(".show_txt") or soup.select_one(".TRS_Editor")
    if not content_div:
        return ""
    return content_div.get_text("\n", strip=True)


# ====================== 源3 全国汽标委 CATARC ======================
def get_catarc_list():
    """抓取汽标委工作动态里的标准发布/解读/制修订条目"""
    resp = _get_with_retry(CATARC_LIST_URL, headers=CATARC_HEADERS, timeout=30, verify=False)
    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "html.parser")
    items = []
    for li in soup.select("li"):
        a = li.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        if not re.search(r"/xwdt/\w+/\d+\.html", href):
            continue
        h3 = a.find("h3")
        title = h3.get_text(strip=True) if h3 else a.get_text(strip=True)
        # 只要标准相关的「发布/解读/征求意见/制修订」，过滤会议/审查会/宣贯会
        if not any(k in title for k in ("标准", "国标", "GB")):
            continue
        if any(k in title for k in ("会议", "审查会", "宣贯会", "工作组", "成立", "年会", "座谈", "研讨")):
            continue
        time_p = a.find("p", class_="time")
        pub_date = time_p.get_text(strip=True) if time_p else ""
        detail_url = urljoin("https://www.catarc.org.cn", href)
        items.append({"title": title, "pub_date": pub_date, "detail_url": detail_url})
    items = [it for it in items if it["pub_date"] >= _cutoff()]
    return items


def get_catarc_detail(url):
    """抓取 CATARC 详情页正文"""
    time.sleep(1.0)
    resp = _get_with_retry(url, headers=CATARC_HEADERS, timeout=30, verify=False)
    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "html.parser")
    content = None
    for sel in (".mainbox", ".TRS_Editor", ".article", ".article_content",
                ".content", ".show_txt", ".main_text"):
        content = soup.select_one(sel)
        if content:
            break
    if content is None:
        h = soup.find("h1") or soup.find("h3")
        if h:
            content = h.find_parent("div") or h.find_parent("td")
    if content is None:
        return ""
    return content.get_text("\n", strip=True)


# ====================== 源4 国家标准委 ======================
def get_gb_list():
    """抓取国标委「强制性/推荐性国标」近期发布列表（分页翻到 30 天边界）"""
    items = []
    cutoff = _cutoff()
    for p1, gb_type in (("1", "强制性国家标准"), ("2", "推荐性国家标准")):
        for page in range(1, 11):  # 安全上限，正常 1-2 页就触发 break
            params = {"p.p1": p1, "p.p90": "circulation_date", "p.p91": "desc",
                      "page": str(page), "pageSize": "50"}
            resp = _get_with_retry(GB_LIST_URL, params=params, headers=HEADERS, timeout=30, verify=False)
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, "html.parser")
            reached_cutoff = False
            row_count = 0
            for tr in soup.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) < 8:
                    continue
                std_no = tds[1].get_text(strip=True)
                name = tds[3].get_text(strip=True)
                status = tds[4].get_text(strip=True)
                pub_date = tds[5].get_text(strip=True).split(" ")[0]
                impl_date = tds[6].get_text(strip=True).split(" ")[0]
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", pub_date):
                    continue
                row_count += 1
                # 列表按发布日期降序，一旦早于 30 天边界，本页及后续页都不再需要
                if pub_date < cutoff:
                    reached_cutoff = True
                    break
                if not any(kw in name for kw in GB_AUTO_KEYWORDS):
                    continue
                hcno = ""
                btn = tds[7].find("button") or tds[7].find("a")
                if btn:
                    m = re.search(r"showInfo\('([A-Fa-f0-9]+)'\)", btn.get("onclick", "") or "")
                    if m:
                        hcno = m.group(1)
                items.append({
                    "title": f"{std_no} {name}",
                    "pub_date": pub_date,
                    "effect_time": impl_date,
                    "source_url": GB_DETAIL_TMPL.format(hcno=hcno) if hcno else "",
                    "content": f"{gb_type}（{status}）",
                })
            if reached_cutoff or row_count == 0:
                break
    return items


# ====================== 汇总 ======================
def _crawl_detail_source(name, list_func, detail_func):
    """抓取需要详情页正文的源（工信部/召回/汽标委），返回 [{source,title,pub_date,effect_time,url,content}]"""
    out = []
    for it in list_func():
        url = it["detail_url"]
        body = detail_func(url) if url else ""
        out.append({
            "source": name,
            "title": it["title"],
            "pub_date": it.get("pub_date", ""),
            "effect_time": "",
            "url": url,
            "content": body,
        })
    return out


def _crawl_gb_source():
    """抓取国标委（列表已含全部信息，无需详情页）"""
    out = []
    for it in get_gb_list():
        out.append({
            "source": "国家标准委",
            "title": it["title"],
            "pub_date": it["pub_date"],
            "effect_time": it.get("effect_time", ""),
            "url": it.get("source_url", ""),
            "content": it.get("content", ""),
        })
    return out


def build_report():
    report = {
        "collect_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window_days": WINDOW_DAYS,
        "sources": {},
        "items": [],
    }

    # 每个源独立 try/except，单个源挂了不影响整体
    jobs = [
        ("工信部", lambda: _crawl_detail_source("工信部", get_notice_list, get_detail)),
        ("召回中心", lambda: _crawl_detail_source("召回中心", get_recall_list, get_recall_detail)),
        ("汽标委", lambda: _crawl_detail_source("汽标委", get_catarc_list, get_catarc_detail)),
        ("国家标准委", _crawl_gb_source),
    ]
    for name, fn in jobs:
        try:
            items = fn()
            report["sources"][name] = {"status": "ok", "count": len(items)}
            report["items"].extend(items)
            print(f"[OK] {name}: {len(items)} 条")
        except Exception as e:
            report["sources"][name] = {"status": "failed", "count": 0, "reason": str(e)}
            print(f"[FAIL] {name}: {e}")

    report["total"] = len(report["items"])
    return report


def write_markdown(report, path="spider_result.md"):
    lines = []
    lines.append("# 越野车行业四源爬虫 · 抓取报告")
    lines.append("")
    lines.append(f"- 采集时间：{report['collect_time']}")
    lines.append(f"- 时间窗口：近 {report['window_days']} 天")
    lines.append(f"- 合计：{report['total']} 条")
    lines.append("")

    lines.append("## 来源概览")
    lines.append("")
    lines.append("| 来源 | 状态 | 条数 |")
    lines.append("| --- | --- | --- |")
    for name, s in report["sources"].items():
        if s["status"] == "ok":
            lines.append(f"| {name} | ✅ 成功 | {s['count']} |")
        else:
            lines.append(f"| {name} | ❌ 失败（{s.get('reason', '')}） | 0 |")
    lines.append("")

    # 按来源分组
    by_source = {}
    for it in report["items"]:
        by_source.setdefault(it["source"], []).append(it)

    lines.append("## 明细")
    lines.append("")
    for name, items in by_source.items():
        lines.append(f"### {name}（{len(items)} 条）")
        for it in items:
            title = it["title"]
            if it["url"]:
                lines.append(f"- **[{title}]({it['url']})**")
            else:
                lines.append(f"- **{title}**")
            meta = f"  {it['pub_date']}"
            if it.get("effect_time"):
                meta += f"　实施：{it['effect_time']}"
            lines.append(f"  {meta}")
            if it.get("content"):
                c = " ".join(it["content"].split())[:300]  # 压成单行并截断，避免 md 过长
                lines.append(f"  > {c}")
        lines.append("")
    return "\n".join(lines)


def main():
    print(f"[START] 采集开始，窗口：近 {WINDOW_DAYS} 天\n")
    report = build_report()

    with open("spider_result.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    md = write_markdown(report)
    with open("spider_result.md", "w", encoding="utf-8") as f:
        f.write(md)

    print(f"\n[DONE] 共 {report['total']} 条")
    print("已生成 spider_result.json / spider_result.md")
    ok = sum(1 for s in report["sources"].values() if s["status"] == "ok")
    fail = sum(1 for s in report["sources"].values() if s["status"] == "failed")
    print(f"[SUMMARY] 来源成功 {ok} / 失败 {fail}")


if __name__ == "__main__":
    main()
