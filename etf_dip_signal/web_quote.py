# -*- coding: utf-8 -*-
"""
web_quote.py —— 腾讯/新浪行情数据源（网络实测可用，作为主数据源）

为什么用它：
  实测环境中 pytdx 的行情推送被网络屏蔽（K线/报价全空），
  但腾讯行情接口完全可用，且日线自带前复权（qfq），比 pytdx 更贴合聚宽口径。

提供接口：
  fetch_daily_kline(code, count)   前复权日线
  fetch_realtime(codes)            实时快照（批量）
  fetch_all_etf()                  全市场 ETF 列表（借 akshare 或腾讯板块）
"""

import json
import time
import threading
import urllib.request
import urllib.parse
import datetime as _dt
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

# ★ 数据源统计（2026-10-20 新增）
#   用途：腾讯 qfq 接口在大批量请求后会被限流返回 501，脚本会自动退化到「新浪不复权」。
#   而作者自己在注释里写明「必须前复权，否则分红/份额折算的ETF乖离率会严重失真」。
#   该退化过程原本完全静默 —— 这里埋计数器，让 signal_alert 能检测并告警。
SRC_STATS = {'tencent': 0, 'sina': 0}

# ★ 腾讯熔断（2026-10-20 新增）
#   实测：连续批量拉 381 只后，腾讯 ifzq 开始 501，且冷却期内 100% 失败。
#   原逻辑对每只仍先试腾讯（含重试），白白浪费大量请求。这里连续失败 8 次即熔断 10 分钟，
#   期间直接走新浪，既提速也让腾讯更早解封。不影响任何策略数值。
_TENCENT_FAILS = [0]
_TENCENT_OFF_UNTIL = [0.0]
_TENCENT_FAIL_LIMIT = 8
_TENCENT_COOLDOWN_SEC = 600

# 并发与限流控制（避免被腾讯限流返回 501）
_MAX_WORKERS = 8          # 并发线程数
_MIN_INTERVAL = 0.04      # 单线程最小请求间隔（秒）
_rate_lock = threading.Lock()
_last_req = [0.0]


def _throttle():
    """全局限流：保证整体请求不过快。"""
    with _rate_lock:
        now = time.time()
        wait = _MIN_INTERVAL - (now - _last_req[0])
        if wait > 0:
            time.sleep(wait)
        _last_req[0] = time.time()


def _get(url, encoding='utf-8', referer=None, retry=2):
    headers = {'User-Agent': _UA}
    if referer:
        headers['Referer'] = referer
    for i in range(retry + 1):
        _throttle()
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as r:
                return r.read().decode(encoding, errors='ignore')
        except Exception:
            if i >= retry:
                return None
            time.sleep(0.5 + i * 0.5)   # 退避
    return None


def fetch_daily_kline_batch(codes, count: int = 120, max_workers: int = _MAX_WORKERS) -> dict:
    """并发批量获取日线。返回 {code: DataFrame}。
    用于池构建阶段（几百只），相比串行提速 5-8 倍。
    """
    out = {}
    if not codes:
        return out

    def _one(c):
        df = fetch_daily_kline(c, count=count)
        return c, df

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_one, c) for c in codes]
        done = 0
        total = len(futures)
        for fut in as_completed(futures):
            try:
                c, df = fut.result()
                if df is not None and not df.empty:
                    out[c] = df
            except Exception:
                pass
            done += 1
            if done % 100 == 0:
                print(f"  [并发取数] {done}/{total}")
    return out


def norm_code(code: str) -> str:
    """6位代码 → 腾讯格式（sh510300 / sz159915）。
    5/6/9 开头=上海，0/1/2/3 开头=深圳。
    """
    s = str(code).strip().upper()
    if s.endswith('.XSHG') or s.startswith('SH'):
        num = s.replace('.XSHG', '').replace('SH', '')
        return 'sh' + num
    if s.endswith('.XSHE') or s.startswith('SZ'):
        num = s.replace('.XSHE', '').replace('SZ', '')
        return 'sz' + num
    num = s
    if num.startswith(('5', '6', '9', '7')):
        return 'sh' + num
    return 'sz' + num


def _strip_prefix(tcode: str) -> str:
    return tcode[2:] if tcode[:2] in ('sh', 'sz') else tcode


# ==================================================
# 日线（前复权）
# ==================================================
def fetch_daily_kline(code: str, count: int = 120, end_date=None) -> pd.DataFrame:
    """日线。★ 必须用前复权，否则分红/份额折算的ETF乖离率会严重失真。
    优先腾讯前复权（qfq），新浪不复权仅作最后备份。
    """
    b = _bucket(count)
    key = (str(code), b, str(end_date))
    if key in _KLINE_CACHE:
        cached = _KLINE_CACHE[key]
        if cached is None or cached.empty:
            return pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'vol', 'amount'])
        return cached.tail(count).reset_index(drop=True)

    df = _kline_tencent(code, b, end_date)
    if not df.empty:
        SRC_STATS['tencent'] += 1
        _TENCENT_FAILS[0] = 0
        _KLINE_CACHE[key] = df
        return df.tail(count).reset_index(drop=True)
    # 腾讯失败 → 计失败次数，触发熔断则令后续 10 分钟直接跳过腾讯
    if time.time() >= _TENCENT_OFF_UNTIL[0]:
        _TENCENT_FAILS[0] += 1
        if _TENCENT_FAILS[0] >= _TENCENT_FAIL_LIMIT:
            _TENCENT_OFF_UNTIL[0] = time.time() + _TENCENT_COOLDOWN_SEC
            print("  [数据源] 腾讯接口连续 %d 次失败（疑似限流 501），"
                  "熔断 %d 秒，改用新浪兜底" % (_TENCENT_FAILS[0], _TENCENT_COOLDOWN_SEC))
    df = _kline_sina(code, b, end_date)
    if not df.empty:
        SRC_STATS['sina'] += 1
    _KLINE_CACHE[key] = df          # 空结果也缓存：同一轮内不必对同一只反复重试
    if df.empty:
        return df
    return df.tail(count).reset_index(drop=True)


# ★ 单轮运行内日线缓存（2026-10-20 新增）
#   背景：calculate_bias 批量取完 381 只(52根) 后，check_oversold_stabilized / check_trend
#   会对同一只再分别取一次(26根/6根)，一次运行实际发出约 760 个请求 —— 腾讯限流下极易崩。
#   这里按「代码 + 数量档(60/320/800)」缓存当轮结果，砍掉重复请求。
#   ★ 只缓存单轮，不落盘、不跨轮复用，因此不存在数据陈旧问题。
_KLINE_CACHE = {}
_CACHE_BUCKETS = (60, 320, 800)


def clear_kline_cache():
    """每轮信号计算开始前调用，清空单轮缓存。"""
    _KLINE_CACHE.clear()


def _bucket(n: int) -> int:
    for b in _CACHE_BUCKETS:
        if n <= b:
            return b
    return _CACHE_BUCKETS[-1]


def _kline_sina(code: str, count: int = 120, end_date=None) -> pd.DataFrame:
    """新浪前复权日线。"""
    empty = pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'vol', 'amount'])
    tc = norm_code(code)
    n = min(max(count + 20, 60), 1023)
    url = ('https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
           f'CN_MarketData.getKLineData?symbol={tc}&scale=240&ma=no&datalen={n}')
    txt = _get(url, encoding='gbk', referer='https://finance.sina.com.cn')
    if not txt or txt.strip() in ('null', '[]', ''):
        return empty
    try:
        data = json.loads(txt)
    except Exception:
        return empty
    if not data:
        return empty
    rows = []
    for it in data:
        try:
            rows.append({
                'date': it['day'][:10],
                'open': float(it['open']),
                'high': float(it['high']),
                'low': float(it['low']),
                'close': float(it['close']),
                'vol': float(it['volume']),
                'amount': float(it['close']) * float(it['volume']),
            })
        except Exception:
            continue
    df = pd.DataFrame(rows)
    if df.empty:
        return empty
    if end_date is not None:
        df = df[df['date'] <= str(end_date)].reset_index(drop=True)
    return df.tail(count).reset_index(drop=True)


def _kline_tencent(code: str, count: int = 120, end_date=None) -> pd.DataFrame:
    """腾讯前复权日线（主源）。"""
    empty = pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'vol', 'amount'])
    if time.time() < _TENCENT_OFF_UNTIL[0]:
        return empty          # ★ 熔断期内直接放弃，不再浪费请求
    tc = norm_code(code)
    n = min(max(count + 20, 60), 800)
    url = (f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
           f'?param={tc},day,,,{n},qfq')
    txt = _get(url)
    if not txt:
        return empty
    try:
        d = json.loads(txt)
        node = d['data'][tc]
        kl = node.get('qfqday') or node.get('day')
    except Exception:
        return empty
    if not kl:
        return empty
    rows = []
    for item in kl:
        try:
            # ★ 腾讯 fqkline 的 volume(item[5]) 单位是「手」(1手=100份)，且接口不返回成交额。
            #   这里 ×100 转成「份」，并用 close×份数 近似成交额(元)。
            #   修复前 amount=close×手数 低估了 100 倍，导致流动性过滤(MIN_MONEY=1000万)
            #   误删几乎所有成交额<10亿的 ETF（银行/豆粕/纳指等被误砍）。
            rows.append({
                'date': item[0], 'open': float(item[1]), 'close': float(item[2]),
                'high': float(item[3]), 'low': float(item[4]), 'vol': float(item[5]) * 100,
                'amount': float(item[2]) * float(item[5]) * 100,
            })
        except Exception:
            continue
    df = pd.DataFrame(rows)
    if df.empty:
        return empty
    if end_date is not None:
        df = df[df['date'] <= str(end_date)].reset_index(drop=True)
    return df.tail(count).reset_index(drop=True)


# ==================================================
# 实时快照（腾讯批量）
# ==================================================
def fetch_realtime(codes) -> pd.DataFrame:
    """腾讯实时行情。返回 code/name/price/last_close/open/high/low/vol/amount/paused。"""
    empty = pd.DataFrame()
    if not codes:
        return empty
    code_list = [str(c) for c in codes]
    tcodes = [norm_code(c) for c in code_list]

    rows = []
    for i in range(0, len(tcodes), 60):
        batch = tcodes[i:i + 60]
        url = 'https://qt.gtimg.cn/q=' + ','.join(batch)
        txt = _get(url, encoding='gbk')
        if not txt:
            continue
        for line in txt.split(';'):
            line = line.strip()
            if '=' not in line or '"' not in line:
                continue
            try:
                val = line.split('="', 1)[1].rstrip('"')
                f = val.split('~')
                if len(f) < 45:
                    continue
                tcode = line.split('=')[0].replace('v_', '').strip()
                code = _strip_prefix(tcode)
                price = float(f[3] or 0)
                last_close = float(f[4] or 0)
                vol_hand = float(f[36] or 0)      # 成交量（手）
                amount_wan = float(f[37] or 0)    # 成交额（万元）
                rows.append({
                    'code': code,
                    'name': f[1],
                    'price': price,
                    'last_close': last_close,
                    'open': float(f[5] or 0),
                    'high': float(f[33] or 0),
                    'low': float(f[34] or 0),
                    'vol': vol_hand * 100,           # 转成股/份
                    'amount': amount_wan * 1e4,      # 转成元
                    'paused': price <= 0,
                })
            except Exception:
                continue
    if not rows:
        return empty
    return pd.DataFrame(rows).drop_duplicates(subset=['code'], keep='first').reset_index(drop=True)


# ==================================================
# 全市场 ETF 列表
# ==================================================
def fetch_all_etf() -> pd.DataFrame:
    """全市场 ETF 列表。优先新浪（实测可用），再 akshare，最后本地文件。"""
    # 方案1：新浪 ETF 榜单（分页）
    try:
        df = _fetch_etf_list_sina()
        if not df.empty:
            return df
    except Exception:
        pass

    # 方案2：akshare
    try:
        import akshare as ak
        spot = ak.fund_etf_spot_em()
        if spot is not None and len(spot) > 0:
            df = pd.DataFrame({
                'code': spot['代码'].astype(str),
                'display_name': spot['名称'].astype(str),
            })
            df = df[df['code'].apply(is_etf_code)].drop_duplicates(subset=['code'])
            return df.reset_index(drop=True)
    except Exception:
        pass

    # 方案3：本地文件
    import os
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'etf_list.csv')
    if os.path.exists(p):
        try:
            df = pd.read_csv(p, dtype=str)
            return df.rename(columns={'name': 'display_name'})[['code', 'display_name']]
        except Exception:
            pass
    return pd.DataFrame(columns=['code', 'display_name'])


def _fetch_etf_list_sina() -> pd.DataFrame:
    """新浪 ETF 榜单分页拉取（含实时价/成交额）。"""
    import os
    rows = []
    page = 1
    while page <= 30:
        url = ('https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/'
               f'Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1'
               '&node=etf_hq_fund&symbol=')
        txt = _get(url, encoding='gbk', referer='https://finance.sina.com.cn')
        if not txt or txt.strip() in ('null', '[]', ''):
            break
        try:
            data = json.loads(txt)
        except Exception:
            break
        if not data:
            break
        for it in data:
            code = str(it.get('code', '')).strip()
            if not is_etf_code(code):
                continue
            rows.append({
                'code': code,
                'display_name': str(it.get('name', '')).strip(),
                'price': float(it.get('trade', 0) or 0),
                'amount_sina': float(it.get('amount', 0) or 0),  # 元
            })
        page += 1
        time.sleep(0.05)

    if not rows:
        return pd.DataFrame(columns=['code', 'display_name'])
    df = pd.DataFrame(rows).drop_duplicates(subset=['code'], keep='first').reset_index(drop=True)

    # 顺手保存一份本地缓存，供离线复用
    try:
        cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
        os.makedirs(cache_dir, exist_ok=True)
        df[['code', 'display_name']].to_csv(
            os.path.join(cache_dir, 'etf_list.csv'), index=False, encoding='utf-8-sig')
    except Exception:
        pass
    return df[['code', 'display_name']]


def is_etf_code(code: str) -> bool:
    code = str(code)
    if len(code) != 6:
        return False
    return code.startswith(('51', '56', '58', '159'))


def fetch_trade_dates(count=800):
    """用上证指数日线日期作为交易日历。
    ★ 必须是 sh000001（上证指数），而非 '000001'——后者经 norm_code 会映射成
      深市平安银行 sz000001，个股可能停牌导致交易日历缺失。
    """
    df = fetch_daily_kline('SH000001', count=count)
    if df.empty:
        return []
    return df['date'].tolist()


def latest_trade_date():
    dates = fetch_trade_dates(count=10)
    if dates:
        return dates[-1]
    return _dt.date.today().strftime('%Y-%m-%d')


if __name__ == '__main__':
    k = fetch_daily_kline('510300', 10)
    print('日线:', k.tail(3).to_dict('records'))
    r = fetch_realtime(['510300', '159915', '563300'])
    print('实时:', r.to_dict('records'))
