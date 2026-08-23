# 知乎盐选小说下载器 v4（极简版）

极简 v4：只保留核心能力 —— 扫码登录、Cookie 管理、下载、导出、极简 Web API。
同步、易读、易维护，让用户 1 分钟跑起来。

## 项目简介

知乎盐选小说下载器 v4 是一个极简版下载工具：

- 扫码登录知乎（自动保存 Cookie）
- 下载盐选专栏 / 单章节（`market/paid_column` 链接）
- 导出 `txt` / `md` / `epub`
- 内置极简 Web UI（可选）

> 仅限已购买内容的个人离线阅读，请勿用于分发、商用或侵权传播。

## 安装

```bash
cd simple

# 方式一：pip
pip install -r requirements.txt

# 方式二：uv pip install
uv pip install -r requirements.txt
```

> 需要 Python 3.10+。`epub` 导出依赖 `ebooklib`（已包含在 requirements.txt 中）。

## 使用

```bash
cd simple

# 1. 扫码登录（Cookie 保存到 ~/.zhihu_downloader/cookies.json）
python -m zhihu_downloader qr-login

# 2. 下载盐选专栏 / 章节
python -m zhihu_downloader download --url <盐选链接> --format txt

# 3. 启动 Web UI（可选）
python -m zhihu_downloader web
```

也可以安装为命令行工具后直接调用 `zhihu-downloader`：

```bash
pip install .
zhihu-downloader qr-login
zhihu-downloader download --url <盐选链接> --format epub
```

### 扫码登录（qr-login）

```bash
python -m zhihu_downloader qr-login
```

命令会：

1. 生成登录二维码（临时图片路径会打印在终端）；
2. 用知乎 App 扫码并确认；
3. 成功后自动保存 Cookie 到 `~/.zhihu_downloader/cookies.json`。

### 下载（download）

```bash
# 下载盐选单章节
python -m zhihu_downloader download \
  --url "https://www.zhihu.com/market/paid_column/<专栏ID>/section/<章节ID>" \
  --format md

# 下载整个盐选专栏
python -m zhihu_downloader download \
  --url "https://www.zhihu.com/market/paid_column/<专栏ID>" \
  --format epub
```

可选参数：

| 参数 | 说明 |
|------|------|
| `--url` | 盐选章节 / 专栏 URL（必填） |
| `--format` | `txt` / `md` / `epub`，默认 `md` |
| `--output-dir` | 输出目录，默认当前目录 `.` |
| `--cookie-file` | 自定义 Cookie 文件路径（默认 `~/.zhihu_downloader/cookies.json`） |
| `--token` | 直接传 `z_c0` token（优先级高于 cookie-file） |

### Web UI（web）

```bash
python -m zhihu_downloader web
```

启动后打开 <http://127.0.0.1:3000>：

1. 点击「扫码登录」→ 用知乎 App 扫码确认；
2. 粘贴盐选链接 → 选择格式 → 开始下载；
3. 下载完成后查看 / 下载导出文件。

> Web UI 的静态页面由前端实现填充（`zhihu_downloader/static/`）。

## 支持格式

| 格式 | 说明 |
|------|------|
| `txt` | 纯文本，单文件 |
| `md` | Markdown，带标题与来源链接 |
| `epub` | 电子书，每章一个章节 |

## Cookie 保存位置

扫码登录成功后，Cookie 自动保存到：

```
~/.zhihu_downloader/cookies.json
```

Cookie 属敏感信息，请勿外泄。删除该文件即可清除登录态。

## FAQ

- **403 反爬拦截**：确认账号具备盐选阅读权限（已购买 / 会员），并确认 Cookie 有效
  （重新运行 `qr-login`，确保 Cookie 含 `z_c0` / `zse_ck`）。
- **二维码过期**：登录二维码有时效，过期后重新运行 `python -m zhihu_downloader qr-login` 获取新二维码。
- **只支持 market/paid_column 链接**：本工具只支持知乎盐选
  （`www.zhihu.com/market/paid_column/...`）章节与专栏链接，公开回答、专栏文章等其他链接暂不支持。

## 目录结构

```
simple/
├── zhihu_downloader/     # v4 包（cli/client/parser/exporters/signature/webapp）
├── tests/                # 单元测试
├── requirements.txt
└── pyproject.toml
```

## License

MIT License（同根项目）。
