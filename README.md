# PIS · Personal Information Source

每天早上 8 点前，在 Notion「PIS」页面下自动生成一个以日期命名的简报页面。全程运行在 GitHub Actions 上，
不依赖你的电脑或任何账号在线。系统会记住你的兴趣变化，越用越懂你。

**每日页面长这样**
- 📌 头条 callout → ⏱ 30 秒速览 → 目录
- 按 *主题*（而不是按来源）组织的段落：综合比较多篇工作、讲清机制，正文中蓝色 **[n]** 可直接点开原文
- 每个主题下附「💬 对你」的意义/下一步建议，以及最值得点开那一篇的预览卡片（bookmark）
- 🧵 线索追踪：记忆中你在跟进的方向今天有什么新进展
- ▸ 🗺 今日图谱（Mermaid 图，主题 → 条目）  ▸ 📋 全部条目一览（表格）
- 子页面「📄 论文精选 / 🌐 动态与博客 / 📌 我的收藏」：每条是一个 ☐ 复选框，勾选即“想深读”

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
   会创建「🧭 研究画像」「🧠 记忆」两个页面和「📥 Inbox」数据库，并打印 4 个 ID。
4. **GitHub**：把本项目推到一个 **私有** 仓库 → Settings → Secrets and variables → Actions，添加 Secrets：
   `DEEPSEEK_API_KEY`、`NOTION_TOKEN`、`NOTION_PIS_PAGE_ID`、`NOTION_PROFILE_PAGE_ID`、`NOTION_MEMORY_PAGE_ID`、`NOTION_INBOX_DB_ID`；
   可选 Variable `DEEPSEEK_MODEL`（默认 `deepseek-chat`；DeepSeek 近期模型名变动频繁，请以官网模型列表为准）。
5. **试跑**：Actions → *PIS daily digest* → Run workflow。之后每天自动运行。

本地调试（不写 Notion，只输出 Markdown 到 `out/`）：
```bash
DEEPSEEK_API_KEY=sk-xxx python -m pis.main --dry-run
```

## 个性化：画像 + 记忆
| | 🧭 研究画像 | 🧠 记忆 |
|---|---|---|
| 谁来写 | 你 | PIS 自动维护 |
| 变化速度 | 慢（研究方向） | 快（近期热点、正在跟进的线索） |
| 信号来源 | 你的手写描述 | 📥 Inbox 收藏与备注（强）、每日页面里 ☑ 勾选（强）、近几日推送主题（弱，仅用于线索承接） |

每次运行：读取画像 + 记忆 + 前 3 天新勾选的条目 → 用于打分和写摘要 → 生成页面后再让 DeepSeek 更新记忆
（兴趣权重、趋势 📈/📉、14 天无信号自动衰减、跟进线索、阅读偏好）。记忆页上半部分是可读表格，
底部折叠的 JSON 是机器读取的数据源。只被推送、没被勾选的内容 **不会** 提高兴趣权重，避免“越推越窄”的自我强化。

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
