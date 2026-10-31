# PIS · Personal Information Source

每天早上 8 点前，在 Notion「PIS」页面下自动生成一个以日期命名的页面：
一段按主题组织、带可点击出处编号的中文摘要，外加「📄 论文精选 / 🌐 动态与博客 / 📌 我的收藏」三个子页面。

```
 GitHub Actions（每天 07:30 北京时间）
   │
   ├─ arXiv 每日公告 RSS（cs.CL/LG/AI/CV…）──┐
   ├─ HF Daily Papers（热度 upvotes）────────┤
   ├─ RSS：官方博客 / RSSHub(X·知乎·小红书) / wewe-rss(公众号) ┤
   └─ Notion「📥 Inbox」：你手动收藏的链接（公众号等）──────┘
                     │
         关键词粗筛 → DeepSeek 按「🧭 研究画像」逐条打分 → 取 Top-K
                     │
         DeepSeek 生成主题化摘要（[n] 引用 → 原文链接）
                     │
         Notion：PIS / 2026-10-31 / {论文精选, 动态与博客, 我的收藏}
```

## 部署（约 15 分钟）

1. **Notion 集成**：打开 <https://www.notion.so/profile/integrations> → New integration（Internal）→ 复制 token（`ntn_…`）。
2. **PIS 页面**：在 Notion 新建页面「PIS」→ 右上角 `···` → Connections → 添加刚才的集成。
3. **初始化子结构**（本地执行一次）：
   ```bash
   pip install -r requirements.txt
   NOTION_TOKEN=ntn_xxx python setup_notion.py "<PIS 页面链接>"
   ```
   会创建「🧭 研究画像」页面（内容来自 `config/profile.md`）和「📥 Inbox」数据库，并打印 3 个 ID。
4. **GitHub**：把本项目推到一个 **私有** 仓库 → Settings → Secrets and variables → Actions，添加：
   `DEEPSEEK_API_KEY`、`NOTION_TOKEN`、`NOTION_PIS_PAGE_ID`、`NOTION_PROFILE_PAGE_ID`、`NOTION_INBOX_DB_ID`
5. **试跑**：Actions → *PIS daily digest* → Run workflow。之后每天自动运行。

本地调试（不写 Notion，只输出 Markdown 到 `out/`）：
```bash
DEEPSEEK_API_KEY=sk-xxx python -m pis.main --dry-run
```

## 更新研究兴趣
直接编辑 Notion 里的「🧭 研究画像」页面，下次运行即生效（`config/profile.md` 仅作兜底）。

## 把公众号文章送进 PIS（📥 Inbox）
个人微信没有开放接口，「转发到文件传输助手/自己聊天框」的内容无法被云端稳定读取。推荐把“转发”换成一键“分享到 Inbox”：

- **iOS 快捷指令**（最顺手）：新建快捷指令，开启“在共享表单中显示”，接收 URL/文本 →
  「获取 URL 内容」：`POST https://api.notion.com/v1/pages`，请求头
  `Authorization: Bearer <NOTION_TOKEN>`、`Notion-Version: 2022-06-28`、`Content-Type: application/json`，JSON 正文：
  ```json
  {"parent": {"database_id": "<NOTION_INBOX_DB_ID>"},
   "properties": {"Name": {"title": [{"text": {"content": "<快捷指令输入>"}}]},
                  "URL": {"url": "<快捷指令输入>"}}}
  ```
  在公众号文章右上角 `···` →「在 Safari 中打开」或「复制链接」，再从分享菜单选这个快捷指令即可。
- **Android**：用 *HTTP Shortcuts* 之类的 App 配同样的请求，或直接用 Notion App 的“分享到 Notion”选择 Inbox 数据库。
- **电脑端**：Notion Web Clipper 保存到 Inbox。
- 可在 `Note` 字段写一句“为什么收藏”，摘要会参考它。

## 接入更多社交平台
在 `config/sources.yaml` 的 `feeds.list` 里加 RSS 地址即可：
- **X / 知乎 / 小红书**：自建 [RSSHub](https://docs.rsshub.app)（需各平台 cookie，小红书/知乎反爬强，路由时常失效）。
- **公众号订阅**：自建 [wewe-rss](https://github.com/cooderl/wewe-rss)（基于微信读书，适合固定订阅几十个号）。
- 这两者需要一台常驻服务器（轻量云 / NAS / 家里常开的电脑均可）。

## 成本
每天约几十万输入 token（800 篇摘要打分 + 1 次总结），按 DeepSeek 官网价格量级在每天 1 元以内。
GitHub Actions 私有仓库每月 2000 分钟免费额度，本任务每天约 3-5 分钟。
