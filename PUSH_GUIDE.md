# v5 合并与推送指南（交付物之一）

> 本目录 zhihu-salt-v5/ 是完整可运行的新仓库（已 git init，未 commit 前你全权审阅）。
> 目标：把旧仓库主线替换为 v5，旧全栈代码归档到 legacy 分支，全程不丢历史。

## 0. 审阅（推送前）
```bash
cd zhihu-salt-v5
# 跑全量测试（应全绿，零网络）
python -m venv .venv && .venv/bin/pip install -e '.[dev]' && .venv/bin/python -m pytest tests -q
# 冒烟：起 UI（不登录也能看界面）
.venv/bin/python -m zhihu_downloader gui --no-browser
# 审阅 git 历史与文件
git status && git log --oneline
```

## 1. 归档旧全栈（在旧仓库操作）
```bash
cd zhihu-salt-novel-downloader
git checkout master && git pull
git checkout -b legacy/fullstack        # 旧代码永久保留在此分支
git push origin legacy/fullstack
git checkout master
# 主线删除旧实现（v5 将接管）：
git rm -r src web simple tests scripts docs \
    .github/workflows/build-tauri.yml .github/workflows/build-windows.yml \
    .github/workflows/release.yml .github/workflows/ci-simple.yml .github/workflows/release-simple.yml \
    pyinstaller.spec Dockerfile.build-windows build_linux.sh build_windows.bat config.yaml \
    CONTRIBUTING.md DESIGN.md disclaimer.py requirements.txt uv.lock
git commit -m "chore: 主线清空，旧全栈与 v4 归档至 legacy/fullstack，v5 接管"
# 校验：git ls-files 应只剩 README.md/.gitignore/LICENSE/pyproject.toml（随后被 v5 版本 rsync 覆盖）
```

## 2. 把 v5 内容并入主线
```bash
cd zhihu-salt-novel-downloader
# 复制 v5 全部文件（不含 .git）
rsync -a --exclude='.git' ../zhihu-salt-v5/ ./
git add -A && git commit -m "feat: v5 单文件应用（CLI 内核 + 本地 Web UI）——断点续传/章节进度/书架追更/EPUB 精排/抗失效通道"
```

## 3. 打 tag 触发发布（CI 会自动跑测试门禁）
```bash
git tag v5.0.0
git push origin master --follow-tags
# release.yml: preflight(版本一致性+全量测试) → Win/Linux(22.04)/macOS 三平台构建 → SHA256SUMS → 聚合 Release
```

## 4. 发布后人工事项
- Releases 页把 Windows zip 置顶说明"双击即用"；描述含 SmartScreen 提示（"更多信息→仍要运行"）
- 旧 README 外链的 docs/posts 若不再使用，删除或移入 legacy 分支
- 关闭旧版相关的 GitHub Pages/静态包引用

## 回滚
任何一步出问题：git reset --hard origin/master（推送前）或 revert 合并提交；
legacy/fullstack 分支保证旧代码随时可回。
