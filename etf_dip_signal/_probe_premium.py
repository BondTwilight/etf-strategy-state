# -*- coding: utf-8 -*-
"""跨境 ETF 溢价率探测：价格乖离里有多少来自溢价崩塌。

逻辑：溢价率 = 收盘价 / 单位净值 - 1
      价格乖离 ≈ 净值乖离 + 溢价率变化
若某只跨境 ETF 的「超跌」主要由溢价率下降贡献，则标的本身没跌，
均值回归的理由不成立（甚至可能是溢价继续收敛的下行风险）。
"""
import os
import sys
import json
import time
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TOKEN = '405585c460d0d7d686644d58e138ea06d34915cee14e9c8914e5ea64'
URL = 'https://fast.xiaodefa.cn'


def pro_api():
    import tushare as ts
    ts.set_token(TOKEN)
    pro = ts.pro_api()
    pro._DataApi__http_url = URL
    return pro


def main():
    d = json.load(open('data/fixed_pool.json', encoding='utf-8'))
    cmap = d.get('cmap', {}); sc = d.get('subclass', {}); bmap = d['bmap']
    nm = d.get('name', {})
    cross = [c for c in d['codes'] if cmap.get(c) == '跨境']
    print('跨境标的 %d 只' % len(cross))

    pro = pro_api()
    ok, bad, rows = 0, 0, []
    t0 = time.time()
    for i, c in enumerate(cross):
        suffix = '.SH' if c.startswith('5') else '.SZ'
        try:
            nv = pro.fund_nav(ts_code=c + suffix, start_date='20210101',
                              end_date='20261020')
        except Exception as e:
            bad += 1
            continue
        if nv is None or len(nv) == 0:
            bad += 1
            continue
        nv = nv[['nav_date', 'unit_nav']].copy()
        nv['nav_date'] = pd.to_datetime(nv['nav_date'])
        nv['unit_nav'] = pd.to_numeric(nv['unit_nav'], errors='coerce')
        nv = nv.dropna().sort_values('nav_date')
        if len(nv) < 100:
            bad += 1
            continue
        nv['code'] = c
        rows.append(nv)
        ok += 1
        if (i + 1) % 20 == 0:
            print('  ... %d/%d  用时 %.0fs' % (i + 1, len(cross), time.time() - t0),
                  flush=True)
    print('成功 %d 只 / 失败 %d 只 / 用时 %.0fs' % (ok, bad, time.time() - t0))
    if not rows:
        print('无净值数据，无法计算溢价率')
        return
    nav = pd.concat(rows, ignore_index=True)
    nav.to_parquet('data/etf_nav_cifang.parquet', index=False)
    print('已缓存 data/etf_nav_cifang.parquet（%d 行）' % len(nav))

    # 与价格对齐
    px = pd.read_parquet('data/etf_qfq_cifang.parquet',
                         columns=['code', 'date', 'close'])
    px['date'] = pd.to_datetime(px['date'])
    px = px[px['code'].isin(nav['code'].unique())]
    # ★ 前复权价不能直接除以净值（复权会缩放绝对价格），需用不复权价
    #   次方只给了 qfq，所以这里用「溢价率的相对变化」而非绝对水平
    j = nav.merge(px, left_on=['code', 'nav_date'], right_on=['code', 'date'],
                  how='inner')
    print('价-净值对齐行数 %d' % len(j))
    if len(j) == 0:
        print('对齐失败')
        return

    # 用比例法消除复权缩放：对每只，溢价率 = close / nav * k，
    # k 取该只全样本中位数归一（即只看溢价率的相对变化）
    j['raw_ratio'] = j['close'] / j['unit_nav']
    med = j.groupby('code')['raw_ratio'].median().rename('med')
    j = j.merge(med, on='code')
    j['prem_idx'] = j['raw_ratio'] / j['med']      # 相对溢价指数，1.0 = 常态

    print()
    print('=' * 96)
    print('【1】各组「相对溢价指数」的分布（1.0 = 该只历史常态）')
    print('=' * 96)
    j['grp'] = j['code'].map(lambda c: '远洋' if sc.get(c) in ('美股', '日本', '欧股')
                             else ('近岸' if sc.get(c) in ('港股', '中概', '新兴市场', '中东')
                                   else '其他跨境'))
    print('%-10s %8s %10s %10s %10s %10s' % ('组', '只数', 'P5', 'P50', 'P95', 'P5~P95幅度'))
    for g, gg in j.groupby('grp'):
        v = gg['prem_idx']
        print('%-10s %8d %10.4f %10.4f %10.4f %9.2f%%'
              % (g, gg['code'].nunique(), v.quantile(.05), v.median(),
                 v.quantile(.95), (v.quantile(.95) - v.quantile(.05)) * 100))
    print()

    # 乖离率
    print('=' * 96)
    print('【2】触发阈值当日，溢价指数处于什么位置（越低=溢价越薄）')
    print('=' * 96)
    out = []
    for c, gg in j.groupby('code'):
        gg = gg.sort_values('nav_date').reset_index(drop=True)
        s = pd.Series(gg['close'].to_numpy(float))
        ma20 = s.rolling(20).mean()
        bias = (s / ma20 - 1.0) * 100.0
        gg['bias20'] = bias
        th = bmap.get(c, -16)
        hit = gg[gg['bias20'] < th]
        if len(hit) >= 5:
            out.append((c, nm.get(c, ''), th, len(hit),
                        hit['prem_idx'].median(), gg['prem_idx'].median(),
                        hit['prem_idx'].quantile(.5) - gg['prem_idx'].median()))
    if out:
        o = pd.DataFrame(out, columns=['code', 'name', 'th', 'n', 'prem_at_hit',
                                       'prem_all', 'delta'])
        print('%-8s %-22s %5s %5s %11s %11s %10s'
              % ('code', 'name', '阈值', '次数', '触发时溢价', '常态溢价', '差'))
        for _, r in o.sort_values('delta').iterrows():
            print('%-8s %-22s %5d %5d %11.4f %11.4f %+9.2f%%'
                  % (r['code'], str(r['name'])[:20], r['th'], r['n'],
                     r['prem_at_hit'], r['prem_all'], r['delta'] * 100))
        print()
        print('  触发时溢价低于常态的标的数: %d / %d'
              % ((o['delta'] < 0).sum(), len(o)))
        print('  溢价差中位数: %+.2f%%' % (o['delta'].median() * 100))
        o.to_csv('回测输出/premium_at_trigger.csv', index=False, encoding='utf-8-sig')
        print('  已写出 回测输出/premium_at_trigger.csv')
    else:
        print('  可算标的不足')


if __name__ == '__main__':
    main()
