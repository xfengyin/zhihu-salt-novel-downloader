# 贡献指南（Contributing）

感谢你愿意为 zhihu-salt-novel-downloader 贡献代码、文档或反馈。
本文档覆盖：报 issue / 提 PR / 本地开发 / 测试 / 合规边界。

> 本项目定位是「极简 v4」：**刻意保持同步、简单、可读、易维护**。
> 任何改动都应遵循这一设计取向，拒绝过度工程化。

---

## 1. 快速开始（本地开发）

环境要求：Python 3.10+（推荐 3.12）。

```bash
# 1. 克隆并进入 simple 目录
git clone https://github.com/xfengyin/zhihu-salt-novel-downloader.git
cd zhihu-salt-novel-downloader/simple

# 2. 创建虚拟环境并安装依赖
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .                 # 安装包本体（可编辑模式）
pip install pytest               # 测试依赖（requirements.txt 不含）

# 3. 跑测试（必须全绿再提交）
python -m pytest -q

# 4. 冒烟验证
python -m zhihu_downloader --help
python -m zhihu_downloader --version
```

## 2. 代码规范

- **风格**：与现有代码一致（`simple/zhihu_downloader/` 现有模块风格），保持同步、无异步魔法。
- **依赖**：尽量不加新依赖；确实需要时在 `simple/requirements.txt` 与 `simple/pyproject.toml` 同步更新，并说明理由。
- **错误信息**：面向用户的错误用中文可读信息（如 `ZhihuError`）。
- **文档**：新命令 / 新参数 / 新格式必须同步更新 `simple/README.md` 与 `simple/README.en.md`。
- **测试**：新功能必须带单元测试（`simple/tests/`，网络请求一律 mock，参考 `tests/test_client.py`）。

## 3. 如何报 issue

请使用 GitHub Issue 模板（仓库已配置）：

- **Bug**：`.github/ISSUE_TEMPLATE/bug_report.md` —— 描述问题、复现步骤、环境
  （含 `python -m zhihu_downloader --version` 输出）、日志（敏感信息请打码）。
- **功能建议**：`.github/ISSUE_TEMPLATE/feature_request.md` —— 解决问题、期望行为、
  替代方案，并完成**合规自查**勾选。

## 4. 如何提 PR

1. 从最新 `master` 新建分支，命名建议 `milestone/zhihu-m*` 或 `fix/<简述>`。
2. 一个小改动一个 PR，保持可评审性。
3. 提交前：
   - [ ] `cd simple && python -m pytest -q` 全绿
   - [ ] 运行 `python -m zhihu_downloader --help` / `--version` 无异常
   - [ ] README 双语同步（如涉及用户可见行为）
   - [ ] 新增功能有单元测试
4. PR 描述写清：改了什么 / 为什么 / 如何验证。
5. 合并由维护者执行；CI（`ci-simple.yml`）必须通过。

## 5. 合规边界（红线）

本项目**只支持已授权内容的个人离线阅读**。任何改动都不得：

- ❌ 绕过付费墙 / 权限校验 / 会员校验；
- ❌ 削弱默认限速（当前默认 2 请求/秒，`--rate-limit` 最小 0.5）；
- ❌ 支持未授权内容的批量抓取、分发或商用；
- ❌ 移除或弱化 README / 合规声明中的限制说明。

> PR 涉及下载、认证、限速逻辑时，请自查上述红线并在 PR 描述中说明未触碰。

## 6. 发布流程

发布由维护者执行，按 [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md) 逐项核对；
推广动作按 [`docs/LAUNCH_PACK.md`](docs/LAUNCH_PACK.md) 与
[`docs/PROMOTION.md`](docs/PROMOTION.md) 执行。

## 7. 行为准则

- 友善、专业；对新手友好；
- 讨论对事不对人；
- 不刷 star、不刷 issue、不刷评论。

---

*再次感谢贡献。所有改动以「真实、合规、可持续」为前提。*
