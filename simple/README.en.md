# Zhihu Salt-Novel Downloader v4 (Minimal Edition)

[![CI](https://github.com/xfengyin/zhihu-salt-novel-downloader/actions/workflows/ci-simple.yml/badge.svg)](https://github.com/xfengyin/zhihu-salt-novel-downloader/actions/workflows/ci-simple.yml)

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
