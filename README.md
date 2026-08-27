# 越野车行业四源爬虫（GitHub Actions 定时版）

每天定时抓取四个权威官方源，落盘为 JSON + Markdown，通过 Actions Artifact 下载查看。

## 四个来源
| # | 来源 | 说明 |
| --- | --- | --- |
| 1 | 工信部 | 汽车申报/公告（CMS 动态加载，走接口） |
| 2 | 缺陷产品召回中心 | 国内汽车召回备案 |
| 3 | 全国汽标委 CATARC | 标准发布/解读/制修订 |
| 4 | 国家标准委 | 强制性/推荐性国标（按关键词过滤出汽车相关） |

时间窗口：近 30 天。

## 文件说明
- `spider.py` —— 爬虫主体，抓取 + 写 `spider_result.json` / `spider_result.md`
- `requirements.txt` —— 依赖（requests + beautifulsoup4）
- `.github/workflows/auto_spider.yml` —— 定时任务（北京时间每天 9:00，UTC 1:00）

## 如何查看结果
1. GitHub 仓库 → **Actions** 标签页 → 选中最近一次运行
2. 页面底部 **Artifacts** → 下载 `spider-result`，里面就是 `spider_result.json` 和 `spider_result.md`

## 修改定时时间
编辑 `.github/workflows/auto_spider.yml` 里的 `cron`（UTC 时间）。
北京时间 = UTC + 8 小时。例如想在北京时间 9:00 跑，填 `0 1 * * *`。

## 注意事项
- 定时任务只会在**默认分支**上生效，代码要 push 到 `main`（或你的默认分支）。
- GitHub 免费版定时任务可能因排队延迟几分钟到几小时，属正常现象。
- 运行环境在美国机房，个别国内政府网站偶尔响应慢，失败源会在报告里标出，不影响其它源。
