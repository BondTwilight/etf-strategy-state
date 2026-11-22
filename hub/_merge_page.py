# -*- coding: utf-8 -*-
"""_merge_page.py —— 把「完整看台」12 个区块合并进手机页，生成 app_template.html

为什么单独一个脚本而不是手改：
  1) live_template.html 有 2471 行，手工删 4 个跨越几十行的块容易误伤；
  2) 每一步都断言锚点存在，改不动就报错，不会静默产出半个页面；
  3) 原文件保留，出问题改一行 _build_live.py 就能退回。

产物：hub/app_template.html（单页、单滚动条、无 iframe）
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "live_template.html")
OUT = os.path.join(HERE, "app_template.html")

s = io.open(SRC, encoding="utf-8").read()
orig_len = len(s)


def cut(text, start_marker, end_marker, keep_end=True):
    """删掉 [start_marker, end_marker) 这一段。锚点必须唯一存在。"""
    assert text.count(start_marker) == 1, "起始锚点不唯一或缺失：%r" % start_marker[:40]
    a = text.index(start_marker)
    b = text.find(end_marker, a + len(start_marker))
    assert b > a, "结束锚点找不到：%r" % end_marker[:40]
    return text[:a] + (text[b:] if keep_end else text[b + len(end_marker):])


# ---------------------------------------------------------------- 1. CSS
NEW_CSS = r'''/* ---------- 顶部锚点导航：一条滚动条走到底，靠它跳 ---------- */
.hd .hubnav{margin-top:9px;display:flex;gap:8px;align-items:center}
.hd .hubnav .rbtn{flex:0 0 auto;font-size:11px;font-weight:650;padding:5px 10px;border-radius:7px;
  background:rgba(255,255,255,.11);border:1px solid rgba(255,255,255,.18);color:#dbeafe;
  cursor:pointer;white-space:nowrap}
.hd .hubnav .rbtn:disabled{opacity:.55}
.hd .hubnav .hint{font-size:9.5px;color:#64748b;margin-left:auto}
.navx{position:sticky;top:0;z-index:40;background:rgba(244,246,250,.97);
  -webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);
  border-bottom:1px solid #e8edf4;padding:7px 12px;display:flex;gap:6px;
  overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}
.navx::-webkit-scrollbar{display:none}
.navx a{flex:0 0 auto;font-size:10px;font-weight:650;color:#475569;background:#fff;
  border:1px solid #e4e9f0;border-radius:20px;padding:4px 10px;text-decoration:none;white-space:nowrap}
html{scroll-behavior:smooth}
.wrap>[id]{scroll-margin-top:46px}

/* ---------- 决策链：四步单向因果 ---------- */
.chn{background:#fff;border:1px solid #e4e9f0;border-radius:14px;padding:13px;margin-bottom:10px}
.chn-h{font-size:12px;font-weight:750;color:#0f172a;display:flex;align-items:center;gap:6px}
.chn-h .rt{margin-left:auto;font-size:9px;color:#94a3b8;font-weight:600}
.chn .tag{font-size:8.5px;padding:1px 5px;border-radius:4px;background:#eff6ff;color:#1d4ed8;font-weight:700}
.chn-s{font-size:9px;color:#94a3b8;margin-top:4px;line-height:1.7}
.chn-l{margin-top:11px;position:relative;padding-left:23px}
.chn-l::before{content:'';position:absolute;left:7px;top:5px;bottom:16px;width:2px;background:#eef2f7}
.chn-i{position:relative;padding-bottom:13px}
.chn-i:last-child{padding-bottom:0}
.chn-i::before{content:attr(data-n);position:absolute;left:-23px;top:0;width:16px;height:16px;
  border-radius:50%;background:#fff;border:2px solid #cbd5e1;color:#94a3b8;font-size:8px;
  font-weight:800;display:flex;align-items:center;justify-content:center;line-height:1}
.chn-i.bear::before{border-color:#059669;color:#059669}
.chn-i.B::before{border-color:#2563eb;color:#2563eb}
.chn-i.fit::before{border-color:#7c3aed;color:#7c3aed}
.chn-i.act::before{border-color:#b91c1c;color:#b91c1c}
.chn-k{font-size:8.5px;color:#94a3b8;letter-spacing:.7px;font-weight:750}
.chn-v{font-size:13px;font-weight:750;color:#0f172a;margin-top:2px;line-height:1.4}
.chn-u{font-size:9px;color:#94a3b8;margin-top:2px;line-height:1.6}
.chn-w{font-size:9px;color:#64748b;margin-top:3px;line-height:1.8;word-break:break-word}
.chn-note{font-size:9px;color:#64748b;background:#f8fafc;border-radius:8px;padding:8px 10px;
  margin-top:10px;line-height:1.9}

/* ---------- 环境矩阵 ---------- */
.mx{background:#fff;border:1px solid #e4e9f0;border-radius:14px;padding:13px;margin-bottom:10px}
.mx-h{font-size:12px;font-weight:750;color:#0f172a;display:flex;align-items:center;gap:6px}
.mx-h .rt{margin-left:auto;font-size:9px;color:#94a3b8;font-weight:600}
.mx-h .tag{font-size:8.5px;padding:1px 5px;border-radius:4px;background:#f5f3ff;color:#6d28d9;font-weight:700}
.mx table{width:100%;border-collapse:collapse;margin-top:9px;table-layout:fixed}
.mx th{font-size:8.5px;font-weight:750;color:#94a3b8;padding:3px 0 4px;text-align:center;
  border-bottom:1px solid #eef2f7;line-height:1.2}
.mx th:first-child{text-align:left;width:74px}
.mx th.on{color:#1d4ed8;background:#eff6ff;border-radius:5px 5px 0 0}
.mx th i{display:block;font-size:7.5px;color:#cbd5e1;font-style:normal;font-weight:600;margin-top:1px}
.mx td{padding:2px 0;text-align:center;border-bottom:1px solid #f6f8fb;font-size:9.5px;
  font-variant-numeric:tabular-nums}
.mx td:first-child{text-align:left;font-size:9.5px;font-weight:650;color:#334155;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding-right:3px}
.mx td b{display:block;font-size:9.5px;line-height:1.35;font-weight:750}
.mx td i{display:block;font-size:7px;line-height:1.3;font-style:normal;color:#94a3b8;font-weight:600}
.mx-lg{display:flex;flex-wrap:wrap;gap:4px 9px;margin-top:9px;font-size:8px;color:#94a3b8;line-height:1.6}
.mx-lg .on{color:#1d4ed8;font-weight:700}
.mx-note{font-size:8.5px;color:#94a3b8;margin-top:7px;line-height:1.8}

/* ---------- 折叠区（健康 / 评分标准 / 口径） ---------- */
.acc{background:#fff;border:1px solid #e4e9f0;border-radius:14px;margin-bottom:10px;overflow:hidden}
.acc>summary{list-style:none;cursor:pointer;padding:12px 13px;font-size:11.5px;font-weight:750;
  color:#334155;display:flex;align-items:center;gap:7px}
.acc>summary::-webkit-details-marker{display:none}
.acc>summary::after{content:'展开';margin-left:auto;font-size:9px;color:#94a3b8;font-weight:600}
.acc[open]>summary::after{content:'收起'}
.acc>summary .tag{font-size:8.5px;padding:1px 5px;border-radius:4px;background:#f1f5f9;
  color:#475569;font-weight:700}
.acc>summary .tag.bad{background:#fef2f2;color:#b91c1c}
.acc>summary .tag.ok{background:#ecfdf5;color:#047857}
.acc .bd{padding:2px 13px 12px;border-top:1px dashed #eef2f7}
.hl{display:flex;gap:7px;padding:6px 0;border-bottom:1px solid #f6f8fb;font-size:9px;line-height:1.8}
.hl:last-child{border-bottom:0}
.hl .d{flex:0 0 6px;height:6px;border-radius:50%;margin-top:6px;background:#34d399}
.hl.warn .d{background:#f59e0b}
.hl.bad .d{background:#ef4444}
.hl .k{flex:0 0 84px;color:#475569;font-weight:750}
.hl .v{flex:1 1 auto;min-width:0;color:#64748b;word-break:break-word}
.rl{padding:9px 0;border-bottom:1px solid #f6f8fb}
.rl:last-child{border-bottom:0}
.rl .t{font-size:10.5px;font-weight:750;color:#334155;display:flex;gap:6px;align-items:baseline}
.rl .w{font-size:8px;color:#1d4ed8;background:#eff6ff;padding:1px 4px;border-radius:4px;font-weight:750}
.rl .h{font-size:9px;color:#64748b;margin-top:3px;line-height:1.85}
.rl .c{font-size:8px;color:#94a3b8;margin-top:2px;font-family:ui-monospace,Menlo,monospace;
  line-height:1.75;word-break:break-word}
.cb{padding:7px 0;border-bottom:1px solid #f6f8fb;font-size:9px}
.cb:last-child{border-bottom:0}
.cb .k{font-weight:700;color:#475569}
.cb .c{color:#94a3b8;font-family:ui-monospace,Menlo,monospace;font-size:8px;margin-top:2px;
  line-height:1.7;word-break:break-word}
.fb{font-size:8.5px;color:#b91c1c;background:#fef2f2;border-radius:8px;padding:9px 11px;
  line-height:1.9;margin-top:9px}
.fb b{display:block;margin-bottom:3px;font-size:9px}
.fb ul{margin:0;padding-left:14px}
.fb li{margin:3px 0}
code{font-family:ui-monospace,Menlo,monospace;font-size:9px;background:#f1f5f9;
  padding:1px 3px;border-radius:3px;color:#475569}

/* 宽屏（桌面打开同一个文件）：两个两列布局，不用再另开一个页面 */
@media(min-width:820px){
  .wrap{max-width:900px}
  .chn,.mx{max-width:none}
}
'''

s = s[:s.index("/* 完整看台：同页内嵌")] + NEW_CSS + s[
    s.index(".hd .hubnav a:hover{background:rgba(255,255,255,.18)}")
    + len(".hd .hubnav a:hover{background:rgba(255,255,255,.18)}") + 1:]

# ---------------------------------------------------------------- 2. 删浮层 HTML
s = cut(s, "<!-- 完整看台浮层", "<!-- 恒方产品详情")

# ---------------------------------------------------------------- 3. 头部导航
assert s.count('<div class="hubnav">') == 1
a = s.index('<div class="hubnav">')
b = s.index("</div>", a) + len("</div>")
s = s[:a] + (
    '<div class="hubnav">\n'
    '    <button class="rbtn" id="reload" type="button">↻ 刷新</button>\n'
    '    <span class="hint" id="statetag">全部内容都在这一页 ↓</span></div>'
) + s[b:]

# ---------------------------------------------------------------- 4. 加锚点导航 + 新区块
NAV = '''<div class="navx" id="navx">
  <a href="#hero">今日</a><a href="#cards">持仓</a><a href="#weather">环境</a>
  <a href="#flow">决策链</a><a href="#matrix">矩阵</a><a href="#predict">预测</a>
  <a href="#books">账本</a><a href="#intel">恒方</a><a href="#health">数据</a>
</div>

'''
assert s.count('<div class="wrap">') == 1
s = s.replace('<div class="wrap">', NAV + '<div class="wrap">')

assert s.count('  <div class="grp">预测 · 账本 · 情报</div>') == 1
s = s.replace('  <div class="grp">预测 · 账本 · 情报</div>',
              '  <div class="grp">决策链 · 为什么是这条</div>\n'
              '  <div id="flow"></div>\n'
              '  <div id="matrix"></div>\n'
              '  <div class="grp">预测 · 账本 · 情报</div>')

assert s.count('  <div id="cloud"></div>') == 1
s = s.replace('  <div id="cloud"></div>',
              '  <div class="grp">数据 · 口径 · 评分标准</div>\n'
              '  <div id="health"></div>\n'
              '  <div id="rules"></div>\n'
              '  <div id="caliber"></div>\n'
              '  <div id="cloud"></div>')

# ---------------------------------------------------------------- 5. 换掉浮层 JS，插入新渲染
NAVJS = r'''/* 顶部锚点跳转 + 滚动高亮。
   2026-11-22 之前点「完整看台」没反应，根因是它依赖一次顶层跳转 ——
   带 ?sharecode 的跳转一旦丢参就被网关挡成 403。现在没有第二个页面了，
   跳转只发生在文档内部，不会再丢任何东西。 */
(function () {
  const nav = document.getElementById('navx');
  if (!nav) return;
  const links = Array.prototype.slice.call(nav.querySelectorAll('a'));
  function mark(on) {
    /* 用 class 控制当前项，不再写行内色 —— 行内色会把 CSS 里的下划线样式压掉 */
    links.forEach(function (a) { a.classList.toggle('on', a === on); });
  }
  links.forEach(function (a) {
    a.addEventListener('click', function (ev) {
      const t = document.querySelector(a.getAttribute('href'));
      if (!t) return;
      ev.preventDefault();
      t.scrollIntoView({ behavior: 'smooth', block: 'start' });
      mark(a);
      try { history.replaceState(null, '', a.getAttribute('href')); } catch (e) { }
    });
  });
  if (links.length) mark(links[0]);      /* 首屏默认高亮第一项 */
  if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (!e.isIntersecting) return;
        links.forEach(function (a) {
          if (a.getAttribute('href') === '#' + e.target.id) mark(a);
        });
      });
    }, { rootMargin: '-46px 0px -72% 0px', threshold: 0 });
    links.forEach(function (a) {
      const n = document.getElementById(a.getAttribute('href').slice(1));
      if (n) io.observe(n);
    });
  }
})();

/* ============================================================================
   决策链 —— 市场状态 → 环境分档 → 策略适配 → 今日动作
   ----------------------------------------------------------------------------
   以前这四块分散在四个页面区块，要用户自己串；现在第一步到第三步都用
   「此刻的价」重算（SC.regime / SC.adapt），不是抄构建时的死数。
   ============================================================================ */
function renderFlow() {
  const el = document.getElementById('flow');
  if (!el) return;
  const ch = D.chain;
  const steps = (ch && ch.steps) ? ch.steps.slice() : [];
  if (!steps.length) { el.innerHTML = ''; return; }

  let liveTag = '';
  try {
    if (D.score && typeof SC !== 'undefined') {
      const rg = SC.regime(D.score);
      const ms = SC.marketState(D.score);
      const m0 = ms && ms['510300'];
      if (m0 && steps[0]) {
        const sc0 = m0.score || {};
        steps[0].v = sc0.state + ' ' + (sc0.total > 0 ? '+' : '') + Number(sc0.total).toFixed(1);
        steps[0].sub = '四维检测器 · 置信 ' + Number(sc0.conf).toFixed(1) + '%';
        steps[0].why = (sc0.dims || []).map(function (d) {
          return d.k + ' ' + (d.v > 0 ? '+' : '') + Number(d.v).toFixed(1);
        }).join(' ｜ ');
      }
      if (rg && rg.ok) {
        const hits = (rg.items || []).filter(function (x) { return x.hit; }).length;
        const dn = ((D.matrix || {}).regimes || []).filter(function (x) { return x.k === rg.code; })[0];
        steps[1].v = rg.code + ' ' + (rg.label || '');
        steps[1].sub = '4 条判据里 ' + hits + ' 条触发' + (dn ? ' · 该档共 ' + dn.n + ' 天' : '');
        steps[1].why = (rg.items || []).map(function (x) {
          const signed = /距|差|变化/.test(x.k);
          return x.k + ' ' + (signed && x.v > 0 ? '+' : '') + x.v + x.unit;
        }).join(' ｜ ');
        const ad = SC.adapt(D.matrix, rg.code);
        if (ad && ad.length && steps[2]) {
          const s0 = (D.slimStrategies || []).filter(function (x) { return x.id === ad[0].id; })[0] || {};
          steps[2].v = (s0.short || s0.name || ad[0].id) + ' 最适配 '
            + (ad[0].bp > 0 ? '+' : '') + ad[0].bp + 'bp';
          steps[2].sub = '按「' + rg.code + '」档内日均收益横向排序';
          steps[2].why = ad.map(function (x) {
            const s1 = (D.slimStrategies || []).filter(function (y) { return y.id === x.id; })[0] || {};
            return (s1.short || s1.name || x.id) + ' ' + (x.bp > 0 ? '+' : '') + x.bp + 'bp';
          }).join(' ｜ ');
        }
        liveTag = '实时';
      }
    }
  } catch (e) { /* 缺序列就用构建时的快照 */ }

  /* 第 4 步：逐策略数动作。
     🔴 真实指令（D.action）优先于回测的 today ——
     2026-11-22 就是这样：线C 的回测口径写「持有第 10 天，未触发卖出」，
     但收盘 0.3620 已跌破 0.3650 止损线，真实指令是「周一开盘卖出」。
     两处不一致时，必须让用户看到那条要下单的。 */
  const ord = {};
  ((D.action || {}).items || []).forEach(function (x) {
    if (x && x.code) ord[x.code] = x.side;
  });
  const rows = (D.strats || []).map(function (s) {
    const t = s.today || {};
    let a = t.action || 'none';
    const c = t.code || '';
    if (c && ord[c]) a = ord[c];
    return { n: s.short || s.name || s.id, a: a, c: c };
  });
  /* 指令里有、但不在任何策略持仓里的（例如临时风控单）也要计入 */
  const known = {};
  rows.forEach(function (r) { if (r.c) known[r.c] = 1; });
  ((D.action || {}).items || []).forEach(function (x) {
    if (x && x.code && !known[x.code]) {
      rows.push({ n: x.sid || '风控单', a: x.side || 'sell', c: x.code });
    }
  });
  if (rows.length && steps[3]) {
    const sell = rows.filter(function (r) { return r.a === 'sell'; }).length;
    const buy = rows.filter(function (r) { return r.a === 'buy'; }).length;
    steps[3].v = (sell ? sell + ' 卖' : '') + (sell && buy ? ' · ' : '')
      + (buy ? buy + ' 买' : '') || '今天不动';
    steps[3].sub = (D.strats || []).length + ' 条策略里 ' + (sell + buy) + ' 条要动手'
      + (sell + buy ? '（真实指令优先于回测口径）' : '');
    steps[3].why = rows.map(function (r) {
      const w = r.a === 'sell' ? '卖' : (r.a === 'buy' ? '买' : (r.a === 'hold' ? '持' : '空'));
      return r.n + ' ' + w + (r.c ? ' ' + r.c : '');
    }).join(' ｜ ');
  }

  let h = '<div class="chn"><div class="chn-h">决策链<span class="tag">单向因果</span>'
    + '<span class="rt">' + esc(liveTag || ('数据日 ' + (D.data_date || '—'))) + '</span></div>'
    + '<div class="chn-s">每一步都由上一步决定。换数据而下游没变，就是那里写死了。</div>'
    + '<div class="chn-l">';
  steps.forEach(function (st) {
    h += '<div class="chn-i ' + esc(st.color || '') + '" data-n="' + (st.n || '') + '">'
      + '<div class="chn-k">' + esc(st.k) + '</div>'
      + '<div class="chn-v">' + esc(st.v) + '</div>'
      + (st.sub ? '<div class="chn-u">' + esc(st.sub) + '</div>' : '')
      + (st.why ? '<div class="chn-w">' + esc(st.why) + '</div>' : '')
      + '</div>';
  });
  h += '</div>';
  if (ch && ch.note) h += '<div class="chn-note">' + rawHTML(ch.note) + '</div>';
  el.innerHTML = h + '</div>';
  el.firstChild.className = 'chn';
}

/* 环境矩阵：5 档 × 5 条策略，看「哪个天气里该信谁」。
   底色按 |日均 bp| 上色（红=赚、绿=亏），格内第二行是胜率。 */
function renderMatrix() {
  const el = document.getElementById('matrix');
  if (!el) return;
  const m = D.matrix;
  if (!m || !m.regimes || !m.rows) { el.innerHTML = ''; return; }
  let cur = '';
  try { if (D.score && typeof SC !== 'undefined') cur = SC.regime(D.score).code || ''; } catch (e) { }
  const SH = { A: 'A', C: 'C', Bp: 'B′', B: 'B', D: 'D' };
  /* 同一套策略在不同区块的名字要一致：矩阵原来写「线B」，卡片写「momo」，
     用户会以为是两条策略。这里统一成「线B·momo」这种能对上的写法。 */
  const SN = { lineC: '线C', band96863: '消费轮动', bank96864: '等股灾',
               momo96865: '线B·momo' };

  let h = '<div class="mx"><div class="mx-h">环境矩阵<span class="tag">哪档信谁</span>'
    + '<span class="rt">日均 bp · 5 档</span></div>'
    + '<table><thead><tr><th>策略</th>';
  m.regimes.forEach(function (r) {
    h += '<th class="' + (r.k === cur ? 'on' : '') + '">' + (SH[r.k] || r.k)
      + '<i>' + r.n + '</i></th>';
  });
  h += '</tr></thead><tbody>';
  m.rows.forEach(function (row) {
    h += '<tr><td>' + esc(SN[row.id] || String(row.name || row.id).replace(/\s*9686\d\s*/, '')) + '</td>';
    (row.cells || []).forEach(function (c) {
      if (!c || c.mean_bp == null) { h += '<td>—</td>'; return; }
      const bp = c.mean_bp;
      const flat = c.flat == null ? 0 : c.flat;
      const a = Math.min(1, Math.abs(bp) / 30);
      let bg, fg;
      if (Math.abs(bp) < 1) { bg = 'rgba(148,163,184,.10)'; fg = '#94a3b8'; }
      else if (bp > 0) { bg = 'rgba(220,38,38,' + (0.04 + a * 0.20).toFixed(2) + ')'; fg = '#b91c1c'; }
      else { bg = 'rgba(5,150,105,' + (0.04 + a * 0.20).toFixed(2) + ')'; fg = '#047857'; }
      h += '<td style="background:' + bg + '"><b style="color:' + fg + '">'
        + (bp > 0 ? '+' : '') + Math.round(bp) + '</b><i>'
        /* 一半以上时间空仓的格子，胜率没有意义 —— 直接写「空仓」，
           否则线C 在 A 档会显示 0% 胜率，被读成「从来没赚过」。 */
        + (flat > 0.5 ? '空仓' : (c.win == null ? '—' : Math.round(c.win * 100) + '%')) + '</i></td>';
    });
    h += '</tr>';
  });
  h += '</tbody></table><div class="mx-lg">';
  m.regimes.forEach(function (r) {
    h += '<span class="' + (r.k === cur ? 'on' : '') + '">' + (SH[r.k] || r.k) + ' '
      + esc(r.label) + ' · ' + r.n + '天</span>';
  });
  h += '</div><div class="mx-note">大号＝该档内<b>日均收益</b>（bp，1bp＝0.01%），小号＝胜率。'
    + '底色越深越强。当前档 <b>' + esc(cur || '—') + '</b> 已高亮 —— '
    + '分高不等于能买，还要过准入闸门。</div></div>';
  el.innerHTML = h;
}

/* 数据健康 / 九维评分标准 / 口径与禁令：三块默认折叠，出问题才自动展开 */
function renderHealth() {
  const el = document.getElementById('health');
  if (!el) return;
  const L = D.health || [];
  if (!L.length) { el.innerHTML = ''; return; }
  const bad = L.filter(function (x) { return x.s !== 'ok'; });
  let h = '<details class="acc"' + (bad.length ? ' open' : '') + '>'
    + '<summary>数据健康<span class="tag ' + (bad.length ? 'bad' : 'ok') + '">'
    + (bad.length ? bad.length + ' 条需注意' : L.length + '/' + L.length + ' 通过')
    + '</span></summary><div class="bd">';
  L.forEach(function (x) {
    h += '<div class="hl ' + esc(x.s || '') + '"><span class="d"></span>'
      + '<span class="k">' + esc(x.k) + '</span><span class="v">'
      + rawHTML(x.v) + '</span></div>';
  });
  el.innerHTML = h + '</div></details>';
}

function renderRules() {
  const el = document.getElementById('rules');
  const R = D.rules || [];
  if (!el || !R.length) return;
  let h = '<details class="acc"><summary>九维评分标准'
    + '<span class="tag">100 分怎么来的</span></summary><div class="bd">';
  R.forEach(function (x) {
    h += '<div class="rl"><div class="t"><span>' + esc(x.k) + '</span>'
      + '<span class="w">' + x.w + ' / 100</span></div>'
      + '<div class="h">' + esc(x.how) + '</div>'
      + '<div class="c">' + esc(x.calc) + '</div>'
      + '<div class="h" style="color:#94a3b8">' + esc(x.live) + '</div></div>';
  });
  el.innerHTML = h + '</div></details>';
}

function renderCaliber() {
  const el = document.getElementById('caliber');
  const c = D.caliber || {};
  if (!el || !(c.rows || []).length) return;
  let h = '<details class="acc"><summary>口径与四条禁令'
    + '<span class="tag">研究基准</span></summary><div class="bd">';
  (c.rows || []).forEach(function (x) {
    h += '<div class="cb"><div class="k">' + esc(x.k) + ' · ' + esc(x.v) + '</div>'
      + '<div class="c">' + esc(x.c) + '</div></div>';
  });
  if ((c.forbid || []).length) {
    h += '<div class="fb"><b>四条禁令（都是踩过的坑）</b><ul>';
    c.forbid.forEach(function (t) { h += '<li>' + rawHTML(t) + '</li>'; });
    h += '</ul></div>';
  }
  el.innerHTML = h + '</div></details>';
}

/* ============================================================================
   云端 state：电脑关着也能天天更新
   ----------------------------------------------------------------------------
   链路 = GitHub Actions 每天 15:10 跑完 → 提交 data/state.json →
         页面 fetch（raw.githubusercontent 带 ACAO:*）→ 覆盖内嵌快照 → 整页重画。
   没配 LIVE_STATE_URL 时直接返回，不发任何请求（不会刷 404）。
   失败不清空：内嵌快照照常显示，只在右上角写「云端未连上」。
   ============================================================================ */
const STATE = { on: false, at: '', err: '' };

function statetag(t) {
  const el = document.getElementById('statetag');
  if (el) el.textContent = t;
}

async function loadState() {
  const url = D.stateUrl;
  if (!url) { statetag('未接云端 · 用内嵌快照'); return; }
  try {
    const r = await fetch(url + (url.indexOf('?') < 0 ? '?' : '&') + 't=' + Date.now(),
                          { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const s = await r.json();
    if (!s || !s.built_at) throw new Error('state 为空');
    if (D.built_at && s.built_at <= D.built_at) {
      statetag('内嵌较新 · ' + String(D.built_at).slice(5));
      return;
    }
    Object.assign(D, s);
    renderAll();
    /* 如果详情弹层正开着，用新数据重画它 —— 否则用户看到的还是旧账本 */
    try { if (typeof STC !== 'undefined' && STC && STC.id) openStrat(STC.id); } catch (e) { }
    try { refreshWeatherLive(); } catch (e) { }
    setTimeout(function () { try { runPredict(); } catch (e) { } }, 400);
    STATE.on = true; STATE.at = s.built_at;
    const cw = (s.caliberWarn && s.caliberWarn.length) ? ' · 口径：收盘价' : '';
    statetag('云端 ' + String(s.built_at).slice(5) + ' 已同步 · 数据日 '
             + (s.data_date || '—') + cw);
  } catch (e) {
    STATE.err = String((e && e.message) || e);
    statetag('云端未连上（' + STATE.err.slice(0, 16) + '）· 用内嵌');
  }
}

'''
s = cut(s, "/* 完整看台入口：本地指向含份额金额的完整版",
        "/* ============================================================================\n   调仓预测", keep_end=True)
# cut() 已把 NAVJS 之前那段删掉，现在把 NAVJS 插回「调仓预测」注释之前
i = s.index("/* ============================================================================\n   调仓预测")
s = s[:i] + NAVJS + s[i:]

# ---------------------------------------------------------------- 6. 接线
assert s.count('renderHero(); renderWeather(); renderBooks(); pills(); renderChain(); paint(); renderCloud(); renderPredict(); renderInd(); renderIntel();') == 1
s = s.replace(
    'renderHero(); renderWeather(); renderBooks(); pills(); renderChain(); paint(); renderCloud(); renderPredict(); renderInd(); renderIntel();',
    '''/* 一处定义「整页重画」：云端 state 拉回来后整页替换，避免漏掉某一块 */
/* AI 解读：只解释「发生了什么」，不是指令。
   state.json 里有 ai_note 才显示（由 tools/ai_note.py 在构建期写好），
   没有就整块不出现 —— 不会留一个空壳。 */
function renderAINote() {
  const el = document.getElementById('nnote');
  if (!el) return;
  const a = D.ai_note;
  if (!a || !a.text) { el.innerHTML = ''; return; }
  const lines = String(a.text).split(/\\n+/)
    .map(function (t) { return t.replace(/^[\s\-•*·]+/, '').replace(/^\d+[.、)]\s*/, '').trim(); })
    .filter(Boolean).slice(0, 6);
  el.innerHTML = '<div class="ain"><div class="ain-h">AI 解读'
    + '<span class="tag">只解释，不下单</span>'
    + '<span class="rt">' + esc(a.model || 'model') + ' · ' + esc(a.at || '') + '</span></div>'
    + '<ul>' + lines.map(function (t) { return '<li>' + esc(t) + '</li>'; }).join('') + '</ul>'
    + '<div class="ain-n">模型只读本页数字，不预测涨跌、不给买卖建议；'
    + '要动手看首屏那张卡。</div></div>';
}

function renderAll(){
  renderHero(); renderAINote(); renderWeather(); renderFlow(); renderMatrix(); renderBooks(); pills();
  renderChain(); paint(); renderCloud(); renderPredict(); renderInd(); renderIntel();
  renderHealth(); renderRules(); renderCaliber();
}
renderAll();''')

assert s.count('  D.wxLive = r.applied ? r.why : (tailInfo || r.why);\n  renderWeather();\n}') == 1
s = s.replace('  D.wxLive = r.applied ? r.why : (tailInfo || r.why);\n  renderWeather();\n}',
              '  D.wxLive = r.applied ? r.why : (tailInfo || r.why);\n'
              '  renderWeather();\n'
              '  /* 决策链与矩阵跟着实时价重算 —— 否则上面写「实时」下面是死数 */\n'
              '  try { renderFlow(); renderMatrix(); } catch (e) { }\n}')

assert s.count('    if (tailInfo) D.wxLive = tailInfo;\n    renderWeather();') == 1
s = s.replace('    if (tailInfo) D.wxLive = tailInfo;\n    renderWeather();',
              '    if (tailInfo) D.wxLive = tailInfo;\n    renderWeather();\n'
              '    try { renderFlow(); renderMatrix(); } catch (e) { }')

# rawHTML：这些文案来自我们自己的构建产物，只挡脚本注入
helper = '''
/* 这些长文案来自本地构建（含 <code>/<b>），需要保留标签；只挡脚本注入。 */
function rawHTML(t) {
  return String(t == null ? '' : t).replace(/<script/gi, '&lt;script')
    .replace(/on\\w+\\s*=/gi, 'data-x=');
}
'''
i = s.index("function renderFlow()")
s = s[:i] + helper.strip() + '\n\n' + s[i:]

# ---------------------------------------------------------------- 7. 自检
must = ['id="navx"', 'id="flow"', 'id="matrix"', 'id="health"', 'id="rules"',
        'id="caliber"', 'function renderFlow', 'function renderMatrix',
        'function renderHealth', 'function renderRules', 'function renderCaliber']
for k in must:
    assert k in s, "产物缺少：" + k
for bad in ['id="hubview"', 'id="hvframe"', 'openHub(', 'id="hubnav"']:
    assert bad not in s, "残留旧代码：" + bad

io.open(OUT, "w", encoding="utf-8").write(s)
print("OK %s -> %s  %d -> %d chars (%+.1f%%)"
      % (os.path.basename(SRC), os.path.basename(OUT), orig_len, len(s),
         (len(s) - orig_len) * 100.0 / orig_len))
