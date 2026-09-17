# 贡献指南

感谢你愿意为「知乎盐选小说下载器」做出贡献！本文档说明如何搭建开发环境、跑测试、提交 PR。

## 开发环境

```bash
git clone https://github.com/xfengyin/zhihu-salt-novel-downloader.git
cd zhihu-salt-novel-downloader

# 推荐使用 uv（项目自带 uv.lock）
uv sync --all-groups

# 或使用 pip
pip install -e ".[dev]"
```

## 运行测试

```bash
uv run pytest                 # 全部测试
uv run pytest tests/test_qr.py -v   # 单个模块
```

## 代码规范

提交前请确保通过：

```bash
uv run black src tests
uv run isort src tests
uv run flake8 src tests
uv run mypy src
```

## 提交 PR

1. Fork 仓库并创建分支：`git checkout -b fix/xxx` 或 `feat/xxx`
2. 提交信息遵循 [Conventional Commits](https://www.conventionalcommits.org/)：
   - `feat: 新增 xxx`
   - `fix: 修复 xxx`
   - `docs: 更新 xxx`
3. 确保 `pytest` 全部通过
4. 发起 PR，并在描述里关联相关 Issue

## 安全与合规

- **不要**在 Issue / PR / 提交里粘贴真实 Cookie（`z_c0` / `zse_ck`）
- 本工具仅限**已购买内容的个人离线阅读**，请勿提交任何绕过付费墙的功能
- 安全相关问题请勿公开开 Issue，参考 [SECURITY.md](SECURITY.md)

## 常见开发要点

- 认证：`src/zhihu_downloader/auth/`（cookies / qr / browser / doctor）
- 解析：`src/zhihu_downloader/parse/`（cleaner / parser / urltype / classifier）
- 引擎：`src/zhihu_downloader/engine/`（client / fetcher / checkpoint）
- 导出：`src/zhihu_downloader/export/`（txt / md / epub）
- Web UI：`src/zhihu_downloader/app/`（FastAPI + 原生前端）
