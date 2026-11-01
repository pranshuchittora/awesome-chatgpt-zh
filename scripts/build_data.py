#!/usr/bin/env python3
"""把 docs/*.md 解析成网站使用的 site/data/resources.json。

Markdown 仍是唯一数据源：表格行、列表项、带链接的标题都会被识别为一条资源。
若提供 GITHUB_TOKEN，会通过 GraphQL 批量补全 GitHub 仓库的 star / 语言 / 更新时间（结果缓存于 data/repo_meta.json）。
只依赖 Python 标准库。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT_DIR = ROOT / "site" / "data"
META_CACHE = ROOT / "data" / "repo_meta.json"
TRENDING = ROOT / "data" / "trending.json"
REPO_URL = "https://github.com/EmbraceAGI/awesome-chatgpt-zh/blob/main/docs/"

# 专题顺序与展示信息：(文件, slug, 标题, 一句话说明, 分组)
TOPICS = [
    ("Claude_Code_Codex.md", "claude-code-codex", "Claude Code & Codex", "官方入口、配置切换、用量统计、多会话与工作流框架", "编程"),
    ("Coding_Agents.md", "coding-agents", "编程智能体", "终端 / IDE 编码 Agent、自主软件工程与评测", "编程"),
    ("API_Proxy.md", "api-proxy", "API 代理与模型路由", "AI 网关、订阅转 API、编码 Agent 换模型", "编程"),
    ("Claude_Skills.md", "claude-skills", "Claude Skills", "Agent Skills 官方资源、技能仓库与工具", "智能体"),
    ("MCP.md", "mcp", "MCP 协议", "模型上下文协议规范、客户端与精选 Servers", "智能体"),
    ("Browser_Computer_Use.md", "browser-computer-use", "浏览器与计算机自动化", "Browser Use、Computer Use、反检测与评测", "智能体"),
    ("Agent_First.md", "agent-first", "Agent-First", "为智能体而构建的理念、标准与实践", "智能体"),
    ("AGI.md", "agi", "通用 Agent 与 AGI", "通用 AI Agent 产品与研究基准", "智能体"),
    ("Image_Generation.md", "image-generation", "AI 生图", "GPT Image、Nano Banana、FLUX、ComfyUI 与提示词", "创作"),
    ("Sora.md", "video", "AI 视频", "Sora 与主流视频生成工具", "创作"),
    ("AI_tools.md", "ai-tools", "AI 生产力工具", "对话、搜索、绘画、写作、PPT、语音等", "创作"),
    ("ChatGPT_tools.md", "chatgpt-tools", "ChatGPT 应用", "精选 AI 应用与经典 ChatGPT 工具", "创作"),
    ("ChatGPT_access.md", "access", "使用途径", "官方入口、第三方客户端、国内外 AI 助手", "入门"),
    ("ChatGPT_prompts.md", "prompts", "Prompt 工程", "中文提示词、LangGPT 与系统学习资源", "入门"),
    ("ChatGPT_plugins.md", "gpts", "GPTs 与扩展", "GPT Store、Actions 与 GPTs 合集", "入门"),
    ("LLMs.md", "llms", "大模型", "2024–2026 主流模型、国产模型与评测榜单", "模型"),
    ("DeepSeek.md", "deepseek", "DeepSeek 生态", "V4 模型、API、编程智能体接入与部署", "模型"),
    ("ChatGPT_dev.md", "dev", "应用开发", "官方资源、Agent 框架、向量库、API 网关", "开发"),
    ("LLM_RAG.md", "rag", "RAG 检索增强", "开源 RAG 框架、Embedding 与 Reranker", "开发"),
    ("ChatGPT_Top_Project.md", "top-projects", "10K+ 爆款开源", "GitHub 上最受欢迎的 LLM 相关项目", "开发"),
    ("OpenAI_articles.md", "articles", "经典技术文章", "OpenAI、Anthropic、DeepMind 等经典论文与博客", "阅读"),
    ("thinking.md", "thinking", "思考", "AI 时代的重要长文与观点", "阅读"),
    ("AI_money.md", "ai-money", "AI 搞钱", "AI 副业与变现方向", "阅读"),
]

LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
GH_RE = re.compile(r"https?://github\.com/([\w.-]+)/([\w.-]+)")
BADGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
CJK_RE = re.compile(r"[一-鿿]")


def clean(text: str) -> str:
    """去掉 Markdown 标记，保留可读文本。"""
    text = BADGE_RE.sub("", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\*\*|__|`|<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip(" -—:：|·・")


def gh_repo(url: str) -> str | None:
    m = GH_RE.match(url)
    if not m:
        return None
    owner, name = m.group(1), m.group(2).removesuffix(".git")
    if owner.lower() in {"features", "topics", "orgs", "apps", "marketplace", "sponsors", "settings", "collections"}:
        return None
    return f"{owner}/{name}"


def pick_url(cells_or_text: str) -> str | None:
    links = [u for _, u in LINK_RE.findall(BADGE_RE.sub("", cells_or_text))]
    if not links:
        return None
    # 优先 GitHub 仓库链接，其次第一个链接
    for u in links:
        if gh_repo(u):
            return u
    return links[0]


def is_trivial(cell: str) -> bool:
    c = clean(cell)
    return not c or c in {"-", "链接", "GitHub", "官网", "文档"} or (len(c) < 3 and not CJK_RE.search(c))


def parse_table_row(cells: list[str]) -> dict | None:
    name_cell = cells[0]
    name = clean(name_cell)
    url = pick_url(name_cell) or pick_url("|".join(cells))
    if not name or not url:
        return None
    desc_cells = [c for c in cells[1:] if not is_trivial(c) and not re.fullmatch(r"\s*(\[[^\]]+\]\([^)]*\)\s*[・·,，/ ]*)+\s*", BADGE_RE.sub("", c))]
    # 4 列表格（名称|Stars|英文简介|中文备注）：优先中文描述
    zh = [c for c in desc_cells if CJK_RE.search(c)]
    desc = clean((zh or desc_cells or [""])[-1])
    if zh and desc_cells and desc_cells[0] not in zh and len(zh) == 1:
        en = clean(desc_cells[0])
        desc = desc if len(desc) > 15 else f"{desc} {en}".strip()
    return {"name": name, "url": url, "desc": desc}


def parse_doc(path: Path) -> tuple[str, list[dict]]:
    lines = path.read_text("utf-8").splitlines()
    intro_lines: list[str] = []
    entries: list[dict] = []
    section = ""
    seen_first_heading = False
    pending_heading: dict | None = None  # 带链接的标题，取其后第一段为描述

    for raw in lines:
        line = raw.rstrip()
        h = re.match(r"^(#{1,4})\s+(.*)$", line)
        if h:
            level, title = len(h.group(1)), h.group(2)
            if pending_heading is not None:
                entries.append(pending_heading)
                pending_heading = None
            if level == 1 or not seen_first_heading:
                seen_first_heading = True
                continue
            url = pick_url(title)
            if url and level >= 3:
                pending_heading = {"name": clean(title), "url": url, "desc": "", "section": section}
            else:
                section = clean(title)
            continue

        if pending_heading is not None and line.strip() and not line.startswith("|"):
            text = clean(re.sub(r"^\s*[-*>]\s*", "", line))
            if text and len(pending_heading["desc"]) < 160:
                pending_heading["desc"] = (pending_heading["desc"] + " " + text).strip()
            continue

        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c) or len(cells) < 2:
                continue
            if clean(cells[0]) in {"名称", "项目", "名字", "Name", "模型"} and not pick_url(line):
                continue
            row = parse_table_row(cells)
            if row:
                row["section"] = section
                entries.append(row)
            continue

        li = re.match(r"^\s*[-*]\s+(.*)$", line)
        if li and pick_url(li.group(1)):
            body = li.group(1)
            m = LINK_RE.search(body)
            name = clean(m.group(1)) if m else clean(body)
            rest = clean(body[m.end():]) if m else ""
            entries.append({"name": name, "url": pick_url(body), "desc": rest, "section": section})
            continue

        if not seen_first_heading or (not entries and not section):
            text = clean(line.lstrip("> "))
            if text and not line.startswith("!") and "](#" not in line:
                intro_lines.append(text)

    if pending_heading is not None:
        entries.append(pending_heading)

    # 同一文档内按 URL 去重（保留描述更长者）
    uniq: dict[str, dict] = {}
    for e in entries:
        key = e["url"].rstrip("/").lower()
        if key not in uniq or len(e["desc"]) > len(uniq[key]["desc"]):
            uniq[key] = e
    intro = " ".join(intro_lines)
    if len(intro) > 220:  # 在句号处截断，避免半句话
        cut = max(intro.rfind(p, 0, 220) for p in "。！？")
        intro = intro[: cut + 1] if cut > 60 else intro[:220] + "…"
    return intro, list(uniq.values())


def fetch_repo_meta(repos: set[str], token: str) -> dict[str, dict]:
    cache: dict[str, dict] = json.loads(META_CACHE.read_text("utf-8")) if META_CACHE.exists() else {}
    todo = sorted(repos)
    fetched = 0
    for i in range(0, len(todo), 80):
        chunk = todo[i:i + 80]
        parts = []
        for j, full in enumerate(chunk):
            owner, name = full.split("/", 1)
            parts.append(f'r{j}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) '
                         '{ nameWithOwner stargazerCount pushedAt isArchived primaryLanguage { name } }')
        query = "query {" + "\n".join(parts) + "}"
        req = urllib.request.Request(
            "https://api.github.com/graphql",
            data=json.dumps({"query": query}).encode(),
            headers={"Authorization": f"Bearer {token}", "User-Agent": "awesome-chatgpt-zh-build"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read()).get("data") or {}
        except Exception as e:  # 网络失败时沿用缓存
            print(f"[warn] graphql: {e}", file=sys.stderr)
            continue
        for j, full in enumerate(chunk):
            node = data.get(f"r{j}")
            if node:
                cache[full.lower()] = {
                    "stars": node["stargazerCount"],
                    "pushed": (node["pushedAt"] or "")[:10],
                    "archived": node["isArchived"],
                    "lang": (node.get("primaryLanguage") or {}).get("name", ""),
                }
                fetched += 1
    META_CACHE.parent.mkdir(parents=True, exist_ok=True)
    META_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0, sort_keys=True), "utf-8")
    print(f"GitHub 元数据：本次更新 {fetched} 个仓库")
    return cache


def main() -> int:
    topics_out, items = [], []
    for fname, slug, title, blurb, group in TOPICS:
        path = DOCS / fname
        if not path.exists():
            print(f"[warn] 缺少 {fname}", file=sys.stderr)
            continue
        intro, entries = parse_doc(path)
        sections = []
        for e in entries:
            if e["section"] and e["section"] not in sections:
                sections.append(e["section"])
            items.append({**e, "topic": slug})
        topics_out.append({"slug": slug, "title": title, "blurb": blurb, "group": group, "intro": intro,
                           "count": len(entries), "sections": sections, "source": REPO_URL + fname})

    for it in items:
        repo = gh_repo(it["url"])
        if repo:
            it["repo"] = repo

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repos = {it["repo"] for it in items if "repo" in it}
    if token:
        meta = fetch_repo_meta(repos, token)
    else:
        meta = json.loads(META_CACHE.read_text("utf-8")) if META_CACHE.exists() else {}
    for it in items:
        m = meta.get(it.get("repo", "").lower())
        if m:
            it.update({"stars": m["stars"], "pushed": m["pushed"], "lang": m["lang"]})
            if m["archived"]:
                it["archived"] = True

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
               "topics": topics_out, "items": items}
    (OUT_DIR / "resources.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), "utf-8")
    if TRENDING.exists():
        shutil.copyfile(TRENDING, OUT_DIR / "trending.json")
    print(f"专题 {len(topics_out)} 个，资源 {len(items)} 条（GitHub 仓库 {len(repos)} 个）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
