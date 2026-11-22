# -*- coding: utf-8 -*-
"""
cifang_quote.py —— 次方量化「前复权日线」实盘适配层（2026-10-20 新增）

为什么需要这一层：
  实盘链路原本靠 web_quote 打腾讯 ifzq 的 *前复权* 日线。实测腾讯该接口在批量
  拉取后会被限流返回 HTTP 501，而原实现会**静默**退化到新浪「不复权」——作者自己
  在注释里写明"必须前复权，否则有分红/份额折算的 ETF 乖离率会严重失真"。
  也就是说：一旦被限流，信号数值是错的，但输出看起来完全正常。

本层职责：
  只接管「历史日线」这一段，用次方 /api/fund/hist_em 的 qfq 数据替换腾讯。
  **实时价不接管**：实时价本身不需要复权，继续走腾讯/新浪 qt 接口（那条没被 501）。

关键工程约束：
  1. 次方限制 50 只/请求。381 只 = 8 个请求，绝不能逐只发（381 请求会撞 60次/分）。
  2. 每个交易日**只拉一次**：结果落盘为 data/kline_cache_cifang_YYYY-MM-DD.parquet，
     同日重跑直接复用（0 API 消耗）。这条同时防住了"定时任务重复启动把接口打满"。
  3. 任何异常都返回空 DataFrame，交由 tdx_api 走原有降级链，绝不抛异常中断信号。

⚠️ 本文件不含 Key，Key 统一在 cifang_api.py 里，勿外传。
"""
import os
import time
import datetime as _dt

import pandas as pd

import cifang_api

KLINE_COLS = ['date', 'open', 'high', 'low', 'close', 'vol', 'amount']

# 进程内缓存：{code: DataFrame}，一次运行内所有调用共享
_MEM = {}
_PREFETCHED = [False]
_STATS = {'calls': 0, 'codes': 0, 'from_cache': 0, 'failed': 0}


def _cache_path(day=None):
    day = day or _dt.date.today().strftime('%Y-%m-%d')
    return os.path.join('data', 'kline_cache_cifang_%s.parquet' % day)


def _prune_old_caches(keep=15):
    """只保留最近 keep 个交易日的日缓存，避免目录无限膨胀（约 1MB/日）。"""
    try:
        d = 'data'
        if not os.path.isdir(d):
            return 0
        fs = sorted([f for f in os.listdir(d)
                     if f.startswith('kline_cache_cifang_') and f.endswith('.parquet')])
        old = fs[:-keep] if len(fs) > keep else []
        for f in old:
            try:
                os.remove(os.path.join(d, f))
            except Exception:
                pass
        return len(old)
    except Exception:
        return 0


def _to_std(df):
    """次方列名 → 项目标准列名，并按日期升序。"""
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=KLINE_COLS)
    d = df.rename(columns={'volume': 'vol'}).copy()
    for c in KLINE_COLS:
        if c not in d.columns:
            d[c] = None
    d = d[KLINE_COLS]
    d['date'] = d['date'].astype(str).str[:10]
    d = d.dropna(subset=['close'])
    d = d.sort_values('date').reset_index(drop=True)
    return d


def _load_day_cache():
    p = _cache_path()
    if not os.path.exists(p):
        return 0
    try:
        big = pd.read_parquet(p)
    except Exception:
        return 0
    n = 0
    for code, g in big.groupby('code'):
        _MEM[str(code)] = _to_std(g.drop(columns=['code']))
        n += 1
    _STATS['from_cache'] = n
    return n


def _save_day_cache():
    frames = []
    for code, df in _MEM.items():
        if df is None or len(df) == 0:
            continue
        d = df.copy()
        d['code'] = code
        frames.append(d)
    if not frames:
        return
    p = _cache_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        pd.concat(frames, ignore_index=True).to_parquet(p, index=False)
    except Exception as e:
        print('[次方行情] 日缓存写入失败（不影响本次信号）: %s' % e)


def prefetch_batch(codes, count=60, end_date=None, force=False):
    """批量预取前复权日线。返回 {code: DataFrame}，与 web_quote 批量接口同构。

    count  —— 需要多少根交易日 K 线
    end_date —— 截止日（默认今天）
    force  —— 忽略同日缓存，强制重拉
    """
    t0 = time.time()
    codes = [str(c) for c in codes]

    if not force:
        # ① 同日落盘缓存优先（同日重跑 0 API 消耗）
        if _load_day_cache() > 0:
            hit = sum(1 for c in codes if c in _MEM)
            if hit >= len(codes) * 0.95:
                print('[次方行情] 复用当日缓存 %d/%d 只，跳过 API（耗时 %.1fs）'
                      % (hit, len(codes), time.time() - t0))
                return {c: _MEM[c] for c in codes if c in _MEM}

    # ② 计算起始日：count 根交易日 ≈ count*1.45 自然日，再留 30 天余量
    end = end_date or _dt.date.today().strftime('%Y-%m-%d')
    days_back = int(count * 1.45) + 30
    start = (_dt.date.fromisoformat(str(end)[:10])
             - _dt.timedelta(days=days_back)).strftime('%Y-%m-%d')

    n_batch = (len(codes) + cifang_api.MAX_SYMBOLS_PER_CALL - 1) // cifang_api.MAX_SYMBOLS_PER_CALL
    print('[次方行情] 拉取 %d 只前复权日线 %s~%s（%d 批 / %d 请求上限）...'
          % (len(codes), start, end, n_batch, n_batch))

    try:
        raw = cifang_api.hist_em(codes, start, end, adjust='qfq')
    except Exception as e:
        print('[次方行情] ❌ 批量拉取失败，回退原链路: %s' % e)
        _STATS['failed'] = len(codes)
        return {}

    _STATS['calls'] += n_batch
    for code, df in raw.items():
        d = _to_std(df)
        if str(end_date or '') and len(d):
            d = d[d['date'] <= str(end_date)[:10]].reset_index(drop=True)
        if len(d):
            _MEM[str(code)] = d
    got = sum(1 for c in codes if c in _MEM)
    _STATS['codes'] = got
    print('[次方行情] 返回 %d/%d 只，耗时 %.1fs%s'
          % (got, len(codes), time.time() - t0,
             '' if got >= len(codes) * 0.95 else '  ⚠️ 覆盖不足，缺失部分将回退原链路'))

    _PREFETCHED[0] = True
    _save_day_cache()
    _prune_old_caches()
    return {c: _MEM[c] for c in codes if c in _MEM}


def get_daily_kline(code, count=120, end_date=None):
    """单只日线（供 tdx_api.get_daily_kline 调用）。命中内存/日缓存则零网络。"""
    code = str(code)
    if code in _MEM and len(_MEM[code]):
        d = _MEM[code]
        if end_date:
            d = d[d['date'] <= str(end_date)[:10]]
        return d.tail(count).reset_index(drop=True)

    # 未预取到的个别标的：单只补拉一次（每个代码最多一次）
    end = end_date or _dt.date.today().strftime('%Y-%m-%d')
    start = (_dt.date.fromisoformat(str(end)[:10])
             - _dt.timedelta(days=int(count * 1.45) + 30)).strftime('%Y-%m-%d')
    try:
        raw = cifang_api.hist_em([code], start, end, adjust='qfq')
    except Exception:
        return pd.DataFrame(columns=KLINE_COLS)
    if code not in raw:
        return pd.DataFrame(columns=KLINE_COLS)
    d = _to_std(raw[code])
    _MEM[code] = d
    if len(d) == 0:
        return d
    return d.tail(count).reset_index(drop=True)


def stats():
    return dict(_STATS)


def clear_cache():
    """每轮运行开始时调用，清掉进程内缓存（保留当日落盘缓存）。"""
    _MEM.clear()
    _PREFETCHED[0] = False
    for k in _STATS:
        _STATS[k] = 0


if __name__ == '__main__':
    import json
    pool = json.load(open('data/fixed_pool.json', encoding='utf-8'))['codes']
    d = prefetch_batch(pool, count=60, force='--force' in __import__('sys').argv)
    lens = sorted(len(v) for v in d.values())
    print('只数=%d 行数 min/median/max=%d/%d/%d' % (
        len(d), lens[0], lens[len(lens) // 2], lens[-1]))
