# 验证记录

验证日期：2026-10-02。修改仅在本地，未提交或推送。

## 已执行

| 验证 | 结果 |
|---|---|
| Skill Creator quick_validate | 通过，根目录 SKILL.md 元数据有效 |
| Python 编译、PowerShell 脚本语法、git diff --check | 通过 |
| Ubuntu WSL / Python 3.12.3 / tmux 3.4 主测试集 | **94 passed, 20 skipped**；跳过为 zsh 相关用例：缺少 zsh，或在 Bash 变体下跳过 zsh 专用检查 |
| GNU Bash 4.2.0(2) 及 ncurses 5.9 定义的针对性测试 | **25 passed, 8 skipped, 66 deselected**；涵盖输出、退出码、复杂命令、自动集成、默认 TERM 和缺少 tmux 定义的数据库 |
| Windows PowerShell 5.1.26100.9549 → WSL | 通过：Unicode、引号、空格、美元符号、管道、退出码、独立 A/B/C 会话及缓存初始化跳过 |
| PowerShell 7.6.5 → WSL | 同上，通过；Skill 路径和运行目录均含中文与空格 |
| bootstrap 状态机 | 通过：首次成功勾选、后台身份记录、重复调用不访问 WSL、失败重检取消勾选；WSL 系统调用使用 mock |
| 运行代码独立于下载源 | 通过：测试移走下载源后，已安装 CLI 仍能运行并通过隔离 smoke 检查 |

所有 tmux 测试使用独立 socket；没有停止或重建用户工作会话。测试依赖、旧 Bash 和终端定义位于 Git 忽略的 `.verification/`，不安装到系统。

## 可复现入口

```bash
bash tests/run_wsl.sh -q
```

Windows：

```powershell
powershell.exe -NoProfile -File tests/test_bootstrap.ps1
powershell.exe -NoProfile -File tests/verify_windows.ps1 -Distro Ubuntu -LinuxUser YOUR_USER
pwsh -NoProfile -File tests/verify_windows.ps1 -Distro Ubuntu -LinuxUser YOUR_USER
```

旧环境测试使用 `DUOTERM_TEST_BASH` 指向实际 Bash 4.2 binary，`DUOTERM_TEST_TERMINFO` 指向旧数据库的 `lib/terminfo`。Bash 编译入口为 `tests/build_legacy_bash.sh`，前提是将官方源归档放在 `.verification/bash-4.2.tar.gz`。

来源与本次下载的 SHA256：

- [GNU Bash 4.2 官方源码](https://ftp.gnu.org/gnu/bash/bash-4.2.tar.gz)：`a27a1179ec9c0830c65c6aa5d7dab60f7ce1a2a608618570f96bfa72e95ab3d8`。
- [Debian 官方 ncurses-base 5.9-10 归档](https://archive.debian.org/debian/pool/main/n/ncurses/ncurses-base_5.9-10_all.deb)：`3aa53b0f177ab8654ae6212b2dca3c9c3a0aa947291305967a31fa8ff4e81262`。
- [Debian 官方 ncurses-term 5.9-10 归档](https://archive.debian.org/debian/pool/main/n/ncurses/ncurses-term_5.9-10_all.deb)：`6140453f9b16daa522f38471caaf3fefb2476d7b053134d101e571ea5df03f1a`。

旧数据库用 `infocmp -A` 明确选取，确认有 `screen-256color` 而没有 `tmux-256color`；避免系统数据库回退掩盖测试条件。本次不是在完整 CentOS 7 系统或真实远程 SSH 服务器上执行。

## 验证边界

- 未在未安装 WSL 的机器上实际启用系统功能、重启或首次创建 Linux 用户；脚本状态转换验证不替代这些系统操作。
- 隔离安装测试的登录 PATH 探测使用 mock，以避免改动用户真实 profile。实际用户 profile 修复分支仍需单独验证。
- zsh 用例未运行；macOS 未支持。
- 对话中的默认执行位置、别名确认和新对话重置已写入 Skill，未使用另一个 Agent 做独立行为评估，不能把文档规则称为宿主强制机制。

后续行为评估应覆盖：已有 A/B 会话、未命名 remote 确认、无会话时两行引导、含糊目标不执行、持续切换 PowerShell、单次本地覆盖、退出共享模式，以及新对话只复用机器初始化记录。
