# -*- coding: utf-8 -*-
"""
pool_builder.py —— 动态 ETF 池构建
完全对应聚宽策略的 build_etf_pool() 及其子函数。

★ 数据源差异说明（务必阅读）：
  聚宽通过 finance.FUND_INVEST_TARGET 拿"跟踪指数"、get_index_stocks 拿成分股、
  get_index_weights 拿权重、FUND_SHARE_DAILY 拿份额规模。
  pytdx 没有这些接口，因此本模块通过"本地映射文件"补足：
    data/etf_index_map.csv        列：code,track_index_name,track_index_code
    data/index_constituents.json  格式：{"000300": ["600519", ...], ...}
    data/index_weights.json       格式：{"000300": {"600519": 0.05, ...}, ...}
    data/etf_shares.json          格式：{"510300": 123456789.0, ...}（单位：份）
  首次运行若缺少这些文件，会自动退化为"仅按名称+指数标识去重"的简化模式，
  不影响主流程运行，只是池子压缩力度弱一些。
"""

import os
import json
import re
import numpy as np
import pandas as pd

import config as cfg
from keywords import (
    MONEY_KEYWORDS, BOND_KEYWORDS, ASSET_CLASS_KEYWORDS, SUBCLASS_KEYWORDS,
    STAR_BROAD_KEYWORDS, SMART_BETA_KEYWORDS, REAL_INDUSTRY_KEYWORDS,
    CROSS_BORDER_KEYWORDS, CROSS_BORDER_EXCLUDE, HK_CN_KEYWORDS, PURE_OVERSEAS_KEYWORDS,
)
from tdx_api import list_all_etf, get_daily_kline, get_trade_dates

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')


# ==================================================
# 本地映射加载
# ==================================================
def _load_csv(name) -> pd.DataFrame:
    path = os.path.join(DATA_DIR, name)
    if os.path.exists(path):
        try:
            return pd.read_csv(path, dtype=str)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def _load_json(name):
    path = os.path.join(DATA_DIR, name)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def load_etf_index_map() -> pd.DataFrame:
    df = _load_csv('etf_index_map.csv')
    if df.empty:
        return pd.DataFrame(columns=['code', 'track_index_name', 'track_index_code'])
    return df


def load_index_constituents() -> dict:
    return _load_json('index_constituents.json')


def load_index_weights() -> dict:
    return _load_json('index_weights.json')


def load_etf_shares() -> dict:
    return _load_json('etf_shares.json')


# ==================================================
# 基础工具
# ==================================================
def name_hit(name, keywords) -> bool:
    if not name:
        return False
    low = str(name).lower()
    return any(kw.lower() in low for kw in keywords)


def resolve_end_date(end_date=None) -> str:
    dates = get_trade_dates()
    if not dates:
        import datetime as _dt
        return _dt.date.today().strftime('%Y-%m-%d')
    if end_date is None:
        return dates[-1]
    if str(end_date) in dates:
        return str(end_date)
    prior = [d for d in dates if d <= str(end_date)]
    return prior[-1] if prior else dates[0]


def filter_basic(etfs_df: pd.DataFrame, date: str) -> pd.DataFrame:
    """基础过滤：剔除货币 / 债券类 ETF（对应 yy_filter_basic）。"""
    df = etfs_df.copy()
    if cfg.EXCLUDE_MONEY:
        mask = df['display_name'].apply(lambda x: name_hit(str(x), MONEY_KEYWORDS))
        df = df[~mask]
    if cfg.EXCLUDE_BOND:
        mask = df['display_name'].apply(lambda x: name_hit(str(x), BOND_KEYWORDS))
        df = df[~mask]
    return df


# ==================================================
# 规模 / 成交额
# ==================================================
def fetch_market_data(codes, end_date: str) -> pd.DataFrame:
    """取每只 ETF 的收盘价、近 AVG_MONEY_DAYS 日均成交额（万元）、年化波动率(%)。
    对应 yy_fetch_market_data / yy_fetch_one_price。
    ★ 使用并发批量拉取，避免串行过慢。
    ★ 波动率用于「大类×波动档」抄底阈值分档（VOL_LOOKBACK 根日线）。
    """
    import web_quote
    kline_map = web_quote.fetch_daily_kline_batch(codes, count=cfg.VOL_LOOKBACK + 2)
    records = []
    for code, df in kline_map.items():
        if df.empty or len(df) < 30:
            continue
        if end_date is not None:
            df = df[df['date'] <= str(end_date)]
        if len(df) < 30:
            continue
        close_val = float(df['close'].iloc[-1])
        money_val = float(pd.to_numeric(df['amount'], errors='coerce')
                          .tail(cfg.AVG_MONEY_DAYS).mean()) / 1e4
        close_s = pd.to_numeric(df['close'], errors='coerce').dropna()
        ret = close_s.pct_change().dropna()
        ann_vol = float(ret.std() * np.sqrt(252) * 100) if len(ret) >= 20 else 0.0
        records.append({'code': code, 'close': close_val, 'avg_money_wan': money_val,
                        'vol': ann_vol})
    if not records:
        return pd.DataFrame(columns=['close', 'avg_money_wan', 'vol'])
    return pd.DataFrame(records).set_index('code')


def fetch_scale(codes, shares_map: dict) -> pd.DataFrame:
    """规模估算。对应 yy_fetch_scale。
    pytdx 无份额接口，用本地 shares_map（份）× 收盘价 估算。
    """
    rows = []
    for code in codes:
        s = shares_map.get(code) or shares_map.get(str(code).split('.')[0])
        rows.append({'code': code, 'shares': s})
    return pd.DataFrame(rows).set_index('code')


# ==================================================
# 指数归一化（对应 yy_normalize_index_code/name）
# ==================================================
def normalize_index_code(code) -> str:
    code = str(code or '').strip()
    if code.lower() in ('', 'none', 'nan'):
        return ''
    return re.sub(r'CNY\d*$', '', code)


def normalize_index_name(name) -> str:
    name = str(name or '').strip()
    if name.lower() in ('', 'none', 'nan'):
        return ''
    name = re.sub(r'\([^)]*\)$', '', name).strip()
    name = re.sub(r'(CNY|CPR)\d*$', '', name).strip()
    name = re.sub(r'^[沪深](?=[A-Za-z0-9])', '', name)
    return name


def extract_index_code(name) -> str:
    name = str(name or '').strip()
    m = re.search(r'\(([0-9A-Za-z.\-]+)\)\s*$', name)
    return m.group(1) if m else ''


def index_display(row) -> str:
    code = str(row.get('track_index_code') or '').strip()
    name = str(row.get('track_index_name') or '').strip()
    if code.lower() in ('none', 'nan'):
        code = ''
    if name.lower() in ('none', 'nan'):
        name = ''
    if name and code and ('(' not in name):
        return f"{name}({code})"
    return name or code or '未知指数'


def sort_by_rank(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(['规模_亿'], ascending=False, na_position='last')


def group_keep_largest(df: pd.DataFrame, key_col: str) -> pd.DataFrame:
    """按某列分组，保留规模最大的一只。对应 yy_group_keep_largest。"""
    work = df.copy()
    work[key_col] = work[key_col].fillna('').astype(str)
    empty_mask = work[key_col] == ''
    work.loc[empty_mask, key_col] = 'SINGLE:' + work.loc[empty_mask, 'code']
    work = sort_by_rank(work)
    keep_codes = [grp.iloc[0]['code'] for _, grp in work.groupby(key_col, sort=False)]
    kept = work[work['code'].isin(keep_codes)].copy()
    return kept.drop(columns=[key_col])


# ==================================================
# 去重：跟踪指数
# ==================================================
def dedup_by_index(df: pd.DataFrame) -> pd.DataFrame:
    """按跟踪指数去重，同指数只留规模最大。对应 yy_dedup_by_index。"""
    work = df.copy()

    def make_key(row):
        code = str(row.get('track_index_code') or '').strip()
        name = str(row.get('track_index_name') or '').strip()
        if code.lower() in ('', 'none', 'nan'):
            code = ''
        if name.lower() in ('', 'none', 'nan'):
            name = ''
        if code:
            return code
        if name:
            return 'NAME:' + name
        return None

    work['index_key'] = work.apply(make_key, axis=1)
    unknown = work['index_key'].isna()
    work.loc[unknown, 'index_key'] = 'UNKNOWN:' + work.loc[unknown, 'code']
    work = sort_by_rank(work)
    keep_codes = [grp.iloc[0]['code'] for _, grp in work.groupby('index_key', sort=False)]
    kept = work[work['code'].isin(keep_codes)].copy()
    return kept.drop(columns=['index_key'])


def dedup_by_alias(df: pd.DataFrame) -> pd.DataFrame:
    """双代码归一：先按指数代码，再按指数名称去重。对应 yy_dedup_by_alias。"""
    work = df.copy()
    work['_alias_code'] = work['track_index_code'].apply(normalize_index_code)
    work = group_keep_largest(work, '_alias_code')
    work['_alias_name'] = work['track_index_name'].apply(normalize_index_name)
    work = group_keep_largest(work, '_alias_name')
    return work


# ==================================================
# 去重：成分股重叠
# ==================================================
def index_overlap(set_a, set_b, weights_a, weights_b):
    """计算两个指数成分股的数量重叠率与权重重叠率。对应 yy_index_overlap。"""
    if len(set_a) == 0 or len(set_b) == 0:
        return 0.0, None
    inter = set_a & set_b
    count_ratio = min(len(inter) / len(set_a), len(inter) / len(set_b))
    weight_ratio = None
    if len(inter) > 0 and weights_a is not None and weights_b is not None:
        wa = sum(weights_a.get(s, 0.0) for s in inter)
        wb = sum(weights_b.get(s, 0.0) for s in inter)
        weight_ratio = min(wa, wb)
    return count_ratio, weight_ratio


def is_duplicate(count_ratio, weight_ratio, count_th, weight_th) -> bool:
    if count_ratio >= count_th:
        return True
    if weight_ratio is not None and weight_ratio >= weight_th:
        return True
    return False


def dedup_by_constituents(df: pd.DataFrame, end_date: str,
                          count_th=0.90, weight_th=0.90) -> pd.DataFrame:
    """按成分股/权重重叠去重。对应 yy_dedup_by_constituents。
    依赖本地 data/index_constituents.json 与 data/index_weights.json。
    若本地无数据，则跳过（返回原表）。
    """
    constituents_all = load_index_constituents()
    weights_all = load_index_weights()
    if not constituents_all:
        return df

    work = df.copy()
    work['_idx_code'] = work.apply(
        lambda r: (str(r.get('track_index_code') or '')
                   if str(r.get('track_index_code') or '').strip()
                   else extract_index_code(r.get('track_index_name'))), axis=1)
    work['_idx_code'] = work['_idx_code'].apply(normalize_index_code)

    def _idx_scale(c):
        vals = work.loc[work['_idx_code'] == c, '规模_亿'].dropna()
        return float(vals.max()) if len(vals) > 0 else 0.0

    sorted_codes = sorted([c for c in work['_idx_code'].unique() if c], key=_idx_scale, reverse=True)

    groups = []
    for c in sorted_codes:
        placed = False
        set_c = set(constituents_all.get(c, []))
        w_c = weights_all.get(c)
        for rep, members in groups:
            set_rep = set(constituents_all.get(rep, []))
            w_rep = weights_all.get(rep)
            cr, wr = index_overlap(set_rep, set_c, w_rep, w_c)
            if is_duplicate(cr, wr, count_th, weight_th):
                members.append(c)
                placed = True
                break
        if not placed:
            groups.append((c, [c]))

    drop_codes = set()
    for rep, group_codes in groups:
        if len(group_codes) == 1:
            continue
        losers = work[work['_idx_code'].isin(group_codes) & (work['_idx_code'] != rep)]
        drop_codes.update(losers['code'].tolist())

    kept = work[~work['code'].isin(drop_codes)].copy()
    return kept.drop(columns=['_idx_code'])


# ==================================================
# 去重：收益率相关性
# ==================================================
def corr_pair(ra: pd.Series, rb: pd.Series):
    """计算 Spearman 与尾部 Pearson 相关性。对应 yy_corr_pair。
    ★ 修复：两个序列统一用位置索引(0..N-1)对齐，避免索引不一致导致 KeyError。
    """
    s_corr = np.nan
    t_corr = np.nan

    # 统一重置为位置索引，并取较短长度对齐
    a_all = pd.Series(np.asarray(ra, dtype=float)).reset_index(drop=True)
    b_all = pd.Series(np.asarray(rb, dtype=float)).reset_index(drop=True)
    n = min(len(a_all), len(b_all))

    if n >= 30:
        # 取最近 n 根，位置对齐
        a = a_all.iloc[-n:].reset_index(drop=True)
        b = b_all.iloc[-n:].reset_index(drop=True)
        try:
            s_corr = a.corr(b, method='spearman')
        except Exception:
            s_corr = np.nan
    if not np.isfinite(s_corr):
        s_corr = 0.0

    # 尾部相关：取各自 10% 分位以下的点，按位置掩码对齐
    if n >= 30:
        a = a_all.iloc[-n:].reset_index(drop=True)
        b = b_all.iloc[-n:].reset_index(drop=True)
        qa = a.quantile(0.10)
        qb = b.quantile(0.10)
        mask = (a <= qa) | (b <= qb)
        if int(mask.sum()) >= 10:
            try:
                t_corr = a[mask].corr(b[mask], method='pearson')
            except Exception:
                t_corr = np.nan
            if not np.isfinite(t_corr):
                t_corr = 0.5
        else:
            t_corr = 0.5
    else:
        t_corr = 0.5
    return round(s_corr * 100), round(t_corr * 100)


def corr_merge(df: pd.DataFrame, end_date: str) -> pd.DataFrame:
    """按收益率相关性去重，同组只保留规模最大。对应 yy_corr_merge。
    ★ 并发批量取数。
    """
    import web_quote
    work = df.copy()
    codes = work['code'].tolist()
    kline_map = web_quote.fetch_daily_kline_batch(codes, count=cfg.CORR_LOOKBACK + 2)
    rets = {}
    for c, k in kline_map.items():
        if k.empty or len(k) < 30:
            continue
        if end_date is not None:
            k = k[k['date'] <= str(end_date)]
        close = pd.to_numeric(k['close'], errors='coerce').dropna()
        if len(close) < 30:
            continue
        r = close.pct_change().dropna()
        if len(r) >= 30:
            rets[c] = r.reset_index(drop=True)

    work['_has_ret'] = work['code'].isin(rets)
    drop_codes = set()
    for _, grp in work.groupby(['asset_class', 'subclass'], sort=False):
        grp = grp[grp['_has_ret']]
        if len(grp) < 2:
            continue
        grp = sort_by_rank(grp)
        reps = []  # (rep_code, [member_codes])
        for _, r in grp.iterrows():
            code = r['code']
            placed = False
            for rep, members in reps:
                s_corr, t_corr = corr_pair(rets[rep], rets[code])
                if (s_corr >= cfg.CORR_SPEARMAN_TH_PCT or t_corr >= cfg.CORR_TAIL_TH_PCT):
                    members.append(code)
                    placed = True
                    break
            if not placed:
                reps.append((code, []))
        for rep, members in reps:
            drop_codes.update(members)

    kept = work[~work['code'].isin(drop_codes)].copy()
    return kept.drop(columns=['_has_ret'])


# ==================================================
# 归类
# ==================================================
def classify_etf(name: str) -> str:
    if not name:
        return '其他'
    low = str(name).lower()
    for asset_class, keywords in ASSET_CLASS_KEYWORDS.items():
        if any(kw.lower() in low for kw in keywords):
            return asset_class
    return '其他'


def asset_class_of(row) -> str:
    """大类归类。对应 yy_asset_class。"""
    name = str(row.get('display_name') or '')
    idx = re.sub(r'\([^)]*\)$', '', str(row.get('index_display') or '')).strip()
    low_name = name.lower()
    low_idx = idx.lower() if idx else ''

    if name_hit(low_name, STAR_BROAD_KEYWORDS) or name_hit(low_idx, STAR_BROAD_KEYWORDS):
        return '股票-宽基'
    if name_hit(low_name, BOND_KEYWORDS) or name_hit(low_idx, BOND_KEYWORDS):
        return '债券'
    if (name_hit(low_idx, ['上期有色金属', '期货'])
            or name_hit(low_name, ['上期有色金属', '豆粕期货', '能源化工'])):
        return '商品'
    # ★ 修正（2026-10-13）：黄金股票型 ETF 必须归「股票-行业」(-16%)，而非「商品」(-11%)。
    #   数据源简称可能把「黄金股ETF」写成「黄金产业」（缺"股"字），若只匹配'黄金股'
    #   会漏判，落到 ASSET_CLASS_KEYWORDS['商品'] 的 '黄金' 上 → 阈值被错划为 -11%，
    #   导致轻微超卖（如 -11.03%）就触发抄底。故补齐同义写法。
    if (name_hit(low_name, ['黄金股', '黄金产业', '黄金股票', '黄金矿业'])
            or name_hit(low_idx, ['黄金股', '黄金产业', '黄金股票', '黄金矿业'])):
        return '股票-行业'

    cross_hit = (name_hit(low_name, CROSS_BORDER_KEYWORDS)
                 or name_hit(low_idx, CROSS_BORDER_KEYWORDS))
    cross_exclude = (name_hit(low_name, CROSS_BORDER_EXCLUDE)
                     or name_hit(low_idx, CROSS_BORDER_EXCLUDE))
    if cross_hit and not cross_exclude:
        return '跨境'

    if name_hit(low_name, SMART_BETA_KEYWORDS) or name_hit(low_idx, SMART_BETA_KEYWORDS):
        return '股票-股息红利'

    cls = classify_etf(name)
    if cls == '其他' and low_idx:
        idx_cls = classify_etf(idx)
        if idx_cls == '股票-宽基':
            cls = '股票-宽基'
    if cls == '股票-宽基' and (name_hit(low_name, REAL_INDUSTRY_KEYWORDS)
                               or name_hit(low_idx, REAL_INDUSTRY_KEYWORDS)):
        return '股票-行业'
    if cls != '其他':
        return cls
    if idx and idx != '未知指数':
        idx_cls = classify_etf(idx)
        if idx_cls != '其他':
            return idx_cls
    return '其他'


def subclass_of(row) -> str:
    """子类归类。对应 yy_subclass。"""
    rules = SUBCLASS_KEYWORDS.get(str(row.get('asset_class') or ''))
    if not rules:
        return '其他'
    texts = [str(row.get('display_name') or '')]
    idx = re.sub(r'\([^)]*\)$', '', str(row.get('index_display') or '')).strip()
    if idx and idx != '未知指数':
        texts.append(idx)
    for text in texts:
        if not text or text == '未知指数':
            continue
        low = text.lower()
        for subclass, keywords in rules:
            if any(kw.lower() in low for kw in keywords):
                return subclass
    return '其他'


def pick_buy_bias_th(asset_class, subclass, display_name, index_display) -> float:
    """决定单只ETF的 20 日乖离买入阈值。完全对应 _pick_buy_bias_th()。"""
    # 1. 商品 → -11%
    if asset_class == '商品':
        return cfg.BUY_BIAS_TH_OVERSEAS_COMMODITY

    # 2. 非跨境：红利+低波 → -5%，其余 → -16%
    if asset_class != '跨境':
        if asset_class == '股票-股息红利':
            text = (str(display_name or '') + ' ' + str(index_display or '')).lower()
            has_hongli = ('红利' in text) or ('高股息' in text)
            has_dibo = ('低波' in text)
            if has_hongli and has_dibo:
                return cfg.BUY_BIAS_TH_DIVIDEND_LOWVOL
        return cfg.BUY_BIAS_TH

    # 3. 跨境 + 港股/中概 → -16%
    if subclass in ('港股', '中概'):
        return cfg.BUY_BIAS_TH

    # 4. 跨境 + 美股/日本/欧股/中东 → -11%
    if subclass in ('美股', '日本', '欧股', '中东'):
        return cfg.BUY_BIAS_TH_OVERSEAS_COMMODITY

    # 5. 跨境其他 → 名称兜底
    text = (str(display_name or '') + ' ' + str(index_display or '')).lower()
    if any(kw.lower() in text for kw in HK_CN_KEYWORDS):
        return cfg.BUY_BIAS_TH
    if any(kw.lower() in text for kw in PURE_OVERSEAS_KEYWORDS):
        return cfg.BUY_BIAS_TH_OVERSEAS_COMMODITY
    return cfg.BUY_BIAS_TH


def get_class_th_override(code):
    """查人工覆盖表（config.CLASS_TH_OVERRIDES）。

    命中返回 (大类, 阈值%)，未命中返回 None。
    覆盖表优先级最高，用于名称规则天然会误判的标的
    （如 562060 标普A股红利：名称含"标普"会被误判跨境，实际底层是A股红利）。
    """
    ov = getattr(cfg, 'CLASS_TH_OVERRIDES', {}) or {}
    code_s = str(code or '')
    hit = ov.get(code_s) or ov.get(code_s.split('.')[0])
    if not hit:
        return None
    return hit[0], int(hit[1])


def pick_buy_bias_th_vol(asset_class, vol_bin) -> float:
    """按「大类 × 波动档」决定 20 日乖离买入阈值（2026-10-13 近5年回测结论）。

    核心规律：波动率越高阈值越深（高波需要更深超卖才算机会），低波浅超卖即反弹。
    映射表见 config.BIAS_TH_BY_CLASS_VOL。原 pick_buy_bias_th 保留为旧口径（备份于
    交付文档/原策略备份_20261013/）。
    """
    tbl = getattr(cfg, 'BIAS_TH_BY_CLASS_VOL', {})
    return tbl.get(asset_class, {}).get(vol_bin, cfg.BUY_BIAS_TH)


# ==================================================
# 池构建主流程
# ==================================================
# ==================================================
# ★ 固定池（2026-10-14 冻结）
# ==================================================
def load_fixed_pool(path=None):
    """读取固定池文件（data/fixed_pool.json）。

    返回 (codes, class_map, bias_th_map, frozen_date)。
    固定池把「代码 → 大类 / 抄底阈值」写死，彻底摆脱对数据源简称的依赖，
    避免 159321 / 159696 / 159529 那类"名称漂移导致阈值错分"。
    """
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            cfg.FIXED_POOL_FILE)
    elif not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    if not os.path.exists(path):
        return [], {}, {}, ''
    with open(path, 'r', encoding='utf-8') as f:
        d = json.load(f)
    codes = [str(c) for c in d.get('codes', [])]
    cmap = {str(k): v for k, v in d.get('cmap', {}).items()}
    bmap = {str(k): int(v) for k, v in d.get('bmap', {}).items()}
    return codes, cmap, bmap, d.get('frozen_at') or d.get('date', '')


def build_etf_pool(end_date=None):
    """构建 ETF 池。对应 build_etf_pool()。
    返回 (pool_codes: List[str], class_map: dict, bias_th_map: dict)
    """
    end_date = resolve_end_date(end_date)
    log = print

    # ★ 固定池模式：直接返回冻结的代码/大类/阈值，跳过全部动态筛选
    if getattr(cfg, 'USE_FIXED_POOL', False):
        codes, cmap, bmap, frozen = load_fixed_pool()
        if codes:
            log(f"[池构建] 使用固定池（{frozen} 冻结）: {len(codes)} 只")
            from collections import Counter
            log(f"    阈值分布: {dict(Counter(bmap.values()))}")
            return codes, cmap, bmap
        log("[池构建] 固定池文件缺失，回退动态建池")

    # 1. 全市场 ETF
    etfs = list_all_etf()
    n_all = len(etfs)
    log(f"[池构建] 场内ETF总数: {n_all} 只")
    if n_all == 0:
        return [], {}, {}

    # 2. 基础过滤
    etfs = filter_basic(etfs, end_date)

    # 3. 合并跟踪指数映射
    index_map = load_etf_index_map()
    if not index_map.empty:
        index_map = index_map.rename(columns={
            'track_index_name': 'track_index_name',
            'track_index_code': 'track_index_code',
        })
        df = etfs.merge(index_map[['code', 'track_index_name', 'track_index_code']],
                        on='code', how='left')
    else:
        df = etfs.copy()
        df['track_index_name'] = None
        df['track_index_code'] = None

    codes = df['code'].tolist()

    # 4. 行情与规模（并发批量）
    log(f"[池构建] 拉取 {len(codes)} 只 ETF 行情（并发）...")
    market = fetch_market_data(codes, end_date)
    shares_map = load_etf_shares()
    scale = fetch_scale(codes, shares_map)
    df = df.merge(market, on='code', how='left')
    df = df.merge(scale, on='code', how='left')
    df['规模_亿'] = pd.to_numeric(df['shares'], errors='coerce') * \
        pd.to_numeric(df['close'], errors='coerce') / 1e8

    # 5. 跟踪指数去重
    kept = dedup_by_index(df)
    log(f"[池构建] 指数去重后: {len(kept)} 只")

    # 6. 迷你基金过滤
    if cfg.EXCLUDE_MINI and cfg.MINI_SCALE > 0 and '规模_亿' in kept.columns:
        scale_num = pd.to_numeric(kept['规模_亿'], errors='coerce')
        # 仅在规模数据存在时过滤；无份额数据的保留（避免误杀）
        mini_mask = scale_num.notna() & (scale_num < cfg.MINI_SCALE)
        kept = kept[~mini_mask]

    # 7. 流动性过滤
    if cfg.EXCLUDE_LIQUIDITY and cfg.MIN_MONEY > 0:
        money_num = pd.to_numeric(kept['avg_money_wan'], errors='coerce')
        liq_mask = money_num.notna() & (money_num < cfg.MIN_MONEY)
        kept = kept[~liq_mask]

    # 8. 双代码归一
    kept = dedup_by_alias(kept)

    # 9. 成分股去重
    kept = dedup_by_constituents(kept, end_date,
                                 cfg.CONSTITUENT_OVERLAP, cfg.WEIGHT_OVERLAP)

    # 10. 归类
    kept = sort_by_rank(kept).copy()
    kept['index_display'] = kept.apply(index_display, axis=1)
    kept['asset_class'] = kept.apply(asset_class_of, axis=1)
    kept['subclass'] = kept.apply(subclass_of, axis=1)

    # 11. 相关性去重
    kept = corr_merge(kept, end_date)

    # 12. 大类剔除
    final = sort_by_rank(kept).copy()
    class_exclude = []
    if cfg.EXCLUDE_DIVIDEND:
        class_exclude.append('股票-股息红利')
    if cfg.EXCLUDE_CROSS:
        class_exclude.append('跨境')
    if cfg.EXCLUDE_COMMODITY:
        class_exclude.append('商品')
    if class_exclude:
        final = final[~final['asset_class'].isin(class_exclude)]

    # 13. 汇总输出
    log(f"[池构建] 最终池子数量: {len(final)} 只  "
        f"压缩率: {(1 - len(final) / n_all) * 100:.1f}%")
    if not final.empty:
        for k, v in final['asset_class'].value_counts().to_dict().items():
            log(f"    {k:<12}: {v} 只")

    if cfg.SHOW_FULL_POOL and not final.empty:
        cols = ['code', 'display_name', 'asset_class', 'subclass', '规模_亿', 'avg_money_wan']
        cols = [c for c in cols if c in final.columns]
        log(final[cols].to_string(index=False))

    class_map = dict(zip(final['code'].tolist(), final['asset_class'].tolist()))

    # ★ 抄底阈值：旧三档（-16/-11/-5）。
    # 2026-10-13 复盘：【真实买卖规则】回测（单持仓/回本止盈/+3%/止损/30天换仓）下
    # 旧三档累计+202%，优于大类×波动档表（+89%）和加深版（+131%），故回退。
    # 大类×波动档逻辑保留在 pick_buy_bias_th_vol（研究备份，不参与决策）。
    bias_th_map = {}
    for _, r in final.iterrows():
        bias_th_map[r['code']] = pick_buy_bias_th(
            r.get('asset_class'), r.get('subclass'),
            r.get('display_name'), r.get('index_display'))

    return final['code'].tolist(), class_map, bias_th_map
