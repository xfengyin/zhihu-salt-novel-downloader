# Zhihu Salt-Novel Downloader v4 (Minimal Edition)

[![CI](https://github.com/xfengyin/zhihu-salt-novel-downloader/actions/workflows/ci-simple.yml/badge.svg)](https://github.com/xfengyin/zhihu-salt-novel-downloader/actions/workflows/ci-simple.yml)
[![Release](https://img.shields.io/github/v/release/xfengyin/zhihu-salt-novel-downloader)](https://github.com/xfengyin/zhihu-salt-novel-downloader/releases)
[![Stars](https://img.shields.io/github/stars/xfengyin/zhihu-salt-novel-downloader)](https://github.com/xfengyin/zhihu-salt-novel-downloader)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/xfengyin/zhihu-salt-novel-downloader/blob/master/LICENSE)

The minimal v4 keeps only the core capabilities: QR-code login, cookie management,
downloading, exporting, and a minimal Web API.
Synchronous, readable, and easy to maintain — get started in about a minute.

## Project Overview

Zhihu Salt-Novel Downloader v4 is a minimal downloader that:

- Logs in to Zhihu via QR code (cookies are saved automatically)
- Downloads salt-novel columns / single sections (`market/paid_column` links)
- Exports to `txt` / `md` / `epub`
- Ships an optional minimal Web UI

> For personal offline reading of content you have already purchased only.
> Do not redistribute, commercialize, or infringe copyright.

## Features

- 🔐 **QR-code login**: Scan once with the Zhihu app; cookies are saved automatically
  to `~/.zhihu_downloader/cookies.json` — no manual copying.
- 📥 **Download salt-novel content**: Single sections and entire columns
  (`market/paid_column` links).
- 📦 **Multiple export formats**: `txt` / `md` / `epub` for readers, typesetting,
  and e-book workflows.
- 🐢 **Rate-limited by default**: 2 requests/second by default (tunable via
  `--rate-limit`, minimum 0.5) — polite to the platform.
- 🛡️ **Request signing**: Automatically injects the `x-zse-96` signature header to
  reduce the chance of anti-crawling blocks (requires valid cookies).
- 🌐 **Minimal Web UI** (optional): scan, paste a link, and download from the browser.
- 🖥️ **Full-featured CLI**: `qr-login` / `download` / `web` subcommands, plus
  `--version`.
- ⚡ **1-minute setup**: Pure Python 3.10+, few dependencies,
  `pip install -r requirements.txt` and go.

## Compliance & Usage Restrictions

Please read the following restrictions carefully before using this tool:

- **Authorized content only**: You may only download salt-novel content that you have
  purchased, subscribed to, or are otherwise authorized to access — for personal
  offline reading only.
- **Rate-limited by default**: Downloads are rate-limited to 2 requests/second by
  default (adjustable via `--rate-limit`, minimum 0.5). Do not raise it unreasonably
  to circumvent platform limits.
- **No paywall bypass**: This tool does not crack or bypass any paywall or access
  check; content you have not purchased or are not authorized to read cannot be
  downloaded.
- **Terms of service**: You must comply with the
  [Zhihu Terms of Service](https://www.zhihu.com/terms) and applicable laws
  (e.g. China's Copyright Law).
- **No redistribution**: Redistribution, commercial use, or any other form of
  copyright infringement of downloaded content is prohibited.

> By using this tool you agree to the restrictions above; any legal risk arising
> from misuse is borne by the user.

## Installation

```bash
cd simple

# Option 1: pip
pip install -r requirements.txt

# Option 2: uv pip install
uv pip install -r requirements.txt
```

> Requires Python 3.10+. `epub` export depends on `ebooklib` (already included in
> requirements.txt).

## Usage

```bash
cd simple

# 1. QR-code login (cookies are saved to ~/.zhihu_downloader/cookies.json)
python -m zhihu_downloader qr-login

# 2. Download a salt-novel column / section
python -m zhihu_downloader download --url <salt-novel-url> --format txt

# 3. Start the Web UI (optional)
python -m zhihu_downloader web

# 4. Show the version
python -m zhihu_downloader --version
```

You can also install it as a command-line tool and call `zhihu-downloader` directly:

```bash
pip install .
zhihu-downloader qr-login
zhihu-downloader download --url <salt-novel-url> --format epub
```

### QR-code login (qr-login)

```bash
python -m zhihu_downloader qr-login
```

This command will:

1. Generate a login QR code (the temporary image path is printed to the terminal);
2. Scan and confirm it with the Zhihu app;
3. On success, automatically save cookies to `~/.zhihu_downloader/cookies.json`.

**QR-code login flow:**

```text
Terminal generates QR code → scan with the Zhihu app → confirm in the app
      ↓
Cookies auto-saved to ~/.zhihu_downloader/cookies.json → reused by later downloads
```

- The QR code is saved as a temporary `.jpg` file and its path is printed; open it
  with any image viewer to scan.
- The QR code expires after a few minutes; re-run `qr-login` to get a fresh one.
- The login session stays valid until the cookies expire or you delete
  `~/.zhihu_downloader/cookies.json`.

### Download (download)

```bash
# Download a single salt-novel section
python -m zhihu_downloader download \
  --url "https://www.zhihu.com/market/paid_column/<column-id>/section/<section-id>" \
  --format md

# Download an entire salt-novel column
python -m zhihu_downloader download \
  --url "https://www.zhihu.com/market/paid_column/<column-id>" \
  --format epub
```

Available options:

| Option | Description |
|--------|-------------|
| `--url` | Salt-novel section / column URL (required) |
| `--format` | `txt` / `md` / `epub`, default `md` |
| `--output-dir` | Output directory, default current directory `.` |
| `--cookie-file` | Custom cookie file path (default `~/.zhihu_downloader/cookies.json`) |
| `--token` | Pass the `z_c0` token directly (takes precedence over `cookie-file`) |
| `--rate-limit` | Max requests per second (default 2, minimum 0.5); applies to every request during a download |

### Web UI (web)

```bash
python -m zhihu_downloader web
```

Open <http://127.0.0.1:3000> after startup:

1. Click "QR-code login" and scan with the Zhihu app;
2. Paste a salt-novel link, choose a format, and start the download;
3. View / download the exported files when finished.

> The Web UI static pages are served from `zhihu_downloader/static/`.

## Terminal Demo

> The terminal output below is a simulated example, not a real screenshot; actual
> output depends on your account and network.

```text
$ python -m zhihu_downloader --version
zhihu-downloader 4.2.0

$ python -m zhihu_downloader qr-login
请用知乎 APP 扫码登录，二维码图片路径: /tmp/tmpa1b2c3.jpg
等待扫码确认中...
登录成功 user_id=1234567890，Cookie 已保存到 /root/.zhihu_downloader/cookies.json

$ python -m zhihu_downloader download \
    --url "https://www.zhihu.com/market/paid_column/123456789/section/987654321" \
    --format epub
标题: 《盐选小说 · 示例章节》
已导出: ./盐选小说 · 示例章节.epub

$ python -m zhihu_downloader web
INFO:     Uvicorn running on http://127.0.0.1:3000 (Press CTRL+C to quit)
```

> English output note: the CLI currently prints Chinese messages (e.g. login and
> download progress); command names, options, and formats are language-neutral.

## Supported Formats

| Format | Description |
|--------|-------------|
| `txt` | Plain text, single file |
| `md` | Markdown, with title and source link |
| `epub` | E-book, one chapter per section |

## Cookie Storage

After a successful QR-code login, cookies are automatically saved to:

```
~/.zhihu_downloader/cookies.json
```

Cookies are sensitive — never share them. Delete this file to clear the login state.

## FAQ

- **HTTP 403 (anti-crawling block)**: Make sure your account has salt-novel reading
  permission (purchased / membership) and that your cookies are valid (re-run
  `qr-login`; ensure cookies contain `z_c0` / `zse_ck`).
- **QR code expired**: Login QR codes are time-limited. Re-run
  `python -m zhihu_downloader qr-login` to get a fresh one.
- **Only `market/paid_column` links are supported**: This tool supports Zhihu
  salt-novel (`www.zhihu.com/market/paid_column/...`) sections and columns only;
  public answers, column articles and other links are not supported.

## Directory Structure

```
simple/
├── zhihu_downloader/     # v4 package (cli/client/parser/exporters/signature/webapp)
├── tests/                # unit tests
├── requirements.txt
└── pyproject.toml
```

## License

MIT License (same as the root project).
