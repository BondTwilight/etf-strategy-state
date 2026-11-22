/* ============================================================================
   live_core.js —— 策略中枢实时内核（主看台 hub/index.html 与手机页 live/index.html 共用）
   ----------------------------------------------------------------------------
   为什么要有这个文件
   ------------------
   在 v6 之前，两个页面各写各的：
     主看台：只有起 serve.py 才有实时价，file:// 打开直接显示「无实时行情」；
             而且只显示价格，不判断「按规则现在该不该动手」。
     手机页：直连东财有实时价，但也只画价格，不知道线C 的四道闸门、96864 的双 5%。
   ⇒ 同一个持仓，两个屏幕可能给出不同的隐含结论。11-20 那笔止损漏执行就是这个形态：
     看板写「距止损 +4.11%」，手机页写「现价 0.362」，没人把两件事算在一起。

   所以本文件是「判定只写一处」的实现：任何页面的判定都调 LC.judge()，
   改规则只改这一个文件，两边同时生效。构建时内联，不产生额外请求。
   ============================================================================ */
const LC = (function () {
  'use strict';

  /* ---------- 1. 标的 → 东财 secid（5/6 开头沪市，其余深市） ---------- */
  function SECID(c) { return (/^[56]/.test(c) ? '1.' : '0.') + c; }

  function hhmmss() {
    const d = new Date(), p = n => String(n).padStart(2, '0');
    return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }

  /* ---------- 2. 行情：双源冗余 ----------
     为什么不是单源：2026-11-22 实测东方财富 push2 在被高频请求后会直接掐连接
     （ERR_EMPTY_RESPONSE，四个域名同时失效），不是 429 限流，重试也没用。
     而腾讯 qt.gtimg.cn 同样返回 Access-Control-Allow-Origin: *
     ⇒ 两个都是浏览器可直连的源，做冗余才敢说「随时能打开」。
       ① 东财 push2：批量、字段全（含最高最低），优先
       ② 腾讯 qt   ：兜底，字段少但够判止损
     */

  /* 东财：f1=小数位 f2=价 f3=涨跌幅×100 f12=代码 f14=名称 f15=最高 f16=最低 f18=昨收 */
  async function fetchEM(codes) {
    const arr = [...new Set((codes || []).filter(Boolean))];
    if (!arr.length) return {};
    const url = 'https://push2.eastmoney.com/api/qt/ulist.np/get?secids='
      + arr.map(SECID).join(',')
      + '&fields=f1,f2,f3,f12,f13,f14,f15,f16,f18&_=' + Date.now();
    const r = await fetch(url, { cache: 'no-store' });
    const j = await r.json();
    const out = {};
    ((j.data && j.data.diff) || []).forEach(function (d) {
      const dec = Math.pow(10, d.f1 == null ? 2 : d.f1);
      out[String(d.f12)] = {
        price: d.f2 == null ? null : d.f2 / dec,
        chg: d.f3 == null ? null : d.f3 / 100,
        high: d.f15 == null ? null : d.f15 / dec,
        low: d.f16 == null ? null : d.f16 / dec,
        pre: d.f18 == null ? null : d.f18 / dec,
        name: d.f14,
        src: 'em'
      };
    });
    return out;
  }

  /* 腾讯：~ 分隔，[1]=名称 [2]=代码 [3]=现价 [4]=昨收 [31]=涨跌额 [32]=涨跌幅% [33]=最高 [34]=最低 */
  function TXID(c) { return (/^[56]/.test(c) ? 'sh' : 'sz') + c; }
  async function fetchTX(codes) {
    const arr = [...new Set((codes || []).filter(Boolean))];
    if (!arr.length) return {};
    const url = 'https://qt.gtimg.cn/q=' + arr.map(TXID).join(',') + '&_=' + Date.now();
    const r = await fetch(url, { cache: 'no-store' });
    const buf = await r.arrayBuffer();
    /* 返回是 GBK，浏览器不会自动按 GBK 解，必须手动 decode */
    const txt = new TextDecoder('gbk').decode(buf);
    const out = {};
    txt.split(';').forEach(function (line) {
      line = line.trim();
      if (line.indexOf('="') < 0) return;
      const f = line.split('="')[1].replace(/"$/, '').split('~');
      if (f.length < 35) return;
      const code = f[2];
      const price = parseFloat(f[3]);
      if (!isFinite(price)) return;
      out[code] = {
        price: price,
        chg: parseFloat(f[32]),
        high: parseFloat(f[33]),
        low: parseFloat(f[34]),
        pre: parseFloat(f[4]),
        name: f[1],
        src: 'tx'
      };
    });
    return out;
  }

  function withTimeout(p, ms) {
    return Promise.race([
      p,
      new Promise(function (_, rej) { setTimeout(function () { rej(new Error('timeout')); }, ms); })
    ]);
  }

  /* 双源取价：返回 {data:{code:{...}}, src:'em'|'tx'|''}
     源挂了记 5 分钟，避免每轮都撞同一个墙（浏览器控制台也不会刷满红字） */
  let emDownUntil = 0;
  async function fetchQuote(codes) {
    /* 2026-11-22 换序：腾讯优先、东财兜底。
       原因：东财 push2 在被高频请求后会直接掐连接（ERR_EMPTY_RESPONSE，
       四个域名同时失效），每次刷新都在 console 里留一条红字；
       而腾讯 qt 同样带 ACAO:*，字段够用（价/昨收/涨跌幅/最高/最低），
       实测 381 只 1.4 秒。东财退到兜底位，只在腾讯失败时才请它。 */
    try {
      const d = await withTimeout(fetchTX(codes), 6000);
      if (d && Object.keys(d).length) return { data: d, src: 'tx' };
    } catch (e) { /* 落到东财 */ }
    if (Date.now() > emDownUntil) {
      try {
        const d = await withTimeout(fetchEM(codes), 6000);
        if (d && Object.keys(d).length) return { data: d, src: 'em' };
        emDownUntil = Date.now() + 300000;
      } catch (e) {
        emDownUntil = Date.now() + 300000;
      }
    }
    return { data: {}, src: '' };
  }

  /* ---------- 3. 各策略的风控口径（与后端 config 对应，改这里要同步改 config） ----------
     注意：real_positions 里的 stop 已经是后端算好的「较紧那条」，
     本表只用于补 target 与文案，不用来重算 stop。 */
  const RULES = {
    lineC:     { stopPct: -15, targetPct: 3,  note: '四道闸门：−15% 深套 / 回本且 20 日乖离≥0 / +3% 目标 / 满 30 日' },
    bank96864: { stopPct: -5,  targetPct: null, note: '双 5% 止损：跌幅 5% / 高点回撤 5%（页面显示较紧那条）' },
    band96863: { stopPct: null, targetPct: null, note: '无止损，靠 19 日区间涨幅 2~10% 带内换仓' },
    momo96865: { stopPct: null, targetPct: null, note: '无止损，靠 20/26 加权斜率双滤换仓' },
    momo94744: { stopPct: null, targetPct: null, note: 'momo + 溢价率 >30% 即卖（躲停牌）' },
    hengfang:  { stopPct: null, targetPct: null, note: '只发信号不下单，无仓位管理' }
  };

  /* ---------- 4. 统一判定：给一个价，返回「该不该动手」 ----------
     it 需要：{code, cost, stop, snap_dist, snap_pnl, sid, target}
     返回：{price, pnl, dist, gate, txt, flip, hot}
       gate  stop 已破止损 / watch 逼近(<2%) / near 距 5% 内 / ok 安全 / na 无止损
       flip  broke 快照没破、实时破了（最危险，必须立刻处理）
             recovered 快照破、实时收回（可以不补做） */
  function judge(it, price) {
    const o = { code: it.code, price: price, pnl: null, dist: null, gate: 'na', txt: '无止损', flip: null, hot: false };
    if (price == null || !isFinite(price)) return o;

    if (it.cost) o.pnl = (price / it.cost - 1) * 100;

    if (it.stop) {
      o.dist = (price / it.stop - 1) * 100;
      if (o.dist < 0)            { o.gate = 'stop';  o.txt = '已破止损'; }
      else if (o.dist < 2)       { o.gate = 'watch'; o.txt = '逼近止损'; }
      else if (o.dist < 5)       { o.gate = 'near';  o.txt = '距 5% 内'; }
      else                       { o.gate = 'ok';    o.txt = '安全'; }

      if (it.snap_dist != null && isFinite(it.snap_dist)) {
        if (it.snap_dist >= 0 && o.dist < 0)      o.flip = 'broke';
        else if (it.snap_dist < 0 && o.dist >= 0) o.flip = 'recovered';
      }
      o.hot = (o.gate === 'stop');
    } else if (it.cost) {
      /* 无止损价但有成本：用规则表里的 stopPct 兜底 */
      const r = RULES[it.sid] || {};
      if (r.stopPct) {
        o.dist = o.pnl - r.stopPct;      /* 距止损的百分点距离 */
        if (o.dist < 0)      { o.gate = 'stop';  o.txt = '已破 ' + r.stopPct + '%'; }
        else if (o.dist < 2) { o.gate = 'watch'; o.txt = '逼近 ' + r.stopPct + '%'; }
        else                 { o.gate = 'ok';    o.txt = '安全'; }
        o.hot = (o.gate === 'stop');
      } else {
        o.gate = 'na'; o.txt = '无止损';
      }
    }
    return o;
  }

  /* ---------- 5. 目标价（线C +3% 止盈，其它策略没有） ---------- */
  function targetOf(it) {
    const r = RULES[it.sid] || {};
    if (it.target != null) return it.target;
    if (r.targetPct != null && it.cost) return it.cost * (1 + r.targetPct / 100);
    return null;
  }

  /* ---------- 6. 交叉校验：实时状态 vs 快照状态 ----------
     返回给人看的告警项。这是「联动」的核心：
     看板说没事、行情说有事 —— 必须当场说清，而不是等收盘再对账。 */
  function crosscheck(items, live, snapDate) {
    const out = [];
    (items || []).forEach(function (it) {
      const q = live[it.code];
      if (!q || q.price == null) return;
      const j = judge(it, q.price);
      const nm = (it.s || '') + ' ' + (it.code || '');
      if (j.flip === 'broke') {
        out.push({
          kind: 'bad', code: it.code,
          txt: nm + '：现价 <b>' + fx(q.price, 3) + '</b> 已跌破止损 <b>' + fx(it.stop, 4)
             + '</b>（' + sg(j.dist) + '）。数据日 ' + (snapDate || '—')
             + ' 记录为 ' + sg(it.snap_dist) + ' ⇒ <b>按规则现在就该卖</b>'
        });
      } else if (j.flip === 'recovered') {
        out.push({
          kind: 'ok', code: it.code,
          txt: nm + '：现价 ' + fx(q.price, 3) + ' 已收回止损线上方（' + sg(j.dist)
             + '）。数据日的补做止损可暂缓，等收盘再判'
        });
      } else if (j.gate === 'watch' && (it.snap_dist == null || it.snap_dist >= 2)) {
        out.push({
          kind: 'warn', code: it.code,
          txt: nm + '：现价 ' + fx(q.price, 3) + ' 距止损仅 <b>' + sg(j.dist)
             + '</b>（数据日还有 ' + sg(it.snap_dist) + '）⇒ 今日盯盘'
        });
      }
    });
    return out;
  }

  /* ---------- 7. 今日动作 × 实时价：限价还成不成立 ----------
     计划里写「挂 0.3584」，现价 0.3620，那就还挂得住；
     现价掉到 0.3550 时再挂 0.3584 就是买在高于市价 —— 必须提醒往下挪。 */
  function checkPlan(plan, price) {
    if (!plan || price == null) return null;
    const m = String(plan.limit || '').match(/([0-9]+\.[0-9]+)/);
    if (!m) return null;
    const lim = parseFloat(m[1]);
    const side = plan.side === 'buy' ? 'buy' : 'sell';
    if (side === 'sell') {
      if (price < lim) return { kind: 'warn', txt: '现价 ' + fx(price, 4) + ' 已低于计划限价 ' + fx(lim, 4) + '，卖单要下移到现价附近才成交' };
      return { kind: 'ok', txt: '现价 ' + fx(price, 4) + ' 高于限价 ' + fx(lim, 4) + '，可直接挂单' };
    }
    if (price > lim) return { kind: 'warn', txt: '现价 ' + fx(price, 4) + ' 已高于计划限价 ' + fx(lim, 4) + '，按纪律「不追高」，放弃这一笔' };
    return { kind: 'ok', txt: '现价 ' + fx(price, 4) + ' 低于限价 ' + fx(lim, 4) + '，可挂单' };
  }

  /* ---------- 8. 小工具 ---------- */
  function fx(v, d) { return (v == null || !isFinite(v)) ? '—' : Number(v).toFixed(d == null ? 3 : d); }
  function sg(v, d) { return (v == null || !isFinite(v)) ? '—' : (v >= 0 ? '+' : '') + Number(v).toFixed(d == null ? 2 : d) + '%'; }

  /* ---------- 9. 把 real_positions / 手机页 items 规范成 judge 需要的形状 ---------- */
  function norm(r) {
    return {
      code: r.code, name: r.name, s: r.strategy || r.s, sid: r.sid,
      cost: r.buy_price != null ? r.buy_price : r.cost,
      stop: r.stop != null ? r.stop : null,
      snap_dist: r.dist_stop != null ? r.dist_stop : (r.snap_dist != null ? r.snap_dist : r.dist),
      snap_pnl: r.pnl != null ? r.pnl : r.snap_pnl,
      act: r.act || (r.live_action && r.live_action.action) || null,
      held: r.held_days != null ? r.held_days : r.held,
      prem: r.prem,
      target: r.target
    };
  }

  return {
    SECID: SECID, TXID: TXID,
    fetchEM: fetchEM, fetchTX: fetchTX, fetchQuote: fetchQuote,
    judge: judge, targetOf: targetOf,
    crosscheck: crosscheck, checkPlan: checkPlan, norm: norm,
    RULES: RULES, fx: fx, sg: sg, hhmmss: hhmmss
  };
})();
