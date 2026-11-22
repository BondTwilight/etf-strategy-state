# -*- coding: utf-8 -*-
"""ai_note.py —— 用 DeepSeek 给「今天的数字」写一段解读，写进 state.json

为什么放在构建期、不放在浏览器：
  1) key 不进前端（前端放 key 等于公开）；
  2) 公开页是匿名访问，模型接口一般要求登录态，浏览器直连大概率 401；
  3) 解读和数字同一次生成，不会出现「数字是今天的、解读是三周前的」。

纪律：
  - 只喂已经算好的事实（今日动作、持仓、环境判据、行业强弱、恒方换仓、健康告警）；
  - 提示词里明确禁止编造数字、禁止给买卖建议，只做「解释 + 需要盯什么」；
  - 没有 DEEPSEEK_KEY 时静默跳过，state.json 里就不出现 ai_note，页面也就不显示。

用法：
  DEEPSEEK_KEY=sk-xxx python tools/ai_note.py [data/state.json]
"""
import datetime
import json
import os
import sys
import urllib.request

API = "https://api.deepseek.com/chat/completions"

SYS = (
    "你是量化策略看板的解读员。你只读数据、只解释，不做投资建议、不预测涨跌。"
    "硬性要求："
    "① 只能使用用户给的数据里出现过的数字，一个都不许自己造；"
    "② 不写「建议买入/卖出」「必然」「一定」这类词；"
    "③ 用中文，3~5 条，每条不超过 45 字，句尾不要加句号；"
    "④ 第一条必须直接说今天要不要动手、动哪只；"
    "⑤ 如果数据里有口径退化（caliberWarn）或健康告警，必须单独用一条指出来。"
)


def digest(s):
    """把 state.json 压成模型能读的一小段事实，避免把 121KB 全塞进去。"""
    L = []
    m = s.get("meta") or {}
    L.append("日期：数据日 %s，构建于 %s" % (s.get("data_date"), s.get("built_at")))
    rg = s.get("regime") or {}
    L.append("环境：%s %s（%s/%s 条判据触发）"
             % (rg.get("code"), rg.get("label"), rg.get("hits"), rg.get("n")))
    mk = s.get("market") or {}
    if mk:
        L.append("市场状态：%s %s，置信 %s%%" % (mk.get("state"), mk.get("score"), mk.get("conf")))

    act = s.get("action") or {}
    items = [x for x in (act.get("items") or []) if x.get("code")]
    if items:
        L.append("今日动作：" + "；".join(
            "%s %s %s %s" % ("卖" if x.get("side") == "sell" else "买",
                             x.get("code"), x.get("name") or "",
                             (x.get("why") or "")[:40]) for x in items[:3]))
    else:
        L.append("今日动作：无（%s）" % (act.get("head") or "规则未触发"))

    for x in (s.get("items") or [])[:6]:
        L.append("持仓：%s %s 浮盈 %s%% 距止损 %s%%"
                 % (x.get("s"), x.get("code"), x.get("pnl"),
                    x.get("dist") if x.get("dist") is not None else "无止损"))

    ind = s.get("industry") or {}
    top = (ind.get("industries") or [])[:2]
    bot = (ind.get("industries") or [])[-2:]
    if top:
        L.append("行业最强：" + "、".join("%s %+.1f%% 广度 %s%%" % (x["k"], x["r20"], x["br20"]) for x in top))
    if bot:
        L.append("行业最弱：" + "、".join("%s %+.1f%% 广度 %s%%" % (x["k"], x["r20"], x["br20"]) for x in bot))

    it = s.get("intel") or {}
    if it.get("products"):
        chg = [p for p in it["products"] if p.get("chg") == "switch"]
        L.append("恒方：%s/%s 有信号，换仓 %d 个，信号日 %s"
                 % (it.get("n_sig"), it.get("n"), len(chg), it.get("date")))

    cw = s.get("caliberWarn") or []
    if cw:
        L.append("口径退化：" + "；".join(cw[:3]))

    hl = [x for x in (s.get("health") or []) if x.get("s") != "ok"]
    if hl:
        L.append("健康告警：" + "；".join("%s（%s）" % (x.get("k"), x.get("v", "")[:36]) for x in hl[:3]))
    return "\n".join(L)


def main():
    p = sys.argv[1] if len(sys.argv) > 1 else os.path.join("data", "state.json")
    if not os.path.exists(p):
        print("没有 %s，跳过" % p)
        return
    key = (os.environ.get("DEEPSEEK_KEY") or "").strip()
    if not key:
        print("未配置 DEEPSEEK_KEY，跳过 AI 解读")
        return

    s = json.load(open(p, encoding="utf-8"))
    facts = digest(s)
    body = {
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        "messages": [{"role": "system", "content": SYS},
                     {"role": "user", "content": "今天的事实：\n" + facts}],
        "temperature": 0.2,
        "max_tokens": 700,
        "stream": False,
    }
    req = urllib.request.Request(
        API, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=120).read().decode("utf-8"))
        txt = (r["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        print("[警告] 模型调用失败，state 不带 ai_note：%r" % (e,))
        return
    if not txt:
        print("[警告] 模型返回空，跳过")
        return

    s["ai_note"] = {"text": txt, "model": body["model"],
                    "at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    with open(p, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, separators=(",", ":"))
    print("已写入 ai_note（%d 字）" % len(txt))
    print(txt[:300])


if __name__ == "__main__":
    main()
