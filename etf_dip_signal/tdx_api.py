# -*- coding: utf-8 -*-
"""
tdx_api.py —— 数据访问层（多数据源统一封装）
替代聚宽的数据接口：
  get_all_securities        -> list_all_etf()
  get_price / history       -> get_daily_kline()
  get_current_data          -> get_realtime()
  get_trade_days            -> get_trade_dates()
  get_security_info         -> get_etf_name()

★ 数据源优先级（实测结论）：
  1. 腾讯行情（web_quote）—— 实测可用，日线自带前复权 qfq，作为默认主源
  2. pytdx —— 通达信协议；本环境行情推送被屏蔽，作为备份
  3. akshare —— 兜底
  用 config.DATA_SOURCE 控制：'web'(默认) / 'tdx' / 'ak'
"""

import time
import socket
import datetime as _dt
from typing import List, Dict, Optional, Tuple

import pandas as pd

import web_quote

try:
    from pytdx.hq import TdxHq_API
    _HAS_PYTDX = True
except ImportError:
    _HAS_PYTDX = False

try:
    import akshare as ak
    _HAS_AKSHARE = True
except ImportError:
    _HAS_AKSHARE = False

import config
from keywords import MONEY_KEYWORDS, BOND_KEYWORDS

# 主数据源：'web'(腾讯，默认) / 'tdx' / 'ak'
DATA_SOURCE = getattr(config, 'DATA_SOURCE', 'web')
_USE_AK = False   # 运行时自动切换标记


# ==================================================
# 连接管理
# ==================================================
class TdxConn:
    """通达信行情连接封装，带自动重连与多服务器容错。"""

    def __init__(self):
        self.api = None
        self.server = None
        self._connect()

    def _connect(self):
        for host, port in config.TDX_SERVERS:
            try:
                api = TdxHq_API(heartbeat=True, auto_retry=True)
                if api.connect(host, port, time_out=config.TDX_TIMEOUT):
                    self.api = api
                    self.server = (host, port)
                    return
            except Exception:
                continue
        raise ConnectionError("无法连接任何通达信服务器，请检查网络或更换服务器列表")

    def ensure(self):
        """确保连接可用，断了自动重连。"""
        try:
            # 用一次轻量请求探活
            if self.api is None:
                self._connect()
                return
            ping = self.api.get_security_count(0)
            if ping is None:
                raise ConnectionError
        except Exception:
            try:
                if self.api:
                    self.api.disconnect()
            except Exception:
                pass
            self._connect()

    def call(self, func_name, *args, **kwargs):
        """通用调用：自动重试。"""
        last_err = None
        for attempt in range(config.TDX_RETRY + 1):
            try:
                self.ensure()
                func = getattr(self.api, func_name)
                res = func(*args, **kwargs)
                if res is not None:
                    return res
            except Exception as e:
                last_err = e
                time.sleep(0.3)
        if last_err:
            raise last_err
        return None

    def close(self):
        try:
            if self.api:
                self.api.disconnect()
        except Exception:
            pass


# 全局单例
_conn: Optional[TdxConn] = None


def get_conn() -> TdxConn:
    global _conn
    if _conn is None:
        _conn = TdxConn()
    return _conn


# ==================================================
# 市场代码工具
# ==================================================
def guess_market(code: str) -> int:
    """根据6位代码推断市场：0=深圳，1=上海。"""
    code = str(code).strip()
    if code.startswith(('5', '6', '9', '7')):   # 51/58/56 ETF、6 股票、5 沪基金
        return 1
    if code.startswith(('0', '1', '2', '3')):   # 15/16 深基金、00/30 股票
        return 0
    return 1


def split_code(full_code: str) -> Tuple[int, str]:
    """兼容 '159915' / '159915.XSHE' / 'SH510300' 三种写法。"""
    s = str(full_code).strip().upper()
    if s.endswith('.XSHE'):
        return 0, s.replace('.XSHE', '')
    if s.endswith('.XSHG'):
        return 1, s.replace('.XSHG', '')
    if s.startswith('SH'):
        return 1, s[2:]
    if s.startswith('SZ'):
        return 0, s[2:]
    return guess_market(s), s


# ==================================================
# 证券列表
# ==================================================
def list_all_etf() -> pd.DataFrame:
    """替代 get_all_securities(['fund'])。
    获取全市场 ETF 列表。优先腾讯/akshare，最后 pytdx。
    """
    # 1. 腾讯+akshare 组合（web_quote 内部先试 akshare 再试本地）
    try:
        df = web_quote.fetch_all_etf()
        if not df.empty:
            return df
    except Exception:
        pass

    # 2. pytdx 兜底
    if _HAS_PYTDX:
        df = _list_all_etf_tdx()
        if not df.empty:
            return df
    return pd.DataFrame(columns=['code', 'display_name'])


def _list_all_etf_tdx() -> pd.DataFrame:
    conn = get_conn()
    rows = []
    for market in (0, 1):
        count = conn.call('get_security_count', market)
        if not count:
            continue
        for start in range(0, count, 1000):
            part = conn.call('get_security_list', market, start)
            if not part:
                continue
            for item in part:
                code = str(item.get('code', '')).strip()
                name = str(item.get('name', '')).strip()
                vol_unit = item.get('volunit', 0)
                if _is_etf_code(code):
                    rows.append({
                        'code': code,
                        'display_name': name,
                        'market': market,
                        'volunit': vol_unit,
                    })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.drop_duplicates(subset=['code'], keep='first').reset_index(drop=True)


def _list_all_etf_ak() -> pd.DataFrame:
    """akshare ETF 列表（备用）。"""
    if not _HAS_AKSHARE:
        return pd.DataFrame(columns=['code', 'display_name'])
    try:
        spot = ak.fund_etf_spot_em()
    except Exception:
        return pd.DataFrame(columns=['code', 'display_name'])
    if spot is None or len(spot) == 0:
        return pd.DataFrame(columns=['code', 'display_name'])
    df = pd.DataFrame({
        'code': spot['代码'].astype(str),
        'display_name': spot['名称'].astype(str),
    })
    df = df[df['code'].apply(_is_etf_code)].drop_duplicates(subset=['code'])
    return df.reset_index(drop=True)


def _is_etf_code(code: str) -> bool:
    """是否是场内 ETF 代码。
    - 沪市：51xxxx / 56xxxx / 58xxxx（跨境/行业ETF）
    - 深市：159xxx / 16xxxx（LOF，酌情排除）
    这里只保留标准 ETF。
    """
    code = str(code)
    if len(code) != 6:
        return False
    if code.startswith(('51', '56', '58')):
        return True
    if code.startswith('159'):
        return True
    return False


def get_etf_name(code: str) -> str:
    market, c = split_code(code)
    res = get_conn().call('get_security_list', market, 0)
    return str(code)


# ==================================================
# K线数据
# ==================================================
def get_daily_kline(code: str, count: int = 120, end_date=None) -> pd.DataFrame:
    """替代 get_price(..., frequency='daily')。
    返回 DataFrame，列为 date/open/high/low/close/vol/amount，按时间升序。
    默认走腾讯前复权日线；失败降级 pytdx / akshare。
    """
    global _USE_AK

    # 0. 次方量化前复权（2026-10-20 新增）
    #    只接管历史日线；实时价仍走腾讯（实时价不需要复权）。
    #    失败不抛异常，继续走原降级链，保证信号不中断。
    if DATA_SOURCE == 'cifang':
        try:
            import cifang_quote
            df = cifang_quote.get_daily_kline(code, count=count, end_date=end_date)
            if df is not None and not df.empty:
                return df
        except Exception as _e:
            print('  [次方行情] %s 单只取数异常，回退原链路: %s' % (code, _e))

    # 1. 腾讯（主源）
    if DATA_SOURCE == 'web' or DATA_SOURCE == 'auto':
        df = web_quote.fetch_daily_kline(code, count=count, end_date=end_date)
        if not df.empty:
            return df

    # 2. pytdx
    if DATA_SOURCE in ('web', 'auto', 'tdx') and _HAS_PYTDX and not _USE_AK:
        df = _get_daily_kline_tdx(code, count, end_date)
        if not df.empty:
            return df
        if DATA_SOURCE == 'tdx':
            return df

    # 3. akshare
    if _HAS_AKSHARE and not _USE_AK:
        _USE_AK = True
    return _get_daily_kline_ak(code, count, end_date)


def _get_daily_kline_tdx(code: str, count: int = 120, end_date=None) -> pd.DataFrame:
    """pytdx 日线（备份）。"""
    empty = pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'vol', 'amount'])
    if not _HAS_PYTDX:
        return empty
    try:
        market, c = split_code(code)
        bars = get_conn().call('get_security_bars', 9, market, c, 0, min(count, 800))
    except Exception:
        return empty
    if not bars:
        return empty
    df = pd.DataFrame(bars).iloc[::-1].reset_index(drop=True)
    if 'datetime' in df.columns:
        df['date'] = pd.to_datetime(df['datetime']).dt.strftime('%Y-%m-%d')
    for col in ['date', 'open', 'high', 'low', 'close', 'vol', 'amount']:
        if col not in df.columns:
            df[col] = None
    df = df[['date', 'open', 'high', 'low', 'close', 'vol', 'amount']].copy()
    if end_date is not None:
        df = df[df['date'] <= str(end_date)].reset_index(drop=True)
    return df


def _get_daily_kline_ak(code: str, count: int = 120, end_date=None) -> pd.DataFrame:
    """akshare 日线（备用数据源）。"""
    empty = pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'vol', 'amount'])
    if not _HAS_AKSHARE:
        return empty
    try:
        df = ak.fund_etf_hist_em(symbol=str(code).split('.')[0], period='daily',
                                 adjust='qfq')
    except Exception:
        try:
            df = ak.stock_zh_a_hist(symbol=str(code).split('.')[0], period='daily',
                                    adjust='qfq')
        except Exception:
            return empty
    if df is None or len(df) == 0:
        return empty
    df = df.rename(columns={
        '日期': 'date', '开盘': 'open', '最高': 'high', '最低': 'low',
        '收盘': 'close', '成交量': 'vol', '成交额': 'amount',
    })
    for col in ['date', 'open', 'high', 'low', 'close', 'vol', 'amount']:
        if col not in df.columns:
            df[col] = None
    df = df[['date', 'open', 'high', 'low', 'close', 'vol', 'amount']].copy()
    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
    if end_date is not None:
        df = df[df['date'] <= str(end_date)].reset_index(drop=True)
    return df.tail(count).reset_index(drop=True)


def get_batch_daily_kline(codes: List[str], count: int = 120) -> Dict[str, pd.DataFrame]:
    """批量获取日线，用于池子构建/相关性去重。"""
    out = {}
    for code in codes:
        try:
            df = get_daily_kline(code, count=count)
            if not df.empty:
                out[code] = df
        except Exception:
            continue
    return out


# ==================================================
# 实时行情
# ==================================================
def get_realtime(codes: List[str]) -> pd.DataFrame:
    """替代 get_current_data()。返回字段：
    code/name/price/last_close/open/high/low/vol/amount/paused
    默认走腾讯实时行情；失败降级 pytdx / akshare。
    """
    global _USE_AK

    # 1. 腾讯（主源）
    #    ★ 'cifang' 也必须走这里：DATA_SOURCE 只决定「历史日线」用谁，
    #      实时价不需要复权，腾讯 qt 接口（与 501 的 ifzq 日线接口不同域）一直可用。
    if DATA_SOURCE in ('web', 'auto', 'cifang'):
        df = web_quote.fetch_realtime(codes)
        if not df.empty:
            return df

    # 2. pytdx
    if DATA_SOURCE in ('web', 'auto', 'tdx', 'cifang') and _HAS_PYTDX and not _USE_AK:
        df = _get_realtime_tdx(codes)
        if not df.empty:
            return df
        if DATA_SOURCE == 'tdx':
            return df

    # 3. akshare
    return _get_realtime_ak(codes)


def _get_realtime_tdx(codes: List[str]) -> pd.DataFrame:
    """pytdx 实时行情（备份）。"""
    if not _HAS_PYTDX:
        return pd.DataFrame()
    conn = get_conn()
    rows = []
    for i in range(0, len(codes), 80):
        batch = codes[i:i + 80]
        pairs = [split_code(c) for c in batch]
        try:
            data = conn.call('get_security_quotes', pairs)
        except Exception:
            data = None
        if not data:
            continue
        for item in data:
            price = item.get('price', 0) or 0
            last_close = item.get('last_close', 0) or 0
            vol = item.get('vol', 0) or 0
            code = str(item.get('code', '')).strip()
            paused = (price <= 0) or (vol <= 0 and last_close > 0
                                       and abs(price - last_close) < 1e-9)
            rows.append({
                'code': code, 'name': code,
                'price': float(price), 'last_close': float(last_close),
                'open': float(item.get('open', 0) or 0),
                'high': float(item.get('high', 0) or 0),
                'low': float(item.get('low', 0) or 0),
                'vol': float(vol), 'amount': float(item.get('amount', 0) or 0),
                'paused': bool(paused),
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.drop_duplicates(subset=['code'], keep='first').reset_index(drop=True)


def _get_realtime_ak(codes: List[str]) -> pd.DataFrame:
    """akshare 实时行情（备用数据源）。"""
    empty = pd.DataFrame()
    if not _HAS_AKSHARE:
        return empty
    try:
        spot = ak.fund_etf_spot_em()
    except Exception:
        return empty
    if spot is None or len(spot) == 0:
        return empty
    spot = spot.rename(columns={
        '代码': 'code', '名称': 'name', '最新价': 'price', '昨收': 'last_close',
        '开盘价': 'open', '最高价': 'high', '最低价': 'low',
        '成交量': 'vol', '成交额': 'amount',
    })
    spot['code'] = spot['code'].astype(str)
    sub = spot[spot['code'].isin([str(c).split('.')[0] for c in codes])].copy()
    for col in ['price', 'last_close', 'open', 'high', 'low', 'vol', 'amount']:
        if col not in sub.columns:
            sub[col] = 0.0
        sub[col] = pd.to_numeric(sub[col], errors='coerce').fillna(0.0)
    sub['paused'] = sub['price'] <= 0
    return sub[['code', 'name', 'price', 'last_close', 'open', 'high',
                'low', 'vol', 'amount', 'paused']].reset_index(drop=True)


# ==================================================
# 交易日历（pytdx 无接口，用本地推算 + 指数K线校验）
# ==================================================
def get_trade_dates(start_date=None, end_date=None) -> List[str]:
    """获取交易日列表。

    ★ 2026-11-02 修复：原实现用 sh000001（上证指数），但次方 `/fund/hist_em`
      只服务基金，**指数代码一律返回空** ⇒ 本函数长期返回 []，导致
      `engine.held_days()` 恒为 0、**「满 30 个交易日到期换仓」在线上从未生效**
      （与回测不一致）。现改用 510300（沪深300ETF）日K线日期做日历。
    """
    df = get_daily_kline('510300', count=800)
    if df is None or df.empty:
        df = get_daily_kline('159967', count=800)     # 备选日历源
    if df is None or df.empty:
        return []
    dates = df['date'].tolist()
    if start_date is not None:
        dates = [d for d in dates if d >= str(start_date)]
    if end_date is not None:
        dates = [d for d in dates if d <= str(end_date)]
    return dates


def latest_trade_date() -> str:
    df = get_daily_kline('SH000001', count=5)
    if df.empty:
        return _dt.date.today().strftime('%Y-%m-%d')
    return df['date'].iloc[-1]


# ==================================================
# 规模/份额（pytdx 无法直接取，用成交额近似）
# ==================================================
def estimate_scale(code: str, close: float, shares_map: Dict[str, float]) -> Optional[float]:
    """规模估算：份额 × 收盘价 / 1e8（亿元）。
    shares_map 需外部维护（可从集思录/交易所导出后加载）。
    """
    if code not in shares_map:
        return None
    return float(shares_map[code]) * float(close) / 1e8
