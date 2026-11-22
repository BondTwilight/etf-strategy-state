# -*- coding: utf-8 -*-
"""标定：14:25 / 14:35 / 14:45 / 14:55 / 14:57 与收盘价（15:00 集合竞价）的偏差。

用途：判断「14:25 出信号」是否可行——如果 14:25 的价格与收盘差得太多，
信号会大量失真；如果差异在噪声内，就可以提前 20 分钟出信号。

同时用 iopv 列检查「价格 vs 盘中净值」的偏离（可算精确溢价率，无 T-1 滞后）。
"""
import os
import sys
import json
import time
import urllib.parse
import urllib.request
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cifang_api as cf

OUT = 'data/minute_calib_1425.csv'
DAYS = 120                      # 回看交易日
BLOCK = 10                      # 每次请求的天数（跨日会返回整天，太大易 400）
TIMES = ['14:25', '14:35', '14:45', '14:55', '14:57', '15:00']

CODES = ['510300', '510500', '159915', '588000', '512480', '512690', '515030',
         '513050', '513060', '159920', '513100', '513500', '159509',
         '513520', '513030', '518880', '159985', '159981',
         '512890', '515080', '159967', '563300']


def call_min(symbol, s, e):
    u = cf.BASE + '/fund/hist_min'
    q = urllib.parse.urlencode({'symbol': symbol, 'start_time': s, 'end_time': e})
    req = urllib.request.Request(u + '?' + q,
                                 headers={'x-api-key': cf.API_KEY,
                                          'User-Agent': 'Mozilla/5.0'})
    b = json.loads(urllib.request.urlopen(req, timeout=30).read().decode('utf-8'))
    if b.get('code') != 0:
        raise RuntimeError(b.get('message'))
    return b.get('data') or {}


def trade_days():
    """取可用交易日：用日线 parquet 的日期序列。"""
    px = pd.read_parquet('data/etf_qfq_cifang.parquet', columns=['date'])
    d = sorted(set(pd.to_datetime(px['date']).dt.strftime('%Y-%m-%d')))
    return d[-DAYS:]


def main():
    days = trade_days()
    print('标定窗口 %s ~ %s（%d 个交易日）' % (days[0], days[-1], len(days)))
    print('标的 %d 只 ｜ 时点 %s' % (len(CODES), TIMES))

    rows = []
    t0 = time.time()
    seen = {}
    for bi in range(0, len(days), BLOCK):
        blk = days[bi:bi + BLOCK]
        s = blk[0] + ' 14:20:00'
        e = blk[-1] + ' 15:00:00'
        got = {}
        for c in CODES:
            try:
                d = call_min(c, s, e)
            except Exception as ex:
                print('  %s 失败: %s' % (c, str(ex)[:60]))
                continue
            for code, arr in d.items():
                for r in arr:
                    ts = str(r[0])
                    day, tm = ts[:10], ts[11:16]
                    got.setdefault(code, {}).setdefault(day, {})[tm] = r
        # 抽取各时点
        n_ok = 0
        for code, per_day in got.items():
            for day, tmap in per_day.items():
                if '15:00' not in tmap:
                    continue
                close = float(tmap['15:00'][2])
                if not (close > 0):
                    continue
                rec = {'code': code, 'date': day, 'close': close,
                       'iopv_close': float(tmap['15:00'][8]) if len(tmap['15:00']) > 8 else np.nan}
                for tt in TIMES[:-1]:
                    if tt in tmap:
                        rec[tt] = float(tmap[tt][2])
                        rec['vol_' + tt] = float(tmap[tt][6])
                    else:
                        rec[tt] = np.nan
                        rec['vol_' + tt] = np.nan
                rows.append(rec)
                n_ok += 1
        print('  块 %d/%d  %s~%s  累计 %d 条  %.0fs'
              % (bi // BLOCK + 1, (len(days) + BLOCK - 1) // BLOCK,
                 blk[0], blk[-1], len(rows), time.time() - t0), flush=True)

    df = pd.DataFrame(rows)
    if df.empty:
        print('无数据')
        return
    df.to_csv(OUT, index=False, encoding='utf-8-sig')
    print('\n已写出 %s（%d 行，%d 只）' % (OUT, len(df), df['code'].nunique()))
    print()

    print('=' * 100)
    print('【1】各时点相对「15:00 收盘价」的偏差（同时点截面统计）')
    print('=' * 100)
    print('%-8s %9s %10s %10s %10s %10s %9s'
          % ('时点', '样本', '均值', '标准差', '|偏差|中位', '90%分位', '最大'))
    for tt in TIMES[:-1]:
        v = (df[tt] / df['close'] - 1.0).dropna()
        if len(v) == 0:
            continue
        print('%-8s %9d %9.3f%% %9.3f%% %9.3f%% %9.3f%% %8.2f%%'
              % (tt, len(v), v.mean() * 100, v.std() * 100,
                 v.abs().median() * 100, v.abs().quantile(.90) * 100,
                 v.abs().max() * 100))
    print()

    # 14:25 -> 收盘 的漂移，按标的分解
    print('=' * 100)
    print('【2】14:25 → 收盘 的漂移，按标的（σ 越大 = 提前 20 分钟出信号越不可靠）')
    print('=' * 100)
    print('%-8s %8s %9s %10s %10s %8s'
          % ('code', '样本', '均值', '标准差', '90%分位', '零成交天数占比'))
    for code, g in df.groupby('code'):
        v = (g['14:25'] / g['close'] - 1.0).dropna()
        if len(v) < 10:
            continue
        zero = (g['vol_14:25'].fillna(0) == 0).mean() * 100
        print('%-8s %8d %8.3f%% %9.3f%% %9.3f%% %7.0f%%'
              % (code, len(v), v.mean() * 100, v.std() * 100,
                 v.abs().quantile(.90) * 100, zero))
    print()

    # 价格 vs iopv
    print('=' * 100)
    print('【3】收盘价 vs IOPV（精确溢价率，无 T-1 滞后）')
    print('=' * 100)
    df['prem'] = df['close'] / df['iopv_close'] - 1.0
    ok = df[np.isfinite(df['prem'])]
    print('  可用 %d / %d 行' % (len(ok), len(df)))
    print('%-8s %8s %10s %10s %10s %10s'
          % ('code', '样本', 'P5', '中位', 'P95', 'P95-P5幅度'))
    for code, g in ok.groupby('code'):
        p = g['prem']
        if len(p) < 10:
            continue
        print('%-8s %8d %9.3f%% %9.3f%% %9.3f%% %9.2f%%'
              % (code, len(p), p.quantile(.05) * 100, p.median() * 100,
                 p.quantile(.95) * 100,
                 (p.quantile(.95) - p.quantile(.05)) * 100))
    print()
    print('注：iopv 为盘中净值估算，收盘价/iopv-1 即当日溢价率。')
    print('    与 fund_nav 相比无 T-1 滞后，也不受份额折算影响。')


if __name__ == '__main__':
    main()
