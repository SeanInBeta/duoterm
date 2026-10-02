# duoterm Skill

让主终端里的 AI Agent 读取和操作你手动打开的共享终端。一个仓库就是完整 Skill，自带 CLI 与初始化脚本，不需要 MCP 或 Agent hooks。

## 安装与第一次使用

在支持本地 Skill 和 shell 命令的 Agent 里说：

> 帮我从 https://github.com/SeanInBeta/duoterm 安装这个 Skill。仓库根目录 SKILL.md 是入口，连同 scripts 和 references 一起安装。

在 PowerShell 启动 Codex 后输入：

```text
$duoterm 我要使用这个 Skill
```

也可通过 /skills 选择。Agent 会检查 WSL、tmux、Python、SSH，安装自带代码并验证。缺少 WSL 时需要配合授权、重启和创建 Linux 用户。首版面向 Windows + Ubuntu/Debian WSL，也支持原生 Linux，macOS 未支持。

成功后用户目录 ~/.duoterm/setup.md 显示：

```markdown
- [x] 首次环境检查已完成
```

setup.json 记录机器可读状态。以后新开 PowerShell/Codex 跳过完整初始化，直接发现共享终端；更新、主动重新检查或故障时处理对应环节。用户状态不放入下载的 Skill。

## 用户手动打开副终端

一个副终端：新开所选发行版/用户的 WSL 窗口，输入：

```bash
duoterm start
duoterm attach
```

多个独立终端：分别新开 WSL 窗口，每个使用自己的名字：

```bash
# 窗口 A
duoterm -s A start
duoterm -s A attach
```

```bash
# 窗口 B
duoterm -s B start
duoterm -s B attach
```

SSH 终端在 start 后加 user@host。密码、口令和主机指纹由用户在副终端处理。

回主终端回复“已经打开了”，Agent 检查并确认。提前打开的终端也会被发现。同名 start 复用会话；省略 -s 的窗口共享同一个 remote。

## 在对话中使用

> 查看 A 终端刚才的报错。
>
> 在 A 里执行 pwd，在 B 里查看磁盘空间。
>
> 接下来直接在当前 PowerShell 执行。
>
> 仅这次本地执行，之后继续共享终端。

一个已确认终端可默认使用，多个终端必须明确目标。共享规则只作用于当前对话，新对话重新启用并确认；机器初始化记录仍保留。这是 Agent 遵循的 Skill 规则，不是全局强制切换。读取发生在工具调用时，无后台持续监听。

## CLI 与诊断

start、attach、list、status、run、read --new、screen、wait、type、keys、stop。-s NAME 指定会话，支持 --json。doctor --json 显式检查；doctor --smoke --json 使用隔离测试服务器。

Windows Agent 通过 Skill 的 scripts/invoke.ps1 调用，无需 Windows PATH 配置。首次运行 scripts/bootstrap.ps1，Linux 运行 scripts/install.sh。详见 [初始化指引](references/setup.md) 与 [故障处理](references/troubleshooting.md)。

shell integration 自动启用，保留旧 Bash 和可见标记回退。新 pane 默认 screen-256color，DUOTERM_TERM 可覆盖，空值沿用 tmux 默认。超时后 wait，不重复执行；忙碌终端不 run，交互程序用 screen/type/keys。

旧版未标记会话不自动接管：用户确认后 duoterm -s NAME start --adopt，不重建任务。共享终端拥有用户账户权限，危险命令检查不是沙箱，日志不脱敏。

## 开发验证

pyproject.toml 只服务 CLI 开发测试，Skill 用户无需 pip 安装仓库。核心唯一源码在 scripts/runtime/duoterm。

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/pytest
```

测试使用隔离 tmux socket，需要 Linux/WSL tmux 和 bash；缺少 zsh 时相应测试跳过。Windows 参数转发验证见 tests/verify_windows.ps1，使用临时状态与独立服务器。真实 Bash 4.2/旧 terminfo 的环境和结果需单独记录，legacy 模拟测试不能代替实际验证。
