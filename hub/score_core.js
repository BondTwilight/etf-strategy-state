/* ============================================================================
 * score_core.js — 浏览器端「实时评分 + 环境判据」引擎
 *
 * 目的：让手机不开电脑就能知道「现在什么天气、这个天气适合哪条策略」。
 * 口径必须与 Python 侧逐位一致，否则评分是假的：
 *   - 指标与四维打分 ← etf_dip_signal/market_state.py（已对次方页面逐位校验）
 *   - 环境分档        ← etf_dip_signal/_sim.py  regime_series()
 *
 * 为什么所有序列都内嵌、不联网：
 *   2026-11-22 实测，三家行情源在 https 发布域下全部不稳定
 *   （腾讯 ifzq 不放行、东财 20 只并发只成 4 只、次方 CORS 抖动）。
 *   评分错一次就是配错仓，不能用会抖的源。
 * ========================================================================== */
const SC = (function () {
  'use strict';

  const REGIME_LABEL = {
    A: '趋势上行·低波', B: '趋势下行·防御有效', Bp: '趋势下行·成长占优',
    C: '震荡·中高波', D: '危机·无差别去杠杆',
  };
  const REGIME_ORDER = ['A', 'C', 'Bp', 'B', 'D'];

  function r(x, n) {
    if (x == null || !isFinite(x)) return null;
    const p = Math.pow(10, n == null ? 4 : n);
    return Math.round(x * p) / p;
  }

  /* ---------- 1. 基础序列运算（对齐 pandas） ---------- */

  function sma(arr, n) {
    const out = new Array(arr.length).fill(null);
    let s = 0;
    for (let i = 0; i < arr.length; i++) {
      s += arr[i];
      if (i >= n) s -= arr[i - n];
      if (i >= n - 1) out[i] = s / n;
    }
    return out;
  }

  /* pandas ewm(span, adjust=False)：y0=x0, yi=(1-a)yi-1 + a·xi, a=2/(span+1) */
  function ewm(arr, span) {
    const a = 2 / (span + 1), out = new Array(arr.length).fill(null);
    let prev = null;
    for (let i = 0; i < arr.length; i++) {
      const x = arr[i];
      if (x == null || !isFinite(x)) { out[i] = prev; continue; }
      prev = (prev == null) ? x : (1 - a) * prev + a * x;
      out[i] = prev;
    }
    return out;
  }

  function diff(arr) {
    return arr.map(function (x, i) { return i ? x - arr[i - 1] : null; });
  }

  /* 简单均值滚动（RSI/ATR 都用它 —— 次方不用 Wilder，实测对不上） */
  function rollMean(arr, n) {
    const out = new Array(arr.length).fill(null);
    for (let i = 0; i < arr.length; i++) {
      if (i < n - 1) continue;
      let s = 0, ok = true;
      for (let j = i - n + 1; j <= i; j++) {
        const v = arr[j];
        if (v == null || !isFinite(v)) { ok = false; break; }
        s += v;
      }
      if (ok) out[i] = s / n;
    }
    return out;
  }

  /* pandas rolling(n).std(ddof=0) —— 总体标准差 */
  function rollStd(arr, n) {
    const out = new Array(arr.length).fill(null);
    for (let i = 0; i < arr.length; i++) {
      if (i < n - 1) continue;
      let s = 0, ok = true;
      for (let j = i - n + 1; j <= i; j++) {
        const v = arr[j];
        if (v == null || !isFinite(v)) { ok = false; break; }
        s += v;
      }
      if (!ok) continue;
      const m = s / n;
      let q = 0;
      for (let j = i - n + 1; j <= i; j++) q += (arr[j] - m) * (arr[j] - m);
      out[i] = Math.sqrt(q / n);
    }
    return out;
  }

  function pctChange(arr, n) {
    return arr.map(function (x, i) {
      return (i < n || arr[i - n] == null || !arr[i - n]) ? null : x / arr[i - n] - 1;
    });
  }

  /* ---------- 2. 指标（对齐 market_state.indicators） ---------- */
  /* ohlcv: [[o,h,l,c,v], ...] 升序 */
  function indicators(ohlcv, dates) {
    const n = ohlcv.length;
    const c = ohlcv.map(function (x) { return +x[3]; });
    const h = ohlcv.map(function (x) { return +x[1]; });
    const l = ohlcv.map(function (x) { return +x[2]; });
    const v = ohlcv.map(function (x) { return +x[4]; });
    const ma = {};
    [5, 10, 20, 60].forEach(function (k) { ma[k] = sma(c, k); });

    const e12 = ewm(c, 12), e26 = ewm(c, 26);
    const dif = e12.map(function (x, i) { return (x == null || e26[i] == null) ? null : x - e26[i]; });
    const dea = ewm(dif, 9);

    const d = diff(c);
    const up = d.map(function (x) { return x == null ? null : Math.max(x, 0); });
    const dn = d.map(function (x) { return x == null ? null : Math.max(-x, 0); });
    const ru = rollMean(up, 14), rd = rollMean(dn, 14);
    const rsi = ru.map(function (x, i) {
      const y = rd[i];
      if (x == null || y == null) return null;
      if (y === 0) return x === 0 ? 50 : 100;
      return 100 - 100 / (1 + x / y);
    });

    const tr = ohlcv.map(function (x, i) {
      const hh = +x[1], ll = +x[2];
      const pc = i ? +ohlcv[i - 1][3] : null;
      const a = hh - ll;
      if (pc == null) return a;
      return Math.max(a, Math.abs(hh - pc), Math.abs(ll - pc));
    });
    const atr = rollMean(tr, 14);

    const mid = ma[20];
    const std = rollStd(c, 20);
    const bw = mid.map(function (m, i) {
      return (m == null || std[i] == null || m === 0) ? null : 4 * std[i] / m;
    });

    const v5 = sma(v, 5), v20 = sma(v, 20);
    const i0 = n - 1;
    const o = {
      date: (dates && dates[i0]) || '',
      close: r(c[i0]),
      chg: (i0 >= 1) ? r((c[i0] / c[i0 - 1] - 1) * 100, 2) : null,
      MA5: r(ma[5][i0]), MA10: r(ma[10][i0]),
      MA20: r(ma[20][i0]), MA60: r(ma[60][i0]),
      DIF: r(dif[i0]), DEA: r(dea[i0]),
      MACD_HIST: r((dif[i0] != null && dea[i0] != null) ? (dif[i0] - dea[i0]) * 2 : null),
      RSI: r(rsi[i0], 2),
      ATR: r(atr[i0]),
      BOLL_bw: r(bw[i0]),
      BOLL_up: r((mid[i0] != null && std[i0] != null) ? mid[i0] + 2 * std[i0] : null),
      BOLL_dn: r((mid[i0] != null && std[i0] != null) ? mid[i0] - 2 * std[i0] : null),
      vol5: r(v5[i0] != null ? v5[i0] / 1e8 : null, 2),
      vol20: r(v20[i0] != null ? v20[i0] / 1e8 : null, 2),
      vol_ratio: r((v5[i0] != null && v20[i0]) ? v5[i0] / v20[i0] : null, 3),
      ret5: (i0 >= 5) ? r((c[i0] / c[i0 - 5] - 1) * 100, 2) : null,
    };
    // ATR 20 日变化：末值 vs 前 20 个 ATR 的均值（对齐 atr.iloc[-21:-1].mean()）
    let pv = 0, pn = 0;
    for (let j = Math.max(0, i0 - 20); j < i0; j++) {
      if (atr[j] != null && isFinite(atr[j])) { pv += atr[j]; pn++; }
    }
    o.ATR_chg = (pn && pv / pn) ? r((atr[i0] / (pv / pn) - 1) * 100, 2) : null;

    /* ---------- 口径之外的观察（不进总分，用来解释「为什么是 0」） ----------
       次方四维只看「水平」，不看「单日强度」和「趋势」：
         量比 1.285 落在 0.7~1.5 就判「正常」→ 0 分，
         但当天可能是 2.2 倍量下跌，这个信号被吃掉了。
       带宽 <0.05 只提示「变盘临近」→ 0 分，但它是近 20 日什么分位，
         用户有权知道。
       这些不改总分（要与次方页面一致），但必须显示出来。 */
    o.vol_mult = (v20[i0] ? r(v[i0] / v20[i0], 2) : null);           // 今日量 / 20日均量
    // 5 日环比
    let a5 = 0, b5 = 0, c5 = 0, d5 = 0;
    for (let j = i0 - 4; j <= i0; j++) { if (isFinite(v[j])) { a5 += v[j]; c5++; } }
    for (let j = i0 - 9; j <= i0 - 5; j++) { if (isFinite(v[j])) { b5 += v[j]; d5++; } }
    o.vol_chg5 = (c5 && d5 && b5) ? r((a5 / c5) / (b5 / d5) * 100 - 100, 1) : null;
    // 成交量 10 日线性斜率（亿股/日）
    const yv = []; for (let j = Math.max(0, i0 - 9); j <= i0; j++) yv.push(v[j] / 1e8);
    let sxy = 0, sx = 0, sy = 0, sxx = 0;
    const nn = yv.length;
    yv.forEach(function (yy, j) { sxy += j * yy; sx += j; sy += yy; sxx += j * j; });
    const den = nn * sxx - sx * sx;
    o.vol_slope = den ? r((nn * sxy - sx * sy) / den, 3) : null;
    // 带宽在近 20 日的分位
    const bws = [];
    for (let j = Math.max(0, i0 - 19); j <= i0; j++) if (bw[j] != null) bws.push(bw[j]);
    if (bws.length > 1) {
      const lastb = bws[bws.length - 1];
      o.bw_pct = r(bws.filter(function (x) { return x < lastb; }).length / bws.length * 100, 0);
      o.bw_min20 = r(Math.min.apply(null, bws));
      o.bw_max20 = r(Math.max.apply(null, bws));
    }
    // 量价组合（单日口径，比 v5/v20 敏感）
    o.vol_combo = '';
    if (o.vol_mult != null && o.chg != null) {
      if (o.vol_mult > 1.5) o.vol_combo = o.chg >= 0 ? '放量上涨' : '放量下跌';
      else if (o.vol_mult < 0.7) o.vol_combo = o.chg >= 0 ? '缩量上涨' : '缩量下跌';
      else o.vol_combo = '量能平稳';
    }
    return o;
  }

  /* ---------- 3. 四维打分（对齐 market_state.score） ---------- */
  function mktScore(o) {
    const m5 = o.MA5, m10 = o.MA10, m20 = o.MA20, m60 = o.MA60;
    let t, tLab;
    const bull = m5 > m10 && m10 > m20 && (m60 == null || m20 > m60);
    const bear = m5 < m10 && m10 < m20 && (m60 == null || m20 < m60);
    if (bull) { t = 100; tLab = '完全多头'; }
    else if (bear) { t = -100; tLab = '完全空头'; }
    else if (m5 > m10 && m10 <= m20) { t = 50; tLab = '部分多头（短期拐头）'; }
    else if (m5 < m10 && m10 >= m20) { t = -50; tLab = '部分空头（短期拐头）'; }
    else { t = 0; tLab = '纠缠'; }

    const dif = o.DIF, dea = o.DEA, rsi = o.RSI;
    let mc, mcLab;
    if (dif > dea && dif > 0) { mc = 100; mcLab = '强势金叉'; }
    else if (dif > dea) { mc = 50; mcLab = '弱势金叉'; }
    else if (dif < dea && dif < 0) { mc = -100; mcLab = '强势死叉'; }
    else { mc = -50; mcLab = '弱势死叉'; }
    let rs, rsLab;
    if (rsi >= 70) { rs = 100; rsLab = '超买'; }
    else if (rsi <= 30) { rs = -100; rsLab = '超卖'; }
    else { rs = 0; rsLab = '正常'; }
    const mom = 0.5 * mc + 0.5 * rs;

    const ac = o.ATR_chg;
    let at, atLab;
    if (ac == null) { at = 0; atLab = '无数据'; }
    else if (ac > 20) { at = -100; atLab = '波动率快速上升'; }
    else if (ac < -20) { at = 50; atLab = '波动率收敛'; }
    else { at = 0; atLab = '波动率正常'; }
    const bw = o.BOLL_bw;
    let bt, btLab;
    if (bw > 0.15) { bt = 100; btLab = '趋势强劲'; }
    else if (bw < 0.05) { bt = 0; btLab = '极窄·等待方向'; }
    else { bt = 0; btLab = '正常'; }
    const vol = 0.5 * at + 0.5 * bt;

    const vr = o.vol_ratio, r5 = o.ret5;
    let vt, vtLab;
    if (vr == null) { vt = 0; vtLab = '无数据'; }
    else if (vr > 1.5) { vt = (r5 != null && r5 >= 0) ? 100 : -100; vtLab = (r5 >= 0) ? '放量上涨' : '放量下跌'; }
    else if (vr < 0.7) { vt = (r5 != null && r5 >= 0) ? 30 : -30; vtLab = (r5 >= 0) ? '缩量上涨' : '缩量下跌'; }
    else { vt = 0; vtLab = '量能正常'; }

    const total = 0.40 * t + 0.30 * mom + 0.15 * vol + 0.15 * vt;
    let state;
    if (total > 30) state = '牛市';
    else if (total < -30) state = '熊市';
    else state = '震荡市';
    const conf = Math.min(Math.abs(total) / 100, 1);

    return {
      total: r(total, 1), state: state, conf: r(conf * 100, 1),
      conf_note: conf < 0.3 ? '判断不可靠，方向并不明确'
        : (conf > 0.7 ? '可以当作重要参考' : '中等强度，需结合其他证据'),
      squeeze: !!(bw < 0.05),
      dims: [
        { k: '趋势', w: 40, v: r(t, 1), label: tLab,
          why: 'MA5 ' + o.MA5 + ' / MA10 ' + o.MA10 + ' / MA20 ' + o.MA20
            + (o.MA60 == null ? '' : ' / MA60 ' + o.MA60)
            + ' ⇒ ' + tLab + ' ' + (t > 0 ? '+' : '') + t,
          detail: 'MA5 ' + o.MA5 + ' ｜ MA10 ' + o.MA10 + ' ｜ MA20 ' + o.MA20
            + (o.MA60 == null ? '' : ' ｜ MA60 ' + o.MA60) },
        { k: '动量', w: 30, v: r(mom, 1), label: mcLab + ' / RSI ' + rsLab,
          why: 'DIF ' + o.DIF + (dif > dea ? ' ≥ ' : ' < ') + 'DEA ' + o.DEA
            + ' ⇒ ' + mcLab + ' ' + (mc > 0 ? '+' : '') + mc
            + '；RSI ' + o.RSI + (rsi >= 70 ? ' ≥70 超买' : (rsi <= 30 ? ' ≤30 超卖' : ' 在 30~70 正常'))
            + ' ' + (rs > 0 ? '+' : '') + rs
            + ' ⇒ 各取一半 = ' + (mom > 0 ? '+' : '') + r(mom, 1),
          detail: 'DIF ' + o.DIF + (dif > dea ? ' > ' : ' < ') + 'DEA ' + o.DEA + ' ｜ RSI ' + o.RSI },
        { k: '波动率', w: 15, v: r(vol, 1), label: atLab + ' / ' + btLab,
          why: 'ATR 20日变化 ' + (o.ATR_chg > 0 ? '+' : '') + o.ATR_chg + '%'
            + (ac == null ? '（无数据）' : (ac > 20 ? ' >+20% 波动骤升 −100'
              : (ac < -20 ? ' <−20% 波动收敛 +50' : ' 在 ±20% 内 0')))
            + '；布林带宽 ' + o.BOLL_bw
            + (bw > 0.15 ? ' >0.15 趋势强劲 +100'
              : (bw < 0.05 ? ' <0.05 极窄（口径只提示、不加分）0' : ' 在 0.05~0.15 正常 0'))
            + ' ⇒ 各取一半 = ' + (vol > 0 ? '+' : '') + r(vol, 1)
            + (o.bw_pct != null ? '。带宽在近 20 日分位 ' + o.bw_pct + '%' : ''),
          detail: 'ATR ' + o.ATR + '（20日变化 ' + (o.ATR_chg > 0 ? '+' : '') + o.ATR_chg + '%）｜ 带宽 ' + o.BOLL_bw },
        { k: '成交量', w: 15, v: r(vt, 1), label: vtLab,
          why: '量比（5日/20日）' + vr + (vr == null ? '（无数据）'
            : (vr > 1.5 ? ' >1.5 放量' : (vr < 0.7 ? ' <0.7 缩量' : ' 在 0.7~1.5 正常 0')))
            + (vr != null && vr <= 1.5 && vr >= 0.7
              ? '。注意：本口径只看均量水平，不看单日强度 —— 今日单日 '
                + o.vol_mult + ' 倍量、' + o.vol_combo + '，这层不在四维里'
              : '')
            + ' ⇒ ' + (vt > 0 ? '+' : '') + r(vt, 1),
          detail: '5日均量 ' + o.vol5 + ' 亿股 / 20日均量 ' + o.vol20 + ' 亿股 ⇒ 量比 ' + vr },
      ],
    };
  }

  /* ---------- 4. 环境判据（对齐 _sim.regime_series） ----------
     判定树（顺序即优先级）：
       below = 沪深300 < MA200
       D  : below 且 创业板波动分位 ≥85% 且 红利20日 < −5%
       B  : below 且 成长(创业板) − 红利 20日差 < 0
       B' : below
       A  : 未破 MA200 且 波动分位 < 50%
       C  : 其余
     注意「红利」用的是 510880，不是持仓里的 515450 —— 前者是判据标的。
  */
  function volPct(vols, win, minp) {
    const v = vols.filter(function (x) { return x != null && isFinite(x); });
    if (v.length < (minp || 250)) return null;
    const a = v.slice(-(win || 750));
    const last = a[a.length - 1];
    const prev = a.slice(0, -1);
    if (!prev.length) return null;
    return prev.filter(function (x) { return x < last; }).length / prev.length;
  }

  function regime(sd) {
    const cl = (sd && sd.close) || {};
    const hs = cl['510300'], cy = cl['159915'], dv = cl['510880'];
    if (!hs || !cy || !dv) {
      return { ok: false, err: '内嵌序列缺 510300 / 159915 / 510880' };
    }
    const n = Math.min(hs.length, cy.length, dv.length);
    const H = hs.slice(-n), C = cy.slice(-n), D = dv.slice(-n);

    const ma200 = sma(H, 200);
    const i0 = n - 1;
    const dev = (ma200[i0] == null) ? null : H[i0] / ma200[i0] - 1;
    const below = dev != null && dev < 0;

    const r20c = C[i0] / C[i0 - 20] - 1;
    const r20d = D[i0] / D[i0 - 20] - 1;
    const gmd = r20c - r20d;

    const pc = C.map(function (x, i) { return i ? x / C[i - 1] - 1 : null; });
    const v20 = rollStd(pc, 20);
    const vol = v20.map(function (x) { return x == null ? null : x * Math.sqrt(252); });
    const vp = volPct(vol, 750, 250);

    let code;
    if (below && vp >= 0.85 && r20d < -0.05) code = 'D';
    else if (below && gmd < 0) code = 'B';
    else if (below) code = 'Bp';
    else if (vp < 0.50) code = 'A';
    else code = 'C';

    const ma200d = sma(D, 200);
    const dDev = (ma200d[i0] == null) ? null : D[i0] / ma200d[i0] - 1;

    /* 每条判据都要能回答「它达标了没、为什么没有/有」——
       只显示一个没打勾的点，会被误读成「没有数据」。 */
    const volOk = vp >= 0.85;
    const dvOk = r20d < -0.05;
    const noteVol = (vp == null) ? '样本不足 250 个观测，算不出分位'
      : (volOk && dvOk ? '两项都满足 ⇒ 触发 D'
        : (volOk ? ('波动 ' + (vp * 100).toFixed(1) + '% 已 ≥85% 达标，'
                   + '但红利 20 日 ' + (r20d > 0 ? '+' : '') + (r20d * 100).toFixed(2)
                   + '% 未跌破 −5% ⇒ 不判 D')
          : ('波动 ' + (vp * 100).toFixed(1) + '% 未达 85% 门槛'
             + (dvOk ? '（红利已跌 ' + (r20d * 100).toFixed(2) + '%，只差波动这一项）' : ''))));

    return {
      ok: true, code: code, label: REGIME_LABEL[code] || '',
      items: [
        { k: '沪深300 距 MA200', v: r(dev * 100, 2), unit: '%', hit: below,
          th: '< 0 ⇒ 趋势向下（第一层：决定上行/下行）',
          note: below ? '已跌破 MA200 ⇒ 判为下行趋势' : '站上 MA200 ⇒ 判为上行趋势' },
        { k: '创业板 20 日波动分位', v: r(vp * 100, 1), unit: '%',
          hit: !!(volOk && dvOk),
          th: '≥85% 且 红利20日 < −5% ⇒ D（第二层：是否无差别去杠杆）',
          note: noteVol, part: !!(volOk !== dvOk) },
        { k: '成长 − 红利 20 日差', v: r(gmd * 100, 2), unit: 'pp', hit: gmd < 0,
          th: '< 0 ⇒ B（防御腿有效）；≥ 0 ⇒ B′（第三层）',
          note: gmd < 0 ? '成长跑输红利 ⇒ 防御腿有效，判 B'
            : '成长仍跑赢红利 ⇒ 判 B′（进攻腿更值得拿）' },
        { k: '红利 距 MA200', v: r(dDev * 100, 2), unit: '%',
          hit: !!(dDev != null && dDev > 0),
          th: '> 0 说明防御腿自己还在趋势上（B 档的佐证）',
          note: (dDev == null) ? '样本不足'
            : (dDev > 0 ? '红利自己还在 MA200 上方 ⇒ 「防御有效」不是猜的'
              : '红利也跌破 MA200 ⇒ 防御腿失效，B 档的结论要打折扣') },
      ],
      raw: { dev: dev, vp: vp, gmd: gmd, r20dv: r20d, dDev: dDev },
    };
  }

  /* ---------- 5. 策略适配：按当前 regime 列查矩阵 ---------- */
  /* matrix = hub.regime_matrix {regimes:[{k,label,n}], rows:[{id,name,cells:[{mean_bp,win,n}]}]} */
  function adapt(matrix, code) {
    if (!matrix || !matrix.regimes || !matrix.rows) return [];
    const idx = matrix.regimes.findIndex(function (x) { return x.k === code; });
    if (idx < 0) return [];
    const out = matrix.rows.map(function (row) {
      const c = row.cells[idx];
      return {
        id: row.id, name: row.name,
        bp: c ? c.mean_bp : null, win: c ? c.win : null, n: c ? c.n : null,
      };
    }).filter(function (x) { return x.bp != null; });
    out.sort(function (a, b) { return b.bp - a.bp; });
    return out;
  }

  /* ---------- 6. 实时评分：静态基线 + 随 regime 变的「环境适配」 ----------
     score_strategy 里唯一会随行情变的是「当前环境适配 18 分」：
        v = 18 × (0.6·rank(bp) + 0.4·rank(win))，rank 为四条策略间的 pct 排名。
     其余八维是历史统计与静态属性，不因今天涨跌而变（写死在内嵌基线里）。
     所以这里只重算那一维，并把差额加到总分上 —— 不虚构会变的东西。
  */
  function pctRank(vals) {
    const idx = vals.map(function (v, i) { return { v: v, i: i }; })
      .sort(function (a, b) { return a.v - b.v; });
    const out = new Array(vals.length).fill(0.5);
    idx.forEach(function (o, k) { out[o.i] = (k + 1) / vals.length; });
    return out;
  }

  function rescore(strategies, matrix, code) {
    const ad = adapt(matrix, code);
    if (!ad.length) return [];
    const map = {};
    ad.forEach(function (x) { map[x.id] = x; });

    const ids = ad.map(function (x) { return x.id; });
    const rb = pctRank(ad.map(function (x) { return x.bp; }));
    const rw = pctRank(ad.map(function (x) { return x.win == null ? 0 : x.win; }));

    return strategies.map(function (s) {
      const a = map[s.id];
      if (!a) return null;
      const k = ids.indexOf(s.id);
      const regRank = 0.6 * rb[k] + 0.4 * rw[k];
      const newDim = 18 * regRank;
      // 找基线里的「环境适配」项
      const items = (s.score && s.score.items) ? s.score.items : [];
      const oldDim = (items.find(function (x) { return x.k === '当前环境适配'; }) || {}).v;
      const base = (s.score && s.score.total) || 0;
      const total = oldDim == null ? base : base - oldDim + newDim;
      return {
        id: s.id, name: s.name, rank: null,
        bp: a.bp, win: a.win, n: a.n,
        regRank: regRank, regDim: r(newDim, 1), regDimOld: oldDim,
        total: r(total, 1), base: base,
        delta: oldDim == null ? null : r(newDim - oldDim, 1),
        // 该策略在这个 regime 下历史日均 bp 的横截面名次
        rankInRegime: k + 1, nStrategies: ad.length,
      };
    }).filter(Boolean).sort(function (a, b) { return b.total - a.total; });
  }

  /* ---------- 6.5 多市场广度 ----------
     用户批评得对：只看 510300 的均线排列，会被单一标的骗线。
     真正的「大盘怎么样」要看多个市场同时有多少在涨 —— 这是我们原来缺的一层。

     做两件事：
       breadth   ：跨市场标的里，20 日涨幅 > 0 的占比（市场广度）
       riskOn    ：风险资产（纳指/创业板/油气）vs 避险（黄金/红利）的 20 日相对强弱
     两个都用 close 序列，不需要 OHLCV，所以成本很低。
  */
  const RISK_ASSETS = ['513100', '159509', '159915', '162411'];
  const SAFE_ASSETS = ['518880', '510880'];
  const BREADTH_CORE = ['510300', '159915', '159920', '513100',
                        '513030', '513520', '518880', '162411'];

  function r20Of(arr) {
    if (!arr || arr.length < 21) return null;
    const a = arr[arr.length - 1], b = arr[arr.length - 21];
    return (b && isFinite(b)) ? (a / b - 1) * 100 : null;
  }

  function breadth(closeMap) {
    const items = [];
    BREADTH_CORE.forEach(function (c) {
      const v = r20Of((closeMap || {})[c]);
      if (v == null) return;
      items.push({ code: c, r20: r(v, 2), up: v > 0 });
    });
    if (!items.length) return null;
    const up = items.filter(function (x) { return x.up; }).length;
    return {
      n: items.length, up: up, down: items.length - up,
      pct: r(up / items.length * 100, 0),
      items: items,
    };
  }

  function riskOn(closeMap) {
    const avg = function (codes) {
      const v = [];
      codes.forEach(function (c) {
        const x = r20Of((closeMap || {})[c]);
        if (x != null) v.push(x);
      });
      return v.length ? v.reduce(function (a, b) { return a + b; }, 0) / v.length : null;
    };
    const a = avg(RISK_ASSETS), b = avg(SAFE_ASSETS);
    if (a == null || b == null) return null;
    const gap = a - b;
    return {
      risk: r(a, 2), safe: r(b, 2), gap: r(gap, 2),
      state: gap > 2 ? '风险偏好回升' : (gap < -2 ? '避险占优' : '中性'),
      // 用 0 轴分档：>5pp 强 risk-on，<-5pp 强 risk-off
      tier: gap > 5 ? 2 : (gap > 2 ? 1 : (gap < -5 ? -2 : (gap < -2 ? -1 : 0))),
    };
  }

  /* ---------- 7. 用实时价补今日 bar ----------
     内嵌序列的最后一天是数据日。若现在是交易日且行情时间晚于数据日，
     就用实时价追加一根（成交量缺失 → 用近 5 日均量代替，只影响量比一维）。
     非交易日/盘前不动 —— 宁可不更新，也不要编一根假 K 线。
  */
  function applyLive(sd, live, nowStr) {
    if (!sd || !sd.close || !live) return { sd: sd, applied: false, why: '无数据' };
    const today = nowStr || new Date().toISOString().slice(0, 10);
    const d = new Date();
    const wd = d.getDay();
    if (wd === 0 || wd === 6) return { sd: sd, applied: false, why: '周末非交易日' };
    if (sd.date >= today) return { sd: sd, applied: false, why: '数据日即今日' };

    const out = { close: {}, ohlcv: {}, dates: (sd.dates || []).slice(), date: today };
    Object.keys(sd.close).forEach(function (c) {
      const arr = sd.close[c].slice();
      const q = live[c];
      arr.push((q && q.price) ? +q.price : arr[arr.length - 1]);
      out.close[c] = arr;
    });
    Object.keys(sd.ohlcv || {}).forEach(function (c) {
      const arr = sd.ohlcv[c].map(function (x) { return x.slice(); });
      const q = live[c];
      if (q && q.price) {
        const vols = arr.slice(-5).map(function (x) { return x[4]; });
        const av = vols.reduce(function (a, b) { return a + b; }, 0) / (vols.length || 1);
        arr.push([q.open || q.price, q.high || q.price, q.low || q.price,
                  +q.price, Math.round(av)]);
      }
      out.ohlcv[c] = arr;
    });
    out.dates.push(today);
    return { sd: out, applied: true, why: '已用实时价补 ' + today };
  }

  function marketState(sd) {
    const o = (sd && sd.ohlcv) || {};
    const out = {};
    Object.keys(o).forEach(function (c) {
      if (!o[c] || o[c].length < 60) return;
      try {
        const ind = indicators(o[c], sd.dates);
        out[c] = { ind: ind, score: mktScore(ind) };
      } catch (e) { /* 单只算错不影响其它 */ }
    });
    return out;
  }

  return {
    indicators: indicators, mktScore: mktScore, regime: regime,
    adapt: adapt, rescore: rescore, applyLive: applyLive,
    marketState: marketState, volPct: volPct,
    breadth: breadth, riskOn: riskOn,
    REGIME_LABEL: REGIME_LABEL, REGIME_ORDER: REGIME_ORDER,
    BREADTH_CORE: BREADTH_CORE,
  };
})();
