/* ============================================================================
   cf_api.js —— 浏览器端次方量化 API 客户端
   ----------------------------------------------------------------------------
   先纠正一个我自己犯的错：
     上一轮我用 urllib 不带 Origin 头测 CORS，看到没有 ACAO 就断言"次方不支持跨域"，
     还把"CORS 是硬约束"写进了文档。这是错的 —— 浏览器发请求一定会带 Origin，
     服务端也会回显。实测预检响应：

       Access-Control-Allow-Origin:  <回显请求的 Origin，连 null（file://）都放行>
       Access-Control-Allow-Headers: x-api-key          ← 自定义头放行
       Access-Control-Allow-Methods: DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT
       Access-Control-Max-Age:       600

   所以浏览器可以直连，拿到腾讯拿不到的三样东西：
     ① IOPV                → 溢价率（腾讯完全没有这个字段）
     ② 官方持仓与绩效        → /api/strategy/my-running（不用等本机刷新）
     ③ 每天固定时点的历史价  → /api/fund/hist_intraday（14:30 / 14:45，回测就是靠它）

   关于 Key
     它会出现在页面源码里，这是直连的代价，用户已明确授权。
     风险边界：这个账号 trading/list 为空（未开通自动交易），Key 只能读行情，
     最坏情况是别人蹭配额（60 次/分钟限流），不能下单。
   ============================================================================ */
const CF = (function () {
  'use strict';

  const BASE = 'https://www.cifangquant.com/api';
  let KEY = '';
  let STATS = { n: 0, fail: 0, lastErr: '' };

  function setKey(k) { KEY = (k || '').trim(); }
  function hasKey() { return !!KEY; }

  async function req(path, params, method, body) {
    const qs = params ? ('?' + new URLSearchParams(params).toString()) : '';
    const opt = { method: method || 'GET', cache: 'no-store', headers: { 'x-api-key': KEY } };
    if (body) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    STATS.n++;
    const r = await fetch(BASE + path + qs, opt);
    if (!r.ok) { STATS.fail++; STATS.lastErr = 'HTTP ' + r.status; throw new Error('HTTP ' + r.status); }
    const j = await r.json();
    if (j.code !== 0) { STATS.fail++; STATS.lastErr = j.message || ('code ' + j.code); throw new Error(STATS.lastErr); }
    return j.data;
  }

  /* 实时快照：last / iopv / 五档 / 成交额 / 涨跌停 */
  function spot(codes) {
    const arr = [].concat(codes);
    // 单次最多 50 只，分片
    const chunks = [];
    for (let i = 0; i < arr.length; i += 45) chunks.push(arr.slice(i, i + 45));
    return Promise.all(chunks.map(function (c) {
      return req('/fund/spot', { symbol: c.join(',') }).catch(function () { return {}; });
    })).then(function (parts) {
      const out = {};
      parts.forEach(function (p) { Object.assign(out, p || {}); });
      return out;
    });
  }

  /* 我发布的运行中策略：官方持仓 + 官方绩效 */
  function myRunning() { return req('/strategy/my-running'); }

  /* 每天固定时点的累计日线（SVIP）。time='14:30' */
  function intraday(codes, startDate, endDate, time, adjust) {
    return req('/fund/hist_intraday', {
      symbol: [].concat(codes).join(','),
      start_date: startDate, end_date: endDate,
      time: time || '14:30', adjust: adjust || 'qfq',
    });
  }

  /* 历史日线（含 IOPV） */
  function histEm(codes, startDate, endDate, adjust) {
    return req('/fund/hist_em', {
      symbol: [].concat(codes).join(','),
      start_date: startDate, end_date: endDate,
      adjust: adjust || 'qfq',
    });
  }

  /* 场内基金排行（1715 只） */
  function exchangeRank(sortBy, limit) {
    return req('/fund/exchange_rank', { sort_by: sortBy || '1yzf', sort_order: 'desc', limit: limit || 300 });
  }

  /* 溢价率：价格 ÷ IOPV − 1。必须用不复权价，否则折算日会失真 */
  function premium(q) {
    if (!q || q.iopv == null || !q.iopv || q.last == null) return null;
    return (q.last / q.iopv - 1) * 100;
  }

  function stats() { return { n: STATS.n, fail: STATS.fail, lastErr: STATS.lastErr }; }

  return {
    setKey: setKey, hasKey: hasKey, stats: stats,
    spot: spot, myRunning: myRunning, intraday: intraday,
    histEm: histEm, exchangeRank: exchangeRank, premium: premium,
  };
})();
