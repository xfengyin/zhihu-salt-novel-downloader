# Reddit r/Python 帖子（最终稿，可直接发布）

> 发布地址：https://www.reddit.com/r/Python/submit
> 标题（Title）：`[P] A minimal CLI to export purchased Zhihu salt-novel content (qr-login, txt/md/epub, rate-limited, MIT)`
> 发布纪律：只发一次；遵守 subreddit 自荐比例规则。

---

**Title**: [P] A minimal CLI to export purchased Zhihu salt-novel content (qr-login,
txt/md/epub, rate-limited, MIT)

**Body**:

I built a small synchronous Python CLI for Zhihu (知乎) paid columns: scan to log
in, then download sections or whole columns you purchased, export to txt/md/epub.
No scraping tricks – it uses the same signed requests a normal browser session
would, is rate-limited by default (2 req/s), and explicitly does NOT bypass
paywalls (purchased content only, personal offline use).

Repo: https://github.com/xfengyin/zhihu-salt-novel-downloader

Happy to hear feedback on the code – it's deliberately minimal and readable.
