# ETF 策略看板 · 云端数据仓库

这个仓库**不含策略源码以外的任何数据**，它的唯一作用是：

> 每个交易日 15:10（北京时间）由 GitHub Actions 跑一遍本机的同一条链路，
> 把结果写成 `data/state.json` 提交回来。看板页面拉这份文件覆盖内嵌快照。

## 一次性配置（4 步）

1. 在 GitHub 新建一个 **Public** 空仓库（公开才有无限 Actions 分钟数，raw 才能被页面直连）。
2. 把本目录推上去：

   ```bash
   git init
   git add .
   git commit -m "init"
   git branch -M main
   git remote add origin https://github.com/<你的用户名>/<仓库名>.git
   git push -u origin main
   ```

3. 仓库 → Settings → Secrets and variables → Actions → New repository secret
   - `CIFANG_KEY`（**必需**）：你的次方 API Key（`ak_...`）
   - `DEEPSEEK_KEY`（可选）：填了就每天多一段 AI 解读；不填这一步自动跳过

4. 仓库 → Actions → 选 `daily-state` → Run workflow 手动跑一次，确认绿勾。
   **第一次会慢（约 6~10 分钟）**：要全量建 381 池 14:45 库 + 21 只分时库。
   之后有 cache，每天只补新增那一段，约 3 分钟。

## 拿到地址后

页面要用的地址是：

```
https://raw.githubusercontent.com/<用户名>/<仓库名>/main/data/state.json
```

把它写进本机 `量化agent/hub/state_url.txt`（一行），然后重新构建 + 发布：

```bat
cd hub
python _build_live.py
```

（或直接跑 `etf_dip_signal\daily_refresh.py --force`，链路里带这一步）

## 每天怎么确认它跑了

- 仓库首页的 commit 记录：每天应该多一条 `state: 2026-11-23 15:12`
- Actions 页面：绿勾 = 成功，红叉点进去看是哪一步
- 看板右上角：显示「云端 11-23 15:12 已同步 · 数据日 2026-11-21」= 拉到的是云端新数据
