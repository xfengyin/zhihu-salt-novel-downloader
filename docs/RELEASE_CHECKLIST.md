# 发版前检查清单（Release Checklist）

> 每次发布 v4.x.y 前逐项核对。快速版见 `docs/PROMOTION.md` §0；
> 本文件是完整版，覆盖 **测试 / CI / README / Release notes / 资产验证 / 合规** 六块。
> 原则：任何一项不通过就**不发版**。

---

## 1. 版本与代码

- [ ] 版本号三处同步且一致：`simple/pyproject.toml`、`simple/zhihu_downloader/__init__.py`、`simple/zhihu_downloader/webapp.py`
- [ ] 本次变更已合入 master，分支为 `milestone/zhihu-m*` → 已通过 PR 合入
- [ ] 工作树干净：`git status` 无未提交改动

## 2. 测试

- [ ] `cd simple && python -m pytest -q` 全绿（记录通过数）
- [ ] 如改动涉及 CLI：`python -m zhihu_downloader --help` / `--version` 输出正常
- [ ] 如改动涉及导出：手动对样例 URL（或 mock 数据）验证 txt / md / epub 三格式可导出

## 3. CI

- [ ] `.github/workflows/ci-simple.yml` 在 master 上最后一次运行全绿（GitHub Actions 页面确认）
- [ ] 确认 CI 触发条件覆盖本次改动路径（`simple/**` 或 workflow 本身）

## 4. README 与文档

- [ ] `simple/README.md` 与 `simple/README.en.md` 与本次变更同步（新命令/新参数/新格式）
- [ ] Badge 链接有效（CI / Release / Stars / License）
- [ ] 功能特性 / 终端演示 / FAQ 与当前行为一致
- [ ] 相关 docs（`docs/PROMOTION.md`、`docs/RELEASE_CHECKLIST.md` 自身）如有引用更新已同步

## 5. Release notes

- [ ] 按 `docs/PROMOTION.md` §5 规范写好 Release notes（新增/改进/修复/合规 四节，中文为主 + 英文一句话摘要）
- [ ] 涉及行为的变更写清「对用户的影响」
- [ ] 合规类改动单独成节，突出「仅已购内容 / 限速 / 不绕过付费墙」

## 6. 发布执行（打 tag 触发 release-simple.yml）

- [ ] 确认 `v4.x.y` 标签格式正确（如 `v4.2.0`），push 后触发 `release-simple.yml`
- [ ] Release workflow 两个构建 job（Linux x64 / Windows x64）均成功

## 7. 资产验证（发布后 30 分钟内）

- [ ] Linux 产物：`zhihu-downloader-simple-<version>-linux-x64.tar.gz` 可下载
- [ ] Windows 产物：`zhihu-downloader-simple-<version>-windows-x64.zip` 可下载
- [ ] 下载后在干净环境运行 `--version` 输出与本次版本一致
- [ ] 下载后运行 `--help` 正常；可完成一次 mock 下载流程（或至少正常启动）
- [ ] GitHub Release 页面 Release notes 展示正确、资产列表完整

## 8. 合规

- [ ] 本次版本无新增「绕过付费墙 / 权限校验」能力
- [ ] 默认限速未被削弱（仍为 2 请求/秒，`--rate-limit` 最小 0.5）
- [ ] README 合规声明（仅已授权内容 / 个人离线阅读 / 禁止传播）仍完整
- [ ] LICENSE 仍为 MIT、无版权争议内容

## 9. 收尾

- [ ] 如适用：按 `docs/PROMOTION.md` §2/§3 执行本版本对应的外部投稿动作
- [ ] 在 `docs/PROMOTION.md` §8 复盘记录本版本 star 变化与渠道效果

---

*任何一项不通过即不发版；发布后如发现回归，走 bug 修复流程并打 patch 版本。*
