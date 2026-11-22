# -*- coding: utf-8 -*-
"""
按资产类别重做「乖离区间 -> 未来收益」诊断。

上一版把 331 只混在一起算，掩盖了跨境类的独立规律。
本版按 subclass 分组，逐组检验：
  1. bias20 的实际分布（各组「跌 16%」到底有多罕见）
  2. 各组在自身阈值下的触发频率（每年几次）
  3. 各组「跌破各区间 -> 未来 10 日收益」（均值 + 胜率 + 样本数）
  4. 下跌分解：开盘跳空占多少、盘中占多少（跨境的关键差异）
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PARQ = os.path.join('data', 'etf_qfq_cifang.parquet')
FWD = 10          # 前瞻交易日
BIAS_W = 20       # 乖离窗口
MIN_N = 30        # 单元格最小样本数，低于此标注样本不足

# ---------- 分组 ----------
def group_of(sub, cls6):
    if sub in ('美股', '日本', '欧股'):
        return 'A_跨境-远洋(美日欧)'
    if sub in ('贵金属', '能化', '农产品', '其他'):
        return 'B_商品'
    if sub in ('港股', '中概', '新兴市场', '中东'):
        return 'C_跨境-近岸(港股中概)'
    if cls6 == '股票-股息红利':
        return 'D_红利低波'
    return 'E_A股境内'


def load():
    """必须走清洗层：次方原始数据有 116 根单日假跳变（-70%/+400%），
    不清洗的话 <-25% 那一格会被假暴跌撑成 +96%，整张表作废。"""
    import data_quality
    df = pd.read_parquet(PARQ)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(['code', 'date']).reset_index(drop=True)
    fixed, n_code, n_bar = 0, 0, 0
    out = []
    for code, g in df.groupby('code', sort=False):
        g = g.reset_index(drop=True)
        cols = [c for c in ('open', 'high', 'low', 'close') if c in g.columns]
        if not cols:
            continue
        f, hits = data_quality.repair_prices(g, jump_th=0.30)
        if hits:
            n_code += 1
            n_bar += len(hits)
        out.append(f)
    df = pd.concat(out, ignore_index=True)
    df = df.sort_values(['code', 'date']).reset_index(drop=True)
    print('[数据体检] 修正单日跳变：%d 只 / %d 根' % (n_code, n_bar))
    return df


def main():
    import json
    pool = json.load(open('data/fixed_pool.json', encoding='utf-8'))
    bmap = pool['bmap']; cmap = pool.get('cmap', {}); sc = pool.get('subclass', {})
    gmap = {c: group_of(sc.get(c, ''), cmap.get(c, '')) for c in pool['codes']}

    df = load()
    print('数据 %d 行 / %d 只标的 / %s ~ %s'
          % (len(df), df['code'].nunique(), df['date'].min().date(), df['date'].max().date()))
    df = df[df['code'].isin(gmap.keys())].copy()
    df['grp'] = df['code'].map(gmap)
    print('入池 %d 行 / %d 只' % (len(df), df['code'].nunique()))
    print()

    rows = []
    gaps = []
    for code, g in df.groupby('code', sort=False):
        g = g.reset_index(drop=True)
        n = len(g)
        if n < BIAS_W + FWD + 5:
            continue
        c = g['close'].to_numpy(float)
        o = g['open'].to_numpy(float) if 'open' in g.columns else None
        if o is not None:
            o = np.where(np.isfinite(o) * (o > 0), o, np.nan)
        ma = pd.Series(c).rolling(BIAS_W).mean().to_numpy()
        bias = (c / ma - 1.0) * 100.0
        fwd = np.full(n, np.nan)
        fwd[:-FWD] = c[FWD:] / c[:-FWD] - 1.0
        prev = np.concatenate([[np.nan], c[:-1]])
        if o is not None:
            gapr = o / prev - 1.0          # 开盘跳空
            intr = c / o - 1.0             # 盘中
        else:
            gapr = np.full(n, np.nan); intr = np.full(n, np.nan)
        grp = gmap[code]
        for i in range(BIAS_W, n - FWD):
            b = bias[i]
            if not np.isfinite(b):
                continue
            rows.append((grp, code, b, fwd[i]))
        # 下跌分解只用「大跌日」：单日跌幅 < -2%
        for i in range(BIAS_W, n):
            if not (np.isfinite(prev[i]) and prev[i] > 0):
                continue
            dr = c[i] / prev[i] - 1.0
            if dr <= -0.02:
                gaps.append((grp, code, dr, gapr[i], intr[i]))

    ob = pd.DataFrame(rows, columns=['grp', 'code', 'bias20', 'fwd10'])
    ob = ob[np.isfinite(ob['fwd10'])]
    print('观测 %d 条' % len(ob))
    print()

    # ---------- 1. bias20 分布 ----------
    print('=' * 96)
    print('【1】bias20 分布：各组「跌到多少」的实际概率')
    print('=' * 96)
    print('%-22s %6s %8s %8s %8s %8s %8s' % ('组', '只数', 'P1', 'P5', 'P10', '中位', '最差'))
    for grp, g in ob.groupby('grp'):
        b = g['bias20']
        print('%-22s %6d %8.2f %8.2f %8.2f %8.2f %8.2f'
              % (grp, g['code'].nunique(), b.quantile(.01), b.quantile(.05),
                 b.quantile(.10), b.median(), b.min()))
    print()

    # ---------- 2. 触发频率 ----------
    print('=' * 96)
    print('【2】各阈值下的触发频率（每年发生多少次「bmin5 有效」的单日机会，近似）')
    print('=' * 96)
    print('%-22s %8s %8s %8s %8s' % ('组', '<-5%', '<-11%', '<-16%', '<-20%'))
    for grp, g in ob.groupby('grp'):
        n_tot = len(g)
        yr = n_tot / 244.0      # 折算年数
        cells = []
        for th in (-5, -11, -16, -20):
            cnt = (g['bias20'] < th).sum()
            cells.append(cnt / yr if yr > 0 else 0)
        print('%-22s %8.2f %8.2f %8.2f %8.2f' % (grp, *cells))
    print()

    # ---------- 3. 波动区间 -> 前瞻收益 ----------
    bins = [(-99, -25), (-25, -20), (-20, -16), (-16, -12), (-12, -8), (-8, -4), (-4, 0), (0, 99)]
    labels = ['<-25', '-25~-20', '-20~-16', '-16~-12', '-12~-8', '-8~-4', '-4~0', '>=0']

    print('=' * 96)
    print('【3】跌破各乖离区间后，未来 %d 日平均收益（括号内为胜率 / 样本数）' % FWD)
    print('=' * 96)
    hdr = '%-22s' % '组' + ''.join('%14s' % l for l in labels)
    print(hdr)
    for grp, g in ob.groupby('grp'):
        line = '%-22s' % grp
        for lo, hi in bins:
            sel = g[(g['bias20'] >= lo) & (g['bias20'] < hi)]['fwd10']
            if len(sel) < MIN_N:
                line += '%14s' % ('n=%d' % len(sel))
            else:
                m = sel.mean() * 100
                w = (sel > 0).mean() * 100
                line += '%14s' % ('%+.2f%%/%d' % (m, len(sel)))
        print(line)
    print()
    print('（格式：平均收益%% / 样本数；样本 < %d 直接标 n=）' % MIN_N)
    print()

    # ---------- 3b. 只看各组自身阈值附近 ----------
    print('=' * 96)
    print('【3b】各组在「自身阈值」附近的表现（跨境是否真该用 -11）')
    print('=' * 96)
    checks = {
        'A_跨境-远洋(美日欧)': [-8, -11, -14, -16, -20],
        'C_跨境-近岸(港股中概)': [-11, -16, -20, -25],
        'E_A股境内': [-11, -16, -20, -25],
        'D_红利低波': [-5, -8, -11, -16],
        'B_商品': [-8, -11, -16, -20],
    }
    for grp, ths in checks.items():
        g = ob[ob['grp'] == grp]
        if len(g) == 0:
            continue
        print('  %s' % grp)
        for th in ths:
            sel = g[g['bias20'] < th]['fwd10']
            if len(sel) < MIN_N:
                print('    bias20 < %3d%%  n=%d（样本不足）' % (th, len(sel)))
                continue
            print('    bias20 < %3d%%  均值 %+6.2f%%  胜率 %5.1f%%  中位 %+6.2f%%  n=%d'
                  % (th, sel.mean() * 100, (sel > 0).mean() * 100,
                     sel.median() * 100, len(sel)))
        print()

    # ---------- 4. 下跌分解 ----------
    print('=' * 96)
    print('【4】大跌日（单日 <= -2%）的构成：开盘跳空 vs 盘中（跨境的核心差异）')
    print('=' * 96)
    gp = pd.DataFrame(gaps, columns=['grp', 'code', 'dr', 'gap', 'intr'])
    gp = gp[np.isfinite(gp['gap']) & np.isfinite(gp['intr'])]
    print('%-22s %8s %10s %10s %10s %10s' % ('组', '大跌日数', '总跌幅', '开盘跳空', '盘中', '跳空占比'))
    for grp, g in gp.groupby('grp'):
        tot = g['dr'].mean() * 100
        ga = g['gap'].mean() * 100
        it = g['intr'].mean() * 100
        share = ga / tot * 100 if abs(tot) > 1e-9 else 0
        print('%-22s %8d %9.2f%% %9.2f%% %9.2f%% %9.1f%%' % (grp, len(g), tot, ga, it, share))
    print()

    # ---------- 5. 隔夜跳空后的回归能力 ----------
    print('=' * 96)
    print('【5】「跳空型大跌」vs「盘中型大跌」的后续 %d 日收益（决定跨境该不该用更松阈值）' % FWD)
    print('=' * 96)
    # 对每个大跌日，找它在 ob 里的 fwd10
    fwd_map = {}
    for code, g in df.groupby('code', sort=False):
        g = g.reset_index(drop=True)
        c = g['close'].to_numpy(float)
        n = len(c)
        f = np.full(n, np.nan)
        f[:-FWD] = c[FWD:] / c[:-FWD] - 1.0
        fwd_map[code] = f
    recs = []
    for code, g in df.groupby('code', sort=False):
        g = g.reset_index(drop=True)
        n = len(g)
        if n < BIAS_W + FWD + 5:
            continue
        c = g['close'].to_numpy(float)
        o = g['open'].to_numpy(float) if 'open' in g.columns else None
        if o is not None:
            o = np.where(np.isfinite(o) * (o > 0), o, np.nan)
        if o is None:
            continue
        prev = np.concatenate([[np.nan], c[:-1]])
        f = fwd_map[code]
        grp = gmap[code]
        for i in range(BIAS_W, n - FWD):
            if not (np.isfinite(prev[i]) and prev[i] > 0):
                continue
            dr = c[i] / prev[i] - 1.0
            if dr > -0.02:
                continue
            gapr = o[i] / prev[i] - 1.0
            intr = c[i] / o[i] - 1.0
            # 跳空为主（跳空跌幅占总跌幅 >= 60%）vs 盘中为主
            kind = '跳空型' if (gapr < 0 and abs(gapr) >= 0.6 * abs(dr)) else '盘中型'
            recs.append((grp, kind, dr, gapr, intr, f[i]))
    kd = pd.DataFrame(recs, columns=['grp', 'kind', 'dr', 'gap', 'intr', 'fwd10'])
    kd = kd[np.isfinite(kd['fwd10'])]
    for grp in sorted(kd['grp'].unique()):
        g = kd[kd['grp'] == grp]
        line = '  %-22s' % grp
        for kind in ('跳空型', '盘中型'):
            s = g[g['kind'] == kind]['fwd10']
            if len(s) < MIN_N:
                line += '  %s n=%d（不足）' % (kind, len(s))
            else:
                line += '  %s %+.2f%% 胜率%.0f%% n=%d' % (
                    kind, s.mean() * 100, (s > 0).mean() * 100, len(s))
        print(line)
    print()

    # ---------- 6. 输出明细 ----------
    os.makedirs('回测输出', exist_ok=True)
    ob.to_csv('回测输出/diag_bias_by_class.csv', index=False, encoding='utf-8-sig')
    print('已写出 回测输出/diag_bias_by_class.csv（%d 条）' % len(ob))


if __name__ == '__main__':
    main()
