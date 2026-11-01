/* ChatGPT 中文指南 · 前端（无依赖） */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const PAGE = 60;
  const NEW_TOPICS = new Set(["claude-code-codex", "api-proxy", "image-generation"]);
  const state = { data: null, trending: null, query: "", page: PAGE };
  const ui = {}; // 每个视图内的筛选状态，按路由保存

  const fmt = (n) => (n >= 10000 ? (n / 1000).toFixed(n >= 100000 ? 0 : 1) + "k" : String(n ?? ""));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const host = (url) => { try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return ""; } };
  const starSvg = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 .9l2.2 4.5 4.9.7-3.6 3.5.9 4.9L8 12.2l-4.4 2.3.9-4.9L.9 6.1l4.9-.7z"/></svg>';

  function highlight(text, q) {
    const safe = esc(text);
    if (!q) return safe;
    const terms = q.split(/\s+/).filter(Boolean).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    if (!terms.length) return safe;
    return safe.replace(new RegExp(`(${terms.map(esc).join("|")})`, "gi"), "<mark>$1</mark>");
  }

  function matches(item, q) {
    if (!q) return true;
    const hay = `${item.name} ${item.desc || item.description || ""} ${item.section || ""} ${item.repo || ""} ${item.category || ""}`.toLowerCase();
    return q.toLowerCase().split(/\s+/).filter(Boolean).every((t) => hay.includes(t));
  }

  function favicon(item) {
    const repo = item.repo;
    const letter = esc((item.name || "?").replace(/^[^\p{L}\p{N}]+/u, "").charAt(0).toUpperCase() || "?");
    if (repo) {
      const owner = repo.split("/")[0];
      return `<span class="favicon">${letter}<img src="https://github.com/${encodeURIComponent(owner)}.png?size=68" alt="" loading="lazy" decoding="async" onerror="this.remove()"></span>`;
    }
    return `<span class="favicon">${letter}</span>`;
  }

  function topicTitle(slug) {
    return state.data.topics.find((t) => t.slug === slug)?.title || slug;
  }

  // ---------- 卡片 ----------
  function resourceCard(it, opts = {}) {
    const q = state.query;
    const tags = [];
    if (opts.showTopic) tags.push(`<span class="tag">${esc(topicTitle(it.topic))}</span>`);
    if (it.section) tags.push(`<span class="tag muted">${highlight(it.section, q)}</span>`);
    if (it.lang) tags.push(`<span class="tag muted">${esc(it.lang)}</span>`);
    if (it.archived) tags.push('<span class="tag warn">已归档</span>');
    return `<a class="card glass" href="${esc(it.url)}" target="_blank" rel="noopener">
      <div class="card-top">${favicon(it)}
        <div class="card-title"><h3>${highlight(it.name, q)}</h3><span class="host">${esc(it.repo || host(it.url))}</span></div>
        ${it.stars != null ? `<span class="stars" title="${it.stars.toLocaleString()} stars">${starSvg}${fmt(it.stars)}</span>` : ""}
      </div>
      ${it.desc ? `<p>${highlight(it.desc, q)}</p>` : ""}
      <div class="card-meta">${tags.join("")}</div>
    </a>`;
  }

  function sparkline(hist) {
    if (!hist || hist.length < 2) return "";
    const ys = hist.map((h) => h[1]);
    const min = Math.min(...ys), max = Math.max(...ys);
    const w = 100, h = 30, span = max - min || 1;
    const pts = ys.map((y, i) => [(i / (ys.length - 1)) * w, h - 3 - ((y - min) / span) * (h - 6)]);
    const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
      <path class="area" d="${d}L${w},${h}L0,${h}Z"/><path class="line" d="${d}" vector-effect="non-scaling-stroke"/></svg>`;
  }

  function trendCard(it, rank) {
    const q = state.query;
    const gained = it.gained ? `<span class="tag up">+${fmt(it.gained)} ${it.source === "trending-weekly" ? "本周" : "今日"}</span>` : '<span class="tag up">新晋</span>';
    return `<a class="card glass trend-card" href="${esc(it.url)}" target="_blank" rel="noopener">
      <div class="card-top">${favicon({ name: it.repo.split("/")[1], repo: it.repo })}
        <div class="card-title"><h3>${rank ? `<span class="rank">#${rank}</span>` : ""}${highlight(it.repo.split("/")[1], q)}</h3><span class="host">${esc(it.repo.split("/")[0])}</span></div>
        <span class="stars" title="${(it.stars || 0).toLocaleString()} stars">${starSvg}${fmt(it.stars)}</span>
      </div>
      ${it.description ? `<p>${highlight(it.description, q)}</p>` : ""}
      ${sparkline(it.history)}
      <div class="card-meta">${gained}<span class="tag">${esc(it.category)}</span>${it.language ? `<span class="tag muted">${esc(it.language)}</span>` : ""}
        <span class="tag muted" title="首次上榜">${esc(it.first_seen)}</span></div>
    </a>`;
  }

  // ---------- 分页渲染 ----------
  function renderList(list, renderFn, container) {
    const shown = list.slice(0, state.page);
    container.innerHTML = shown.length ? `<div class="grid">${shown.map(renderFn).join("")}</div>` : '<div class="empty glass">没有匹配的结果，换个关键词试试。</div>';
    if (list.length > state.page) {
      const btn = document.createElement("button");
      btn.className = "more";
      btn.textContent = `加载更多（剩余 ${list.length - state.page}）`;
      btn.onclick = () => { state.page += PAGE; renderList(list, renderFn, container); };
      container.appendChild(btn);
      // 滚动到底部时自动加载
      const io = new IntersectionObserver((ents) => { if (ents[0].isIntersecting) { io.disconnect(); btn.click(); } }, { rootMargin: "400px" });
      io.observe(btn);
    }
  }

  // ---------- 侧边栏 ----------
  function renderSidebar(active) {
    const groups = {};
    for (const t of state.data.topics) (groups[t.group] ||= []).push(t);
    const trendCount = todayTrending().length;
    let html = `<div class="side-group"><h3>导航</h3>
      <a class="side-link" href="#/" ${active === "home" ? 'aria-current="page"' : ""}>全部专题<span class="n">${state.data.items.length}</span></a>
      <a class="side-link hot" href="#/trending" ${active === "trending" ? 'aria-current="page"' : ""}>今日 AI 热门<span class="n">${trendCount}</span></a></div>`;
    for (const [g, ts] of Object.entries(groups)) {
      html += `<div class="side-group"><h3>${esc(g)}</h3>${ts.map((t) =>
        `<a class="side-link${NEW_TOPICS.has(t.slug) ? " new" : ""}" href="#/t/${t.slug}" ${active === t.slug ? 'aria-current="page"' : ""}>${esc(t.title)}<span class="n">${t.count}</span></a>`).join("")}</div>`;
    }
    $("#sidebar").innerHTML = html;
  }

  function todayTrending() {
    const t = state.trending;
    if (!t) return [];
    return t.items.filter((i) => i.last_seen === t.updated);
  }

  // ---------- 视图 ----------
  function viewHome(el) {
    const topics = state.data.topics;
    const hot = todayTrending().slice(0, 6);
    el.innerHTML = `
      <div class="section-title"><h2>专题</h2></div>
      <div class="topic-grid">${topics.map((t) => `
        <a class="topic-card glass" href="#/t/${t.slug}">
          <span class="grp">${esc(t.group)}${NEW_TOPICS.has(t.slug) ? " · 新专题" : ""}</span>
          <h3>${esc(t.title)}</h3><p>${esc(t.blurb)}</p><span class="cnt">${t.count} 条资源</span>
        </a>`).join("")}</div>
      ${hot.length ? `<div class="section-title"><h2>今日 AI 热门</h2><a href="#/trending">查看全部 →</a></div>
      <div class="grid">${hot.map((it, i) => trendCard(it, i + 1)).join("")}</div>` : ""}
      <div class="section-title" style="margin-top:36px"><h2>高星项目</h2></div>
      <div id="topStars"></div>`;
    const seen = new Set();
    const top = state.data.items.filter((i) => i.stars && !seen.has(i.repo) && seen.add(i.repo)).sort((a, b) => b.stars - a.stars);
    state.page = 24;
    renderList(top, (it) => resourceCard(it, { showTopic: true }), $("#topStars"));
  }

  function viewTopic(el, slug) {
    const topic = state.data.topics.find((t) => t.slug === slug);
    if (!topic) return viewNotFound(el);
    const st = (ui[slug] ||= { section: "", sort: "default" });
    const items = state.data.items.filter((i) => i.topic === slug);
    const counts = {};
    for (const i of items) counts[i.section] = (counts[i.section] || 0) + 1;
    el.innerHTML = `
      <div class="content-head"><div><h2>${esc(topic.title)}</h2><p>${esc(topic.intro || topic.blurb)}</p></div>
        <a class="source" href="${esc(topic.source)}" target="_blank" rel="noopener">在 GitHub 查看原文 ↗</a></div>
      <div class="toolbar">
        <div class="chips" role="group" aria-label="分区">
          <button class="chip" data-sec="" aria-pressed="${!st.section}">全部<span class="n">${items.length}</span></button>
          ${topic.sections.filter((s) => counts[s]).map((s) => `<button class="chip" data-sec="${esc(s)}" aria-pressed="${st.section === s}">${esc(s)}<span class="n">${counts[s]}</span></button>`).join("")}
        </div>
        <div class="seg" role="group" aria-label="排序">
          <button data-sort="default" aria-pressed="${st.sort === "default"}">编辑顺序</button>
          <button data-sort="stars" aria-pressed="${st.sort === "stars"}">按 Star</button>
        </div>
      </div>
      <div id="list"></div>`;
    const draw = () => {
      let list = items.filter((i) => !st.section || i.section === st.section);
      if (st.sort === "stars") list = [...list].sort((a, b) => (b.stars || -1) - (a.stars || -1));
      state.page = PAGE;
      renderList(list, (it) => resourceCard(it), $("#list"));
    };
    el.querySelectorAll("[data-sec]").forEach((b) => b.addEventListener("click", () => {
      st.section = b.dataset.sec;
      el.querySelectorAll("[data-sec]").forEach((x) => x.setAttribute("aria-pressed", x === b));
      draw();
    }));
    el.querySelectorAll("[data-sort]").forEach((b) => b.addEventListener("click", () => {
      st.sort = b.dataset.sort;
      el.querySelectorAll("[data-sort]").forEach((x) => x.setAttribute("aria-pressed", x === b));
      draw();
    }));
    draw();
  }

  function viewTrending(el) {
    const t = state.trending;
    if (!t || !t.items.length) {
      el.innerHTML = '<div class="empty glass">热门数据尚未生成。运行 <code>scripts/fetch_trending.py</code> 后刷新。</div>';
      return;
    }
    const st = (ui.trending ||= { cat: "", range: "today", sort: "gained" });
    const weekAgo = new Date(Date.parse(t.updated) - 7 * 864e5).toISOString().slice(0, 10);
    const inRange = (i) => st.range === "all" || (st.range === "today" ? i.last_seen === t.updated : i.last_seen >= weekAgo);
    const ranged = t.items.filter(inRange);
    const counts = {};
    for (const i of ranged) counts[i.category] = (counts[i.category] || 0) + 1;
    const cats = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
    if (st.cat && !counts[st.cat]) st.cat = "";
    el.innerHTML = `
      <div class="content-head"><div><h2>GitHub AI 热门</h2>
        <p>每日自动抓取 GitHub Trending（日榜 / 周榜，多语言）与近 30 天新晋高星仓库，按关键词筛出 AI 相关项目并自动分类。</p></div>
        <span class="source">更新于 ${esc(t.updated)}</span></div>
      <p class="trend-note glass">自动收录只反映热度，不代表推荐。人工评审过的优质项目会移入对应专题。</p>
      <div class="toolbar">
        <div class="seg" role="group" aria-label="时间范围">
          <button data-range="today" aria-pressed="${st.range === "today"}">今日</button>
          <button data-range="week" aria-pressed="${st.range === "week"}">近 7 天</button>
          <button data-range="all" aria-pressed="${st.range === "all"}">近 45 天</button>
        </div>
        <div class="seg" role="group" aria-label="排序">
          <button data-sort="gained" aria-pressed="${st.sort === "gained"}">按增长</button>
          <button data-sort="stars" aria-pressed="${st.sort === "stars"}">按 Star</button>
          <button data-sort="new" aria-pressed="${st.sort === "new"}">最新上榜</button>
        </div>
      </div>
      <div class="toolbar"><div class="chips" role="group" aria-label="分类">
        <button class="chip" data-cat="" aria-pressed="${!st.cat}">全部<span class="n">${ranged.length}</span></button>
        ${cats.map((c) => `<button class="chip" data-cat="${esc(c)}" aria-pressed="${st.cat === c}">${esc(c)}<span class="n">${counts[c]}</span></button>`).join("")}
      </div></div>
      <div id="list"></div>`;
    let list = ranged.filter((i) => !st.cat || i.category === st.cat);
    const daily = (i) => (i.gained || 0) / (i.source === "trending-weekly" ? 7 : 1);
    const sorters = {
      // 周榜增量折算成日均，与日榜可比
      gained: (a, b) => daily(b) - daily(a) || b.stars - a.stars,
      stars: (a, b) => b.stars - a.stars,
      new: (a, b) => b.first_seen.localeCompare(a.first_seen) || (b.gained || 0) - (a.gained || 0),
    };
    list = [...list].sort(sorters[st.sort]);
    state.page = PAGE;
    renderList(list, (it) => trendCard(it, st.sort === "gained" ? list.indexOf(it) + 1 : 0), $("#list"));
    const bind = (attr, key) => el.querySelectorAll(`[data-${attr}]`).forEach((b) =>
      b.addEventListener("click", () => { st[key] = b.dataset[attr]; viewTrending(el); }));
    bind("range", "range"); bind("sort", "sort"); bind("cat", "cat");
  }

  function viewSearch(el) {
    const q = state.query;
    const res = state.data.items.filter((i) => matches(i, q));
    // 同一资源可能出现在多个专题，按 URL 去重
    const seen = new Set();
    const uniq = res.filter((i) => { const k = i.url.replace(/\/$/, "").toLowerCase(); return !seen.has(k) && seen.add(k); });
    uniq.sort((a, b) => {
      const an = a.name.toLowerCase().includes(q.toLowerCase()) ? 1 : 0;
      const bn = b.name.toLowerCase().includes(q.toLowerCase()) ? 1 : 0;
      return bn - an || (b.stars || 0) - (a.stars || 0);
    });
    const trend = (state.trending?.items || []).filter((i) => matches({ ...i, name: i.repo }, q) && !seen.has(i.url.toLowerCase()));
    el.innerHTML = `<div class="content-head"><div><h2>搜索「${esc(q)}」</h2><p>资源库 ${uniq.length} 条${trend.length ? `，AI 热门 ${trend.length} 条` : ""}</p></div></div>
      <div id="list"></div>${trend.length ? '<div class="section-title" style="margin-top:32px"><h2>AI 热门中的结果</h2></div><div id="tlist"></div>' : ""}`;
    state.page = PAGE;
    renderList(uniq, (it) => resourceCard(it, { showTopic: true }), $("#list"));
    if (trend.length) $("#tlist").innerHTML = `<div class="grid">${trend.slice(0, 30).map((it) => trendCard(it)).join("")}</div>`;
  }

  function viewNotFound(el) {
    el.innerHTML = '<div class="empty glass">页面不存在。<a href="#/" style="color:var(--blue-600)">返回首页</a></div>';
  }

  // ---------- 路由 ----------
  function route() {
    if (!state.data) return;
    const hash = decodeURIComponent(location.hash.replace(/^#/, "")) || "/";
    const el = $("#content");
    let active = "home";
    document.body.classList.toggle("searching", !!state.query);
    if (state.query) {
      active = "";
      viewSearch(el);
    } else if (hash.startsWith("/t/")) {
      active = hash.slice(3);
      viewTopic(el, active);
    } else if (hash === "/trending") {
      active = "trending";
      viewTrending(el);
    } else {
      viewHome(el);
    }
    renderSidebar(active);
    document.querySelectorAll("[data-nav]").forEach((a) => {
      const on = (a.dataset.nav === "trending") === (active === "trending") && !state.query;
      a.toggleAttribute("aria-current", on);
      if (on) a.setAttribute("aria-current", "page");
    });
    const t = state.data.topics.find((x) => x.slug === active);
    document.title = (state.query ? `搜索 ${state.query}` : t ? t.title : active === "trending" ? "GitHub AI 热门" : "AI 资源导航") + " · ChatGPT 中文指南";
  }

  function navigate() {
    state.query = "";
    $("#q").value = "";
    route();
    const top = $(".layout").getBoundingClientRect().top + scrollY - 90;
    if (location.hash && location.hash !== "#/" && scrollY > top) scrollTo({ top, behavior: "smooth" });
  }

  // ---------- 初始化 ----------
  function renderStats() {
    const d = state.data;
    const repos = new Set(d.items.filter((i) => i.repo).map((i) => i.repo)).size;
    const today = todayTrending().length;
    $("#stats").innerHTML = `
      <div><dt>收录资源</dt><dd>${d.items.length.toLocaleString()}</dd></div>
      <div><dt>专题</dt><dd>${d.topics.length}</dd></div>
      <div><dt>开源仓库</dt><dd>${repos.toLocaleString()}</dd></div>
      <div><dt>今日 AI 热门</dt><dd>${today}</dd></div>`;
    $("#built").textContent = ` · 数据构建于 ${d.built}`;
  }

  async function init() {
    // 全局渐变定义，供 sparkline 复用
    document.body.insertAdjacentHTML("beforeend",
      '<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs><linearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#3b6cf6" stop-opacity=".25"/><stop offset="1" stop-color="#3b6cf6" stop-opacity="0"/></linearGradient></defs></svg>');
    try {
      const [res, trend] = await Promise.all([
        fetch("data/resources.json").then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }),
        fetch("data/trending.json").then((r) => (r.ok ? r.json() : null)).catch(() => null),
      ]);
      state.data = res;
      state.trending = trend;
    } catch (e) {
      $("#content").innerHTML = `<div class="empty glass">数据加载失败（${esc(e.message)}）。请先运行 <code>python3 scripts/build_data.py</code>。</div>`;
      return;
    }
    renderStats();
    route();
  }

  let timer;
  $("#q").addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => { state.query = e.target.value.trim(); route(); }, 120);
  });
  $("#q").addEventListener("keydown", (e) => { if (e.key === "Escape") { e.target.value = ""; state.query = ""; route(); e.target.blur(); } });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !/input|textarea/i.test(document.activeElement.tagName)) { e.preventDefault(); $("#q").focus(); }
  });
  addEventListener("hashchange", navigate);
  const toTop = $("#toTop");
  addEventListener("scroll", () => { toTop.hidden = scrollY < 800; }, { passive: true });
  toTop.addEventListener("click", () => scrollTo({ top: 0, behavior: "smooth" }));

  init();
})();
