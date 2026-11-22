/* ============================================================================
   predict_core.js —— 调仓预测内核（浏览器端，零本机依赖）
   ----------------------------------------------------------------------------
   为什么要有它
     策略原本由本机 Python 算：`_platform.py` 用次方 API 取历史日线 + 实时快照，
     14:30 输出今日操作。**没开电脑就没有今日操作。**
     这些公式本身不需要 Python —— 加权斜率 V2 只是加权最小二乘，
     乖离率只是 (close/MA-1)×100。搬到浏览器就能做到：
     随时打开、随时用「此刻的价」推演「如果现在收盘会怎么动」。

   数据从哪来（均已实测浏览器可直连，ACAO:*）
     历史日线：腾讯 web.ifzq.gtimg.cn（qfq 前复权，与 Python 口径一致）
     实时价  ：腾讯 qt.gtimg.cn（LC.fetchQuote 已有，双源）

   与 Python 的一致性
     公式逐行照抄 etf_dip_signal/_platform.py：
       wslope_v2()  ← 同文件 38-56 行
       ret_n()      ← 59-61 行
       MOMO 双滤     ← 170-171 行（r20*100≥1、r26*100≥1、0≤score≤3.0，按 score 降序）
       BAND 带内     ← 203 行（r19*100 ∈[2,10]，带内按 r19 降序）
       BANK 开关     ← 221-227 行（s10∈[0.4,2.5] 且 close>MA10 → 持 159552）
       DIP  闸门     ← bt_etf_dip.py 163-177 行（−15% / 回本且 b20≥0 / +3% / 30 日）
     池子与策略参数同样照抄，改一处必须同步两处。

   一个诚实的限制
     线C 的「回本止盈 / 到期换仓」两道闸门需要知道「候选第一名是不是自己」，
     那要扫 381 只全池，浏览器拉不动。所以线C 只给「−15% 深套 / +3% 目标 / 剩余天数」
     这三项精确预测，并明确标注另外两道要回本机看。
     momo(12) / 96863(6) / 96864(2) 池子小，全池扫描，预测是完整的。
   ============================================================================ */
const PC = (function () {
  'use strict';

  /* ---------- 池子与参数（照抄 _platform.py 32-34 行） ---------- */
  const POOLS = {
    momo96865: {
      sid: 96865, name: 'momo 原版', exec: '14:30',
      codes: ['518880', '159509', '588000', '501225', '513100', '513310',
              '159915', '162719', '159985', '513030', '513290', '513520'],
      rule: '20/26 日加权斜率 V2，双滤（20日涨幅≥1%、26日涨幅≥1%、得分∈[0,3]），取最强',
    },
    band96863: {
      sid: 96863, name: '消费轮动', exec: '14:50',
      codes: ['162411', '513100', '161128', '588000', '162415', '515450'],
      rule: '19 日涨幅需落在 2%~10% 带内，带内取涨幅最高；带外不买',
    },
    bank96864: {
      sid: 96864, name: '等股灾', exec: '14:30',
      codes: ['159552', '515020'],
      rule: '159552 的 10 日加权斜率∈[0.4,2.5] 且收盘>MA10 才持它，否则持银行 515020',
    },
  };

  const NAMES = {
    '518880': '黄金ETF', '159509': '纳指科技', '588000': '科创50', '501225': '全球芯片',
    '513100': '纳指100', '513310': '中韩半导体', '159915': '创业板', '162719': '石油LOF',
    '159985': '豆粕ETF', '513030': '德国ETF', '513290': '纳指生物', '513520': '日经ETF',
    '162411': '油气LOF', '161128': '标普信息', '162415': '美国消费', '515450': '红利低波',
    '159552': '中证2000增强', '515020': '银行ETF华夏',
  };

  /* ---------- 历史 K 线：东财优先 → 次方兜底 → 腾讯最后 ----------
     2026-11-22 在公网页面里实测三家（都是在 https 发布域下真实 fetch）：
       东财 push2his  ✅ 200 / 146ms / 131KB   ← 最快，无需 Key
       次方 hist_em   ✅ 200 /   4s / 5.4KB    ← 与回测同源、含 IOPV，但慢
       腾讯 ifzq      ❌ Failed to fetch       ← 对 https 发布域不放行（file:// 下可以）
     所以顺序按「快且稳」排，次方当准确兜底。 */
  function emid(c) { return (/^[56]/.test(c) ? '1.' : '0.') + c; }
  function txid(c) { return (/^[56]/.test(c) ? 'sh' : 'sz') + c; }
  function ymd(d) {
    const p = n => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
  }

  async function klineEM(code, n) {
    const url = 'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=' + emid(code)
      + '&klt=101&fqt=1&beg=0&end=20500101&lmt=' + n
      + '&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58&_=' + Date.now();
    const r = await fetch(url, { cache: 'no-store' });
    const j = await r.json();
    const kl = (j && j.data && j.data.klines) || [];
    return kl.map(function (s) {
      const a = s.split(',');
      return { d: a[0], o: +a[1], c: +a[2], h: +a[3], l: +a[4], v: +a[5] };
    }).filter(function (x) { return isFinite(x.c) && x.c > 0; });
  }

  async function klineCF(code, n) {
    if (typeof CF === 'undefined' || !CF.hasKey || !CF.hasKey()) return null;
    const back = Math.max(120, Math.round(n * 1.7));
    const end = new Date();
    const start = new Date(end.getTime() - back * 86400000);
    const data = await CF.histEm([code], ymd(start), ymd(end), 'qfq');
    const rows = (data && data[code]) || [];
    if (rows.length < Math.min(30, n)) return null;
    return rows.map(function (x) {
      return { d: x[0], o: +x[1], c: +x[2], h: +x[3], l: +x[4], v: +x[6] };
    }).filter(function (x) { return isFinite(x.c) && x.c > 0; });
  }

  async function klineTX(code, n) {
    const url = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param='
      + txid(code) + ',day,,,' + n + ',qfq&_=' + Date.now();
    const r = await fetch(url, { cache: 'no-store' });
    const j = await r.json();
    const d = j && j.data && j.data[txid(code)];
    if (!d) return null;
    const rows = d.qfqday || d.day || [];
    return rows.map(function (x) {
      return { d: x[0], o: +x[1], c: +x[2], h: +x[3], l: +x[4], v: +x[5] };
    }).filter(function (x) { return isFinite(x.c) && x.c > 0; });
  }

  async function kline(code, n) {
    /* ① 优先用页面内嵌的收盘价序列（构建时从 parquet 抽好，0 网络 0 延迟）
          预测只需要 close —— 加权斜率、n 日涨幅、均线乖离全部只吃收盘价。
          2026-11-22 实测：腾讯 ifzq 对 https 域不放行、次方 hist_em 的 CORS 抖动、
          东财 push2his 20 只并发只成功 4 只。三家都不可靠，唯一稳的是内嵌。 */
    if (typeof D !== 'undefined' && D.kline && D.kline[code] && D.kline[code].length >= 30) {
      return D.kline[code].map(function (c) {
        return { d: '', o: c, c: c, h: c, l: c, v: 0 };
      });
    }
    /* ② 内嵌没有（新入池标的）才联网 */
    const need = n;
    try {
      const k = await klineEM(code, Math.max(need, 80));
      if (k && k.length >= Math.min(30, need)) return k;
    } catch (e) { /* 落到次方 */ }
    try {
      const k = await klineCF(code, need);
      if (k && k.length) return k;
    } catch (e) { /* 落到腾讯 */ }
    try { return await klineTX(code, need); } catch (e) { return null; }
  }

  /* ---------- 加权斜率 V2（逐行照抄 wslope_v2） ----------
     y 取最近 n 个收盘，w=(1+i/n)²，加权最小二乘 → slope，
     年化 exp(slope*250)-1，得分 = 年化 × max(R²,0) */
  function wslope(close, n, priceOverride) {
    if (!close || close.length < n) return null;
    const y = close.slice(-n).map(Number);
    if (priceOverride != null) y[n - 1] = priceOverride;   // 用实时价替掉最后一根
    if (y.some(function (v) { return !isFinite(v) || v <= 0; })) return null;

    const x = [], w = [];
    let sw = 0;
    for (let i = 0; i < n; i++) { x.push(i); w.push(Math.pow(1 + i / n, 2)); sw += w[i]; }
    let sxw = 0, syw = 0;
    for (let i = 0; i < n; i++) { sxw += w[i] * x[i]; syw += w[i] * y[i]; }
    const mx = sxw / sw, my = syw / sw;

    let sxx = 0, sxy = 0;
    for (let i = 0; i < n; i++) {
      sxx += w[i] * Math.pow(x[i] - mx, 2);
      sxy += w[i] * (x[i] - mx) * (y[i] - my);
    }
    if (sxx <= 0) return null;
    const slope = sxy / sxx;
    const ann = Math.exp(slope * 250) - 1;

    let ssr = 0, sst = 0;
    for (let i = 0; i < n; i++) {
      const yh = my + slope * (x[i] - mx);
      ssr += w[i] * Math.pow(y[i] - yh, 2);
      sst += w[i] * Math.pow(y[i] - my, 2);
    }
    const r2 = sst > 0 ? 1 - ssr / sst : 0;
    return { ann: ann, score: ann * Math.max(r2, 0), slope: slope, r2: r2 };
  }

  /* ---------- n 日涨幅（照抄 ret_n） ---------- */
  function retN(close, n, priceOverride) {
    if (!close || close.length <= n) return null;
    const last = priceOverride != null ? priceOverride : close[close.length - 1];
    const base = close[close.length - 1 - n];
    if (!isFinite(base) || base <= 0) return null;
    return last / base - 1;
  }

  function ma(close, n, priceOverride) {
    if (!close || close.length < n) return null;
    const seg = close.slice(-n).map(Number);
    if (priceOverride != null) seg[n - 1] = priceOverride;
    const s = seg.reduce(function (a, b) { return a + b; }, 0);
    return s / n;
  }

  /* ---------- 并发受限地批量取 K 线 ---------- */
  async function batchKline(codes, n, conc) {
    const out = {}, list = codes.slice();
    const limit = conc || 4;
    async function worker() {
      while (list.length) {
        const c = list.shift();
        try { out[c] = await kline(c, n); } catch (e) { out[c] = null; }
      }
    }
    await Promise.all(Array.from({ length: Math.min(limit, codes.length) }, worker));
    return out;
  }

  /* ---------- momo 96865：全池扫描 ---------- */
  async function predictMomo(live, holdCode) {
    const P = POOLS.momo96865;
    const ks = await batchKline(P.codes, 60, 4);
    const rows = [];
    P.codes.forEach(function (c) {
      const k = ks[c];
      if (!k || k.length < 30) { rows.push({ code: c, name: NAMES[c], err: true }); return; }
      const cl = k.map(function (z) { return z.c; });
      const lv = live[c] && live[c].price != null ? live[c].price : null;
      const s = wslope(cl, 20, lv);
      const r20 = retN(cl, 20, lv), r26 = retN(cl, 26, lv);
      const pass = !!(s && r20 != null && r26 != null
        && r20 * 100 >= 1 && r26 * 100 >= 1 && s.score >= 0 && s.score <= 3.0);
      rows.push({
        code: c, name: NAMES[c] || c,
        score: s ? +s.score.toFixed(3) : null,
        r20: r20 != null ? +(r20 * 100).toFixed(2) : null,
        r26: r26 != null ? +(r26 * 100).toFixed(2) : null,
        last: lv != null ? lv : cl[cl.length - 1],
        pass: pass,
      });
    });
    rows.sort(function (a, b) { return (b.score == null ? -1e9 : b.score) - (a.score == null ? -1e9 : a.score); });
    const ok = rows.filter(function (x) { return x.pass; });
    const top = ok[0] || null;
    const hold = holdCode ? rows.find(function (x) { return x.code === holdCode; }) : null;
    const holdOk = holdCode ? ok.find(function (x) { return x.code === holdCode; }) : null;

    let action = 'hold', reason = '';
    if (top) {
      if (holdCode && top.code === holdCode) { action = 'hold'; reason = '当前持仓仍是双滤后第一'; }
      else if (holdCode) { action = 'switch'; reason = '第一名已变成 ' + top.code + ' ' + (top.name || ''); }
      else { action = 'buy'; reason = '当前空仓，第一名 ' + top.code + ' 可买入'; }
    } else {
      action = holdCode ? 'sell' : 'empty';
      reason = '12 只全部不满足双滤（需 20日≥1%、26日≥1%、得分≤3）⇒ ' + (holdCode ? '满足最短持有后清仓' : '空仓');
    }
    if (holdCode && hold && hold.pass === false && !top) {
      action = 'sell';
    }
    return {
      id: 'momo96865', name: 'momo 原版 96865', exec: P.exec, rule: P.rule,
      ok: true, rows: rows, top: top, hold: hold, holdOk: !!holdOk,
      action: action, reason: reason,
      passN: ok.length, poolN: rows.filter(function (x) { return !x.err; }).length,
    };
  }

  /* ---------- 96863：19 日带内 ---------- */
  async function predictBand(live, holdCode) {
    const P = POOLS.band96863;
    const ks = await batchKline(P.codes, 40, 3);
    const rows = [];
    P.codes.forEach(function (c) {
      const k = ks[c];
      if (!k || k.length < 25) { rows.push({ code: c, name: NAMES[c], err: true }); return; }
      const cl = k.map(function (z) { return z.c; });
      const lv = live[c] && live[c].price != null ? live[c].price : null;
      const r19 = retN(cl, 19, lv);
      const v = r19 != null ? r19 * 100 : null;
      rows.push({
        code: c, name: NAMES[c] || c,
        r19: v != null ? +v.toFixed(2) : null,
        last: lv != null ? lv : cl[cl.length - 1],
        pass: v != null && v >= 2.0 && v <= 10.0,
      });
    });
    rows.sort(function (a, b) { return (b.r19 == null ? -1e9 : b.r19) - (a.r19 == null ? -1e9 : a.r19); });
    const ok = rows.filter(function (x) { return x.pass; });
    const top = ok[0] || null;
    const hold = holdCode ? rows.find(function (x) { return x.code === holdCode; }) : null;

    let action = 'hold', reason = '';
    if (top) {
      if (holdCode === top.code) { action = 'hold'; reason = '持仓仍在带内且最强'; }
      else if (holdCode) { action = 'switch'; reason = '带内最强变成 ' + top.code; }
      else { action = 'buy'; reason = '带内最强 ' + top.code + '（' + (top.r19) + '%）'; }
    } else {
      action = holdCode ? 'sell' : 'empty';
      reason = '6 只没有一个落在 2%~10% 带内 ⇒ ' + (holdCode ? '卖出' : '空仓');
    }
    return {
      id: 'band96863', name: '消费轮动 96863', exec: P.exec, rule: P.rule,
      ok: true, rows: rows, top: top, hold: hold,
      action: action, reason: reason,
      passN: ok.length, poolN: rows.filter(function (x) { return !x.err; }).length,
    };
  }

  /* ---------- 96864：斜率开关 ---------- */
  async function predictBank(live) {
    const P = POOLS.bank96864;
    const ks = await batchKline(P.codes, 40, 2);
    const k = ks['159552'];
    let s10 = null, ma10 = null, last = null, inRange = false, above = false;
    if (k && k.length >= 15) {
      const cl = k.map(function (z) { return z.c; });
      const lv = live['159552'] && live['159552'].price != null ? live['159552'].price : null;
      s10 = wslope(cl, 10, lv);
      ma10 = ma(cl, 10, lv);
      last = lv != null ? lv : cl[cl.length - 1];
      inRange = !!(s10 && s10.score >= 0.4 && s10.score <= 2.5);
      above = !!(ma10 != null && last > ma10);
    }
    const holdMain = inRange && above;
    return {
      id: 'bank96864', name: '等股灾 96864', exec: P.exec, rule: P.rule,
      ok: !!(s10 && ma10 != null),
      score: s10 ? +s10.score.toFixed(3) : null,
      ma10: ma10 != null ? +ma10.toFixed(4) : null,
      last: last,
      inRange: inRange, aboveMa10: above,
      target: holdMain ? '159552' : '515020',
      targetName: holdMain ? '中证2000增强' : '银行ETF华夏',
      action: 'hold',
      reason: holdMain
        ? '斜率 ' + (s10 ? s10.score.toFixed(2) : '—') + ' ∈[0.4,2.5] 且站上 MA10 ⇒ 持 159552 进攻腿'
        : (inRange === false
            ? '斜率 ' + (s10 ? s10.score.toFixed(2) : '—') + ' 不在 [0.4,2.5] ⇒ 回落到银行默认腿'
            : '收盘未站上 MA10（' + (ma10 != null ? ma10.toFixed(4) : '—') + '）⇒ 回落到银行默认腿'),
    };
  }

  /* ---------- 线C：只做「价格能决定」的三道闸门 ----------
     −15% 深套止损、+3% 目标、剩余天数 — 这三道只看自己这只的价，能精确预测。
     「回本止盈」「到期换仓」要看 381 只全池谁是第一，浏览器拉不动，明确不预测。 */
  async function predictDip(live, pos) {
    if (!pos || !pos.code) return null;
    const k = await kline(pos.code, 80);
    const out = {
      id: 'lineC', name: '线C 乖离抄底', exec: '14:45',
      rule: '四道闸门：−15% 深套 / 回本且 20日乖离≥0 / +3% / 满 30 日',
      ok: !!(k && k.length >= 25), code: pos.code, name2: pos.name,
      cost: pos.cost, stop: pos.stop, held: pos.held,
      gates: [], partial: true,
    };
    if (!out.ok) return out;
    const cl = k.map(function (z) { return z.c; });
    const lv = live[pos.code] && live[pos.code].price != null ? live[pos.code].price : null;
    const px = lv != null ? lv : cl[cl.length - 1];
    const m20 = ma(cl, 20, lv);
    const b20 = m20 ? (px / m20 - 1) * 100 : null;
    const ret = pos.cost ? (px / pos.cost - 1) * 100 : null;
    out.price = px;
    out.b20 = b20 != null ? +b20.toFixed(2) : null;

    if (ret != null) {
      out.gates.push({
        k: '深套止损', th: '−15%', now: ret,
        hit: ret <= -15,
        left: +((ret + 15)).toFixed(2),        // 还要跌多少 pp 才触发
        txt: ret <= -15 ? '已触发，按规则卖出' : ('再跌 ' + Math.abs(ret + 15).toFixed(2) + 'pp 触发'),
        price: pos.cost ? +(pos.cost * 0.85).toFixed(4) : null,
      });
      out.gates.push({
        k: '目标收益', th: '+3%', now: ret,
        hit: ret >= 3,
        left: +(3 - ret).toFixed(2),
        txt: ret >= 3 ? '已触发（还需候选第一不是自己）' : ('再涨 ' + (3 - ret).toFixed(2) + 'pp 触发'),
        price: pos.cost ? +(pos.cost * 1.03).toFixed(4) : null,
      });
    }
    const left = pos.held != null ? Math.max(0, 30 - pos.held) : null;
    out.gates.push({
      k: '到期换仓', th: '30 日', now: pos.held, hit: left === 0,
      left: left,
      txt: left === 0 ? '已满 30 日（还需候选第一不是自己）' : ('还剩 ' + left + ' 个交易日'),
      price: null,
    });

    /* 回本止盈：需要 b20>=0 且 ret>=0，两个条件能算；但「候选第一不是自己」算不了 */
    if (b20 != null && ret != null) {
      out.recover = {
        b20ok: b20 >= 0, retOk: ret >= 0,
        txt: (b20 >= 0 && ret >= 0)
          ? '价格条件已满足（20日乖离 ' + b20.toFixed(2) + '% ≥0、浮盈 ' + ret.toFixed(2) + '%），是否卖取决于候选第一名'
          : '未满足：20日乖离 ' + b20.toFixed(2) + '%（需≥0）、浮盈 ' + ret.toFixed(2) + '%（需≥0）',
      };
    }

    /* 动作：只看「价格能决定」的闸门。−15% 已破就是卖，其它维持 */
    const stopHit = ret != null && ret <= -15;
    out.action = stopHit ? 'sell' : 'hold';
    out.reason = stopHit
      ? ('浮亏 ' + ret.toFixed(2) + '% 已跌破 −15% 深套止损线 ⇒ 按规则卖出，卖出后 3 个交易日不开新仓')
      : ('三道价格闸门均未触发（浮亏 ' + (ret == null ? '—' : ret.toFixed(2) + '%')
         + '，20日乖离 ' + (b20 == null ? '—' : b20.toFixed(2) + '%')
         + '），持有第 ' + (pos.held == null ? '?' : pos.held) + ' 天');
    return out;
  }

  /* ---------- 汇总：一次算完四条 ---------- */
  async function predictAll(live, holds) {
    const t0 = Date.now();
    const tasks = [
      predictMomo(live, (holds.momo96865 || {}).code),
      predictBand(live, (holds.band96863 || {}).code),
      predictBank(live),
      predictDip(live, holds.lineC),
    ];
    const res = await Promise.all(tasks.map(function (p) {
      return p.catch(function (e) { return { ok: false, err: String(e && e.message || e) }; });
    }));
    return {
      at: LC.hhmmss(),
      ms: Date.now() - t0,
      strategies: res.filter(Boolean),
      codes: [...new Set([].concat(
        POOLS.momo96865.codes, POOLS.band96863.codes, POOLS.bank96864.codes,
        holds.lineC ? [holds.lineC.code] : []
      ))],
    };
  }

  return {
    POOLS: POOLS, NAMES: NAMES,
    kline: kline, wslope: wslope, retN: retN, ma: ma,
    predictMomo: predictMomo, predictBand: predictBand,
    predictBank: predictBank, predictDip: predictDip, predictAll: predictAll,
  };
})();
