#!/usr/bin/env python3
"""抓取 GitHub Trending 与近期新晋热门仓库，筛出 AI 相关项目。

输出：
  data/trending.json  —— 网站使用的结构化数据（含首次/最近上榜日期、历史 star）
  docs/Trending.md    —— 供 GitHub 阅读的 Markdown 版本

只依赖 Python 标准库。环境变量 GITHUB_TOKEN（可选）用于提高 Search API 限额。
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "trending.json"
MD_FILE = ROOT / "docs" / "Trending.md"
EXCLUDE_FILE = ROOT / "data" / "trending_exclude.txt"  # 手动排除的仓库，每行一个 owner/repo
# 越狱、破解、成人内容等不适合收录的项目
EXCLUDE_RE = re.compile(r"jailbreak|破甲|越狱|\bnsfw\b|crack(ed)?\b|keygen|免费白嫖", re.I)

UA = "awesome-chatgpt-zh-trending-bot (+https://github.com/yzfly/awesome-chatgpt-zh)"
TODAY = dt.date.today().isoformat()
KEEP_DAYS = 45          # 超过该天数未再上榜的条目移出列表
MAX_ITEMS = 300

# 关键词：命中仓库名 / 简介 / topics 即视为 AI 相关
AI_PATTERNS = [
    r"\bai\b", r"\bagi\b", r"\bllms?\b", r"\bgpt", r"chatgpt", r"openai", r"claude", r"anthropic",
    r"gemini", r"deepseek", r"\bqwen", r"\bglm\b", r"kimi", r"\bgrok\b", r"llama", r"mistral",
    r"\bagents?\b", r"agentic", r"\bmcp\b", r"model context protocol", r"\brag\b", r"embedding",
    r"vector (db|database|store)", r"diffusion", r"text-to-(image|video|speech)", r"\btts\b", r"\basr\b",
    r"whisper", r"comfyui", r"stable.?diffusion", r"\bflux\b", r"transformer", r"fine-?tun", r"\blora\b",
    r"inference", r"\bvllm\b", r"ollama", r"prompt", r"copilot", r"codex", r"cursor", r"vibe.?coding",
    r"coding agent", r"machine learning", r"deep learning", r"neural", r"multimodal", r"\bvlm\b",
    r"reasoning", r"chatbot", r"large language", r"语言模型", r"大模型", r"智能体", r"人工智能", r"生成式",
    r"skills?\b.*(agent|claude|codex)", r"computer.?use", r"browser.?use", r"speech", r"voice clon",
]
AI_RE = re.compile("|".join(AI_PATTERNS), re.I)
AI_TOPICS = {
    "ai", "llm", "llms", "chatgpt", "openai", "claude", "claude-code", "anthropic", "gemini", "deepseek",
    "agent", "agents", "ai-agent", "ai-agents", "mcp", "mcp-server", "rag", "generative-ai", "genai",
    "machine-learning", "deep-learning", "stable-diffusion", "comfyui", "llama", "ollama", "codex",
    "artificial-intelligence", "large-language-models", "agentic-ai", "vibe-coding", "prompt-engineering",
}

# 分类：按顺序匹配第一个命中的规则
CATEGORIES = [
    ("编程智能体", r"claude.?code|codex|coding agent|cursor|copilot|vibe.?coding|\bide\b|code (review|assistant)|terminal agent|opencode|gemini.?cli"),
    ("MCP / Skills", r"\bmcp\b|model context protocol|\bskills?\b"),
    ("API 代理与网关", r"gateway|proxy|relay|router|中转|api key|openai.?compatible|load.?balanc"),
    ("语音与音频", r"speech|voice|\btts\b|\basr\b|audio|whisper|music|语音"),
    ("图像与视频", r"image|video|diffusion|comfyui|\bflux\b|text-to-(image|video)|绘|生图|视频"),
    ("浏览器与自动化", r"browser|computer.?use|crawl|scrap|automation|web agent|爬"),
    ("RAG 与知识库", r"\brag\b|retriev|knowledge|vector|embedding|memory|知识库|记忆"),
    ("模型与训练", r"model|train|fine-?tun|inference|\bvllm\b|quantiz|weights|llama|qwen|deepseek|transformer|模型"),
    ("智能体框架", r"agent|agentic|workflow|orchestrat|智能体"),
]
CAT_RES = [(name, re.compile(p, re.I)) for name, p in CATEGORIES]


def http_get(url: str, accept: str = "text/html", token: str | None = None, retries: int = 3) -> str:
    headers = {"User-Agent": UA, "Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last: Exception | None = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError) as e:  # 网络抖动重试
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def to_int(s: str) -> int:
    s = s.replace(",", "").strip()
    return int(s) if s.isdigit() else 0


def parse_trending_page(page: str) -> list[dict]:
    """解析 github.com/trending 页面。结构变化时宁可少抓，不抛异常中断。"""
    repos = []
    for art in re.findall(r'<article class="Box-row">(.*?)</article>', page, re.S):
        m = re.search(r'<h2[^>]*>\s*<a[^>]*href="/([^"/]+/[^"/]+)"', art, re.S)
        if not m:
            continue
        full = m.group(1).strip()
        desc_m = re.search(r'<p class="[^"]*col-9[^"]*">(.*?)</p>', art, re.S)
        lang_m = re.search(r'itemprop="programmingLanguage">([^<]+)<', art)
        stars_m = re.search(rf'href="/{re.escape(full)}/stargazers"[^>]*>(.*?)</a>', art, re.S)
        period_m = re.search(r'([\d,]+)\s+stars\s+(today|this week|this month)', art)
        repos.append({
            "repo": full,
            "description": strip_tags(desc_m.group(1)) if desc_m else "",
            "language": lang_m.group(1).strip() if lang_m else "",
            "stars": to_int(strip_tags(stars_m.group(1))) if stars_m else 0,
            "gained": to_int(period_m.group(1)) if period_m else 0,
        })
    return repos


def fetch_trending() -> list[dict]:
    found: dict[str, dict] = {}
    for since in ("daily", "weekly"):
        for lang in ("", "python", "typescript", "rust", "go", "jupyter-notebook"):
            url = f"https://github.com/trending/{lang}?since={since}" if lang else f"https://github.com/trending?since={since}"
            try:
                items = parse_trending_page(http_get(url))
            except RuntimeError as e:
                print(f"[warn] {e}", file=sys.stderr)
                continue
            for it in items:
                it["source"] = f"trending-{since}"
                prev = found.get(it["repo"])
                # 同仓库多次出现时，保留日榜来源与较大的增量
                if not prev or (since == "daily" and prev["source"] != "trending-daily"):
                    found[it["repo"]] = it
            time.sleep(1)
    return list(found.values())


def fetch_rising(token: str | None) -> list[dict]:
    """GitHub Search：近 30 天创建、star 增长快的 AI 仓库（补足 Trending 页面覆盖不到的）。"""
    since = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    queries = [
        f"topic:llm created:>{since} stars:>300",
        f"topic:ai-agents created:>{since} stars:>300",
        f"topic:mcp created:>{since} stars:>200",
        f"topic:claude-code created:>{since} stars:>200",
        f"topic:codex created:>{since} stars:>200",
        f"topic:generative-ai created:>{since} stars:>300",
        f"agent in:name,description created:>{since} stars:>800",
    ]
    out: dict[str, dict] = {}
    for q in queries:
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
            {"q": q, "sort": "stars", "order": "desc", "per_page": 30})
        try:
            data = json.loads(http_get(url, "application/vnd.github+json", token))
        except (RuntimeError, json.JSONDecodeError) as e:
            print(f"[warn] search {q!r}: {e}", file=sys.stderr)
            continue
        for r in data.get("items", []):
            if r.get("fork") or r.get("archived"):
                continue
            out[r["full_name"]] = {
                "repo": r["full_name"],
                "description": r.get("description") or "",
                "language": r.get("language") or "",
                "stars": r.get("stargazers_count", 0),
                "gained": 0,
                "topics": r.get("topics", []),
                "created": (r.get("created_at") or "")[:10],
                "source": "rising",
            }
        time.sleep(2 if token else 7)  # 未认证 Search API 限额 10 次/分钟
    return list(out.values())


def is_ai(it: dict, excluded: set[str]) -> bool:
    text = f"{it['repo']} {it.get('description', '')}"
    if it["repo"].lower() in excluded or EXCLUDE_RE.search(text):
        return False
    return bool(AI_RE.search(text)) or bool(AI_TOPICS & set(it.get("topics", [])))


def categorize(it: dict) -> str:
    text = f"{it['repo']} {it.get('description', '')} {' '.join(it.get('topics', []))}"
    for name, rx in CAT_RES:
        if rx.search(text):
            return name
    return "其他 AI"


def load_existing() -> dict[str, dict]:
    if DATA_FILE.exists():
        try:
            return {it["repo"]: it for it in json.loads(DATA_FILE.read_text("utf-8")).get("items", [])}
        except (json.JSONDecodeError, KeyError):
            pass
    return {}


def merge(existing: dict[str, dict], fresh: list[dict]) -> list[dict]:
    for it in fresh:
        old = existing.get(it["repo"], {})
        hist = old.get("history", [])
        if not hist or hist[-1][0] != TODAY:
            hist.append([TODAY, it["stars"]])
        else:
            hist[-1][1] = it["stars"]
        existing[it["repo"]] = {
            **old,
            **{k: v for k, v in it.items() if v not in ("", None, [])},
            "description": it.get("description") or old.get("description", ""),
            "url": f"https://github.com/{it['repo']}",
            "category": categorize(it),
            "first_seen": old.get("first_seen", TODAY),
            "last_seen": TODAY,
            "times_seen": old.get("times_seen", 0) + (0 if old.get("last_seen") == TODAY else 1),
            "history": hist[-30:],
        }
    cutoff = (dt.date.today() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    items = [v for v in existing.values() if v.get("last_seen", "") >= cutoff]
    # 今日上榜优先，其次按增量 / star 排序
    items.sort(key=lambda x: (x["last_seen"], x.get("gained", 0), x.get("stars", 0)), reverse=True)
    return items[:MAX_ITEMS]


def write_markdown(items: list[dict]) -> None:
    today_items = [i for i in items if i["last_seen"] == TODAY]
    lines = [
        "# GitHub AI 热门项目（自动更新）",
        "",
        f"> 由 [scripts/fetch_trending.py](../scripts/fetch_trending.py) 每日自动抓取 GitHub Trending 与近 30 天新晋热门仓库，"
        f"按关键词筛选 AI 相关项目。最近更新：{TODAY}，今日上榜 {len(today_items)} 个，近 {KEEP_DAYS} 天累计 {len(items)} 个。",
        "> 自动收录仅代表热度，不代表推荐；经人工评审的优质项目会移入对应专题。",
        "",
    ]
    by_cat: dict[str, list[dict]] = {}
    for it in today_items:
        by_cat.setdefault(it["category"], []).append(it)
    for cat, rows in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        lines += [f"## {cat}", "", "| 项目 | Stars | 新增 | 语言 | 简介 |", "|---|---|---|---|---|"]
        for r in rows:
            desc = (r.get("description") or "-").replace("|", "\\|").replace("\n", " ")
            gained = f"+{r['gained']}" if r.get("gained") else "新晋"
            lines.append(f"| [{r['repo']}]({r['url']}) | {r['stars']:,} | {gained} | {r.get('language') or '-'} | {desc} |")
        lines.append("")
    MD_FILE.write_text("\n".join(lines), "utf-8")


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    candidates = fetch_trending() + fetch_rising(token)
    excluded = set()
    if EXCLUDE_FILE.exists():
        excluded = {l.strip().lower() for l in EXCLUDE_FILE.read_text("utf-8").splitlines() if l.strip() and not l.startswith("#")}
    ai = [c for c in candidates if is_ai(c, excluded)]
    if not ai:
        print("[error] 没有抓到任何 AI 项目，保留旧数据", file=sys.stderr)
        return 1
    existing = {k: v for k, v in load_existing().items()
                if k.lower() not in excluded and not EXCLUDE_RE.search(f"{k} {v.get('description', '')}")}
    items = merge(existing, ai)
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps({"updated": TODAY, "items": items}, ensure_ascii=False, indent=1), "utf-8")
    write_markdown(items)
    print(f"候选 {len(candidates)}，AI 相关 {len(ai)}，列表共 {len(items)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
