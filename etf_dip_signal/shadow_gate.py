# -*- coding: utf-8 -*-
"""
shadow_gate.py —— 天基营「仓位调节」影子验证器（2026-10-22 新增）

为什么需要它：
  天基营 API 只开放**最近 30 个交易日**，历史日期一律 404（已实测 2020/2022/2024/2025
  四个日期全部 404，`recent?days=365` 也只返回 30 条）。也就是说：
  **「天基营做闸门到底有没有用」这个问题，现在无法回测，只能向前积累数据。**

它做什么：
  每天跑完信号后，把「当日天基营状态 + 当日抄底候选 + 实际动作」落一行日志。
  之后任何时点都能回答两个问题：
    ① 天基营=空仓 的日子里，抄底候选的后续 10 日收益是否明显更差？
    ② 若按「空仓日仓位减半」执行，累计收益/回撤会差多少？

判定标准必须**事先写死**，否则事后一定会找理由：
  · 样本 ≥ 60 个交易日（约 3 个月）
  · 若「空仓日候选 10 日胜率」比「做多日」低 < 10pp ⇒ 闸门无价值，否决
  · 若低 ≥ 10pp 且两侧样本各 ≥ 20 ⇒ 仓位调节有依据，可进入回测
"""
import csv
import json
import os

import pandas as pd

LOG = os.path.join('data', 'shadow_log.csv')
FIELDS = ['date', 'tj_signal', 'tj_longCycle', 'tj_midStrength', 'tj_shortBottom',
          'n_cand', 'top_code', 'top_name', 'top_bias50', 'top_bias20',
          'action', 'hold_code', 'hold_px',
          'px_512100', 'px_563300', 'px_hold']


def _tj_fields(ext):
    """从 generate_signal 的 external_signal(dict) 提取信号，并补充原始字段。"""
    if not isinstance(ext, dict):
        return ('未知', '', '', '')
    sig = ext.get('signal') or '未知'
    sig_date = ext.get('date') or ext.get('today')
    lc = ms = sb = ''
    if sig_date:
        try:
            import engine
            row = engine._fetch_signal_by_date(str(sig_date)[:10]) or {}
            lc = row.get('longCycle', '')
            ms = row.get('midStrength', '')
            sb = row.get('shortBottom', '')
        except Exception:
            pass
    return (sig, lc, ms, sb)


def record(res):
    """每个交易日调用一次，追加一行。任何异常都不得影响主流程。"""
    if not res or not res.get('is_trade_day'):
        return None
    cands = res.get('candidates') or []
    top = cands[0] if cands else {}
    acts = res.get('trade_actions') or []
    act_by_code = {a.get('code'): a for a in acts if isinstance(a, dict)}
    hold = (res.get('final_positions') or {})
    hold_code = next(iter(hold.keys()), '') if isinstance(hold, dict) else ''
    hold_px = ''
    if isinstance(hold, dict) and hold_code:
        hold_px = (hold.get(hold_code) or {}).get('avg_cost', '') or ''

    sig, lc, ms, sb = _tj_fields(res.get('external_signal'))
    action = 'none'
    if top and top.get('code') in act_by_code:
        action = 'buy'
    elif acts:
        action = 'sell'

    row = {
        'date': res.get('date', ''),
        'tj_signal': sig,
        'tj_longCycle': lc,
        'tj_midStrength': ms,
        'tj_shortBottom': sb,
        'n_cand': len(cands),
        'top_code': top.get('code', ''),
        'top_name': top.get('name', ''),
        'top_bias50': round(float(top.get('bias50', 0) or 0), 4) if top else '',
        'top_bias20': round(float(top.get('bias20', 0) or 0), 4) if top else '',
        'action': action,
        'hold_code': hold_code,
        'hold_px': hold_px,
    }

    # ★ 记录两条线各自的收盘价，供「纸面并行」计算净值
    #   线A（抄底）= 持仓标的的收盘价；线B（天基营）= 中证1000ETF 512100
    try:
        import tdx_api
        watch = [c for c in {hold_code, '512100', str(getattr(__import__('config'), 'EXTERNAL_TARGET_CODE', '563300'))} if c]
        rt = tdx_api.get_realtime(watch)
        pm = dict(zip(rt['code'], rt['price'])) if len(rt) else {}
        row['px_512100'] = pm.get('512100', '')
        row['px_563300'] = pm.get(str(getattr(__import__('config'), 'EXTERNAL_TARGET_CODE', '563300')), '')
        row['px_hold'] = pm.get(hold_code, '') if hold_code else ''
    except Exception:
        row['px_512100'] = row['px_563300'] = row['px_hold'] = ''

    os.makedirs('data', exist_ok=True)
    new = not os.path.exists(LOG)
    with open(LOG, 'a', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    return row


def report(cache='data/etf_qfq_cifang.parquet'):
    """用缓存行情给历史记录补上后续 5/10/20 日收益，按天基营状态分组统计。"""
    if not os.path.exists(LOG):
        print('尚无影子记录：data/shadow_log.csv 不存在')
        return
    df = pd.read_csv(LOG, encoding='utf-8-sig', dtype=str)
    if len(df) == 0:
        print('影子日志为空')
        return
    print('影子记录 %d 天（%s ~ %s）' % (len(df), df['date'].iloc[0], df['date'].iloc[-1]))

    if not os.path.exists(cache):
        print('无行情缓存，跳过收益回填')
        return
    big = pd.read_parquet(cache)
    px = {c: g.set_index('date')['close'].astype(float).sort_index()
          for c, g in big.groupby('code')}

    rows = []
    for _, r in df.iterrows():
        code = r['top_code']
        if not code or code not in px:
            continue
        s = px[code]
        idx = s.index[s.index >= r['date']]
        if len(idx) == 0:
            continue
        base = s.loc[idx[0]]
        rec = {'date': r['date'], 'tj': r['tj_signal'], 'code': code}
        for n in (5, 10, 20):
            if len(idx) > n:
                rec['r%d' % n] = s.loc[idx[n]] / base - 1
            else:
                rec['r%d' % n] = None
        rows.append(rec)

    R = pd.DataFrame(rows)
    if len(R) == 0:
        print('无可回填样本')
        return
    print('\n可回填样本 %d 个（需该标的在记录日之后仍有行情）' % len(R))
    g = R.groupby('tj')
    print('\n  %-8s %6s %12s %12s %10s' % ('天基营', '样本', '5日均值', '10日均值', '10日胜率'))
    for k, sub in g:
        c10 = sub['r10'].dropna()
        print('  %-8s %6d %11.2f%% %11.2f%% %9s' % (
            k, len(sub), sub['r5'].dropna().mean() * 100 if len(sub['r5'].dropna()) else float('nan'),
            c10.mean() * 100 if len(c10) else float('nan'),
            ('%.1f%%' % ((c10 > 0).mean() * 100)) if len(c10) else 'n/a'))
    print('\n⚠️ 样本 < 60 天时上述差异不具统计意义，仅作方法演示。')


def paper_report(cash_yield=0.025):
    """纸面并行净值：线A=抄底（按持仓标的日收益），线B=天基营（512100 日收益，空仓期计息）

    口径说明（v1，够用但不完美）：
      · 线A 用「持仓标的收盘价」日变动近似当日收益；调仓当日的滑点/手续未计
      · 线B 严格按 newDuokong1：做多日吃 512100 收益，空仓日按 cash_yield/252 计息
      · 两线均从首条记录起算，初始净值 1.000
    """
    if not os.path.exists(LOG):
        print('尚无影子记录')
        return
    df = pd.read_csv(LOG, encoding='utf-8-sig', dtype=str)
    if len(df) < 2:
        print('影子记录仅 %d 条，至少需 2 个交易日才能算净值' % len(df))
        return
    df = df.reset_index(drop=True)
    dr = cash_yield / 252.0
    na = nb = 1.0
    rows = []
    for i in range(1, len(df)):
        p, c = df.iloc[i - 1], df.iloc[i]
        # 线A
        ra = dr
        try:
            if c['hold_code'] and c['hold_code'] == p['hold_code'] \
                    and float(c['px_hold']) > 0 and float(p['px_hold']) > 0:
                ra = float(c['px_hold']) / float(p['px_hold']) - 1
        except Exception:
            pass
        # 线B
        rb = dr
        try:
            if p['tj_signal'] == 'long' and float(c['px_512100']) > 0 and float(p['px_512100']) > 0:
                rb = float(c['px_512100']) / float(p['px_512100']) - 1
        except Exception:
            pass
        na *= (1 + ra)
        nb *= (1 + rb)
        rows.append({'date': c['date'], 'A': na, 'B': nb,
                     'A_ret': ra, 'B_ret': rb, 'tj': c['tj_signal']})
    R = pd.DataFrame(rows)
    print('纸面并行净值（%s 起，%d 个交易日）' % (df.iloc[0]['date'], len(R)))
    print('  %-12s %8s %8s %8s' % ('日期', '线A抄底', '线B天基营', '合成40/60'))
    for _, x in R.tail(10).iterrows():
        print('  %-12s %8.4f %8.4f %8.4f' % (
            x['date'], x['A'], x['B'], 0.4 * x['A'] + 0.6 * x['B']))
    print('\n  累计：线A %+.2f%% ｜ 线B %+.2f%% ｜ 合成(40/60) %+.2f%%'
          % ((na - 1) * 100, (nb - 1) * 100, (0.4 * na + 0.6 * nb - 1) * 100))
    print('  ⚠️ 样本 < 60 个交易日时结论不可用，仅作记录。')


if __name__ == '__main__':
    import sys
    if '--paper' in sys.argv:
        paper_report()
    else:
        report()
