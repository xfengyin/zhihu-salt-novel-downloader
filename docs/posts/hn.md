# Show HN 帖子（最终稿，可直接发布）

> 发布地址：https://news.ycombinator.com/submit
> 标题（Title）：Show HN: Zhihu Salt-Novel Downloader – a minimal CLI for your purchased Zhihu content
> 建议发布时间：UTC 13:00–15:00（美东早间）
> 发布纪律：只发一次；发完可在评论区自评一句（欢迎指正签名/限速部分）。

---

Show HN: Zhihu Salt-Novel Downloader – a minimal CLI for your purchased Zhihu content

Zhihu (知乎) hosts paid "salt-novel" (盐选) columns. There was no simple way to
export content you have legitimately purchased for offline reading.

This is a minimal, dependency-light Python CLI (one package, ~5 files):

- QR-code login with the official flow (cookies saved locally)
- Download single sections or whole columns (market/paid_column links)
- Export to txt / md / epub
- Rate-limited by default (2 req/s), no paywall bypass, purchased content only

Everything is synchronous and readable on purpose. MIT licensed.

https://github.com/xfengyin/zhihu-salt-novel-downloader

Compliance: only content you purchased/subscribed to, personal offline use,
no redistribution, respects Zhihu's ToS (see README).
