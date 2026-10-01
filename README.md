# duoterm：你和 AI Agent 共用同一个 SSH 终端

一个终端开 Agent（Claude Code / Codex CLI / OpenCode / Hermes / OpenClaw / 自己写的 Python Agent 都行），另一个终端 SSH 到服务器。你在 SSH 终端里照常敲命令；Agent 能看到这个终端里的全部输入输出，也能直接在里面执行命令，而你会实时看到它在打什么。

```
Windows Terminal（左右分屏）
┌──────────────────────────────┬──────────────────────────────────────┐
│ Agent（Claude Code / Codex…） │ duoterm attach   ← 你在这里手动敲命令   │
│                              │ rtuser@server:~$ df -h                │
│  调用 duoterm / MCP 工具 ─────────▶ tmux 会话 "remote"（在 WSL 里）     │
│  run / read / screen / keys  │   └─ bash → ssh myserver               │
└──────────────────────────────┴──────────────────────────────────────┘
                                   └─ 所有输出同时写入 ~/.duoterm/remote.log
```

## 到底需要装什么？

**只需要装 tmux**（WSL 里再加上本来就有的 Python 3.10+ 和 ssh），然后装上这个仓库。
MCP 和 Skill **不是要另外下载的软件**，而是把同一个能力接到不同 Agent 上的几种方式，本仓库都已经提供：

| 层 | 是什么 | 谁能用 |
|---|---|---|
| tmux | 底层的“共享终端”：你 attach 进去打字，程序可以读屏幕、往里发按键 | 所有 |
| `duoterm` 命令 | 本仓库核心，一个普通命令行工具 | **任何能执行 shell 命令的 Agent**（通用兜底，不依赖 MCP / Skill） |
| `duoterm-mcp` | MCP server，把功能暴露成 `terminal_run` 等工具 | 支持 MCP 的 Agent：Claude Code、Codex、OpenCode、Hermes… |
| `skills/shared-terminal/SKILL.md` | Agent Skills 格式的使用说明 | 支持 SKILL.md 的 Agent：Claude Code、Codex、OpenCode、Hermes、OpenClaw… |
| `templates/AGENTS.md` | 一段纯文字说明 | 什么都不支持的 Agent，贴进 AGENTS.md / 系统提示词即可 |

推荐组合：**duoterm + MCP**（Agent 用起来最稳）；Agent 不支持 MCP 就用 **duoterm + Skill 或 AGENTS.md**。

## 快速开始（Windows + WSL）

以下命令都在 **WSL 的 Ubuntu** 里执行。

```bash
# 1. 安装（会自动 apt 安装 tmux / python3-venv，然后把 duoterm、duoterm-mcp 放到 ~/.local/bin）
git clone https://github.com/SeanInBeta/duoterm.git && cd duoterm
./install.sh            # 加 --skills 会把 Skill 复制到已存在的 Agent 目录（~/.claude/skills 等）

# 2. 配好 SSH 免密登录（Agent 不能、也不应该替你输密码），参考 templates/ssh_config.example
ssh-keygen -t ed25519 && ssh-copy-id myserver

# 3. 创建共享会话并连上服务器（tmux 会话名默认 remote）
duoterm start myserver

# 4. 在“SSH 那个终端”里接入这个会话，之后你就在这里手动操作
duoterm attach
```

不用再做别的：Agent 第一次执行命令时，duoterm 会自动在远程 shell 里装上不可见的 shell integration（发一行设置代码，执行完自己擦掉），之后屏幕上就只有命令和输出。

然后在另一个终端（也在 WSL 里）启动你的 Agent，并按下一节把它接上。

> 之前装过、`duoterm-mcp` 启动报 `No module named 'mcp.server.fastmcp'`（Agent 里显示 `duoterm: failed (0 tools)`）？这是装上了不兼容的 mcp 2.x，运行 `~/.local/share/duoterm/venv/bin/pip install "mcp<2"` 或重新运行 `./install.sh` 即可修复。

Windows Terminal 小技巧：把 `templates/windows-terminal-profile.json` 加到 profile 里，一点就能打开“共享 SSH”标签；`Alt+Shift+D` 分屏，一边 Agent 一边 SSH。

## 接入各个 Agent

挑你的 Agent 支持的方式，配一种就行（各 Agent 的配置路径以它们的官方文档为准）。

| Agent | MCP | Skill 目录 |
|---|---|---|
| Claude Code | `claude mcp add duoterm -- duoterm-mcp` | `~/.claude/skills/` |
| Codex CLI | `codex mcp add duoterm -- duoterm-mcp`，或 `templates/agents/codex/config.toml` | `~/.codex/skills/` 或 `~/.agents/skills/` |
| OpenCode | `templates/agents/opencode/opencode.json` 合并到 `~/.config/opencode/opencode.json` | `~/.config/opencode/skills/` |
| Hermes Agent | `templates/agents/hermes/config.yaml` 合并到 `~/.hermes/config.yaml` | `~/.hermes/skills/` |
| OpenClaw | 按它的 MCP / Skill 机制接入 | `~/.openclaw/skills/` |
| 自己写的 Python Agent | 能当 MCP client 就接 `duoterm-mcp` | 或直接 `from duoterm.core import Terminal`，见 `templates/agents/python/example_agent_tool.py` |
| 其他任何 Agent | — | 把 `templates/AGENTS.md` 贴进它的说明文件 / 系统提示词，让它调用 `duoterm` 命令 |

**Claude Code 额外福利**：`templates/agents/claude-code/settings.json` 里配了一个 `UserPromptSubmit` hook（`duoterm context`）。每次你给 Claude 发消息，它会自动把共享终端里“上次以来的新内容”塞进上下文，你直接问“刚才那个报错怎么回事”就行。同一个文件还把只读命令（status / read / screen / wait）设为免确认，`run` / `type` / `keys` 仍需你批准。其他 Agent 如果有类似的“提交前执行命令”的 hook，也可以挂 `duoterm context`。

**Agent 跑在 PowerShell（不在 WSL 里）**：把 `scripts/` 加进 PATH，`duoterm.ps1` 会转发到 WSL；MCP 配置写 `command: wsl.exe, args: ["-e", "bash", "-lc", "exec duoterm-mcp"]`。推荐还是把 Agent 也放进 WSL 跑，最省事。

## 命令一览

| 命令 | 作用 |
|---|---|
| `duoterm start [host] [--ssh-arg ARG] [--reconnect]` | 创建 tmux 会话、开启日志并执行 `ssh host`；会话已存在时不会重复 ssh（断线后用 `--reconnect`） |
| `duoterm attach` | 你自己接入共享会话 |
| `duoterm status` | 会话是否存在、是否停在空闲提示符、Agent 是否有命令在跑、是否检测到 shell integration |
| `duoterm integrate [--force]` | 立即装上 shell integration（bash / zsh）。一般不用手动执行：`run` 第一次会自动装 |
| `duoterm integrate --print` | 只打印这段设置代码，贴进服务器的 `~/.bashrc` / `~/.zshrc` 永久生效 |
| `duoterm run "cmd" [-t 秒] [--force]` | 在空闲提示符执行一条命令，返回输出和 `[exit N]` |
| `duoterm read [-n N]` / `duoterm read --new` | 最近 N 行 / 上次读取以来的新增内容（包括你手打的） |
| `duoterm screen` | 当前屏幕原样（vim、top、交互提示） |
| `duoterm type "text" [--enter]` | 原样输入文本（回答 y/n、REPL 输入） |
| `duoterm keys C-c Enter Escape Up q …` | 发送按键 |
| `duoterm wait [--pattern RE] [--idle 秒] [-t 秒]` | 等待超时未完成的命令、某段输出出现、或终端回到空闲 |
| `duoterm context` | 给 hook 用：新内容包在 `<shared-terminal>` 标签里 |
| `duoterm stop` | 关闭会话 |

通用参数：`-s NAME`（或环境变量 `DUOTERM_SESSION`）选会话，可以同时连多台服务器；`--json` 输出结构化结果。
退出码：`run` / `wait` 返回远程命令自己的退出码；124 = 还在运行；125 = duoterm 自身错误（没会话、终端忙、命令被拦截）。

## 工作原理（以及解决了哪些坑）

- **共享**：tmux 会话跑在本地 WSL 里，pane 里是 `ssh myserver`。你 `tmux attach` 进去打字；Agent 用 `tmux send-keys` 输入、`tmux capture-pane` 读屏。远程服务器上**不需要装任何东西**（shell integration 是可选的，也只是一段 shell 代码）。
- **终端类型**：duoterm 新建的共享窗口里 `TERM=screen-256color`，ssh 会把它带到服务器上。tmux 自己默认的 `tmux-256color` 在老服务器（例如 CentOS 7）的终端库里没有，那里的 bash 会退回“哑终端”模式：输入行横向滚动，提示符被藏到 `<` 后面，长命令和输出挤在一起。tmux 兼容 screen 的控制指令，`screen-256color` 各个系统都有。只影响 duoterm 建的这个窗口，不改你其他 tmux 会话；想换成别的值设 `DUOTERM_TERM`，设成空（`DUOTERM_TERM=`）则用 tmux 自己的 `default-terminal`。已经在跑的会话要 `duoterm stop` 后重新 `duoterm start` 才生效。
- **知道命令何时结束、退出码多少**，有两种方式，`run` 每次自动选：
  - **shell integration（推荐）**：和 VS Code / iTerm2 / FinalTerm 一样，让远程 shell 在每次显示提示符前输出 OSC 133 转义序列：`ESC]133;D;<上一条命令退出码>BEL`、`ESC]133;A BEL`，命令开始执行时输出 `ESC]133;C BEL`（bash 用 `PROMPT_COMMAND` + `PS0`，zsh 用 `precmd` / `preexec`）。bash < 4.4（例如 CentOS 7 的 4.2）没有 `PS0`，改为在 `PS1` 末尾加一个不可见的“提示符结束”标记 `ESC]133;B BEL`，命令输出从回显的命令行之后算起。终端不会显示这些序列，但 `tmux pipe-pane` 写的原始日志里有。`run` 记下日志当前的字节偏移，**只发送命令本身**，然后在日志里等这之后的第一个 `133;D`：退出码取自它，输出取 `C` 和 `D` 之间（清理掉所有 OSC 序列）。屏幕上就只有 `ls` 和它的输出。
  - **printf 标记（回退）**：没有检测到 integration 时，`run` 发送 `cmd; printf '\n__RT_%s_%d__\n' <随机id> $?`，轮询屏幕直到出现 `__RT_<id>_<退出码>__`。屏幕回显里是 `%s/%d` 模板，不会误匹配。读给 Agent 的内容会把这些标记折叠成 `[exit N]`。
  - **怎么判断用哪种**：只有日志里最近一个 OSC 133 标记是“提示符开始”（A），或者是“提示符结束”（B）且它后面没有任何输出时，才走 integration。你 ssh 到另一台机器、`sudo -i`、进了子 shell、开了 vim 时，最近的标记是“命令开始”（C），自动回退到 printf 标记；回到装了 integration 的 shell 后又自动切回来。万一判断错了（比如 ssh 断线掉回本地 shell），提示符回来却没等到 `D`，`run` 会补发一次 printf 标记取回 `$?`，并在这个 shell 里改用回退方式。
  - 两种方式下，含注释、多行、结尾 `&` 的命令都会包成 `{ …\n}` 再发送（多行命令因此只算一条命令、一个 `D`）。
- **shell integration 的安装**：在一个还没集成的 shell 里第一次 `run` 时自动进行（设 `DUOTERM_AUTO_INTEGRATE=0` 可关闭，改为手动 `duoterm integrate`；装不上的 shell，比如 sh/fish，只尝试一次）。做法是在空闲提示符下发送一行设置代码（开头带空格，`HISTCONTROL` 含 `ignorespace`/`ignoreboth` 时不进 history），执行完自己把这一行从屏幕上擦掉；`read --new` / `context` 里也会隐藏它。代码是幂等的（重复执行不会重复挂钩），`$?` 第一时间捕获、再原样交还，所以你原有的 `PROMPT_COMMAND`（包括 bash 5.1+ 的数组形式）、zsh `precmd` 钩子以及 conda 的 `(env)` 前缀、彩色/多行 `PS1` 都照常工作——bash ≥ 4.4 和 zsh 下完全不改 `PS1`，更老的 bash 只在末尾追加一个零宽标记。想永久生效就把 `duoterm integrate --print` 的输出放到服务器 `~/.bashrc` / `~/.zshrc` 的**最后**。
- **防止抢键盘**：执行前检查光标所在行是不是“空闲提示符”（默认匹配以 `$`、`#`、`%` 结尾），你正在输入一半、有程序在跑、开着 vim 时都会拒绝，并提示 Agent 先看屏幕。执行期间 tmux 状态栏会显示红色 `AGENT RUNNING: …`。
- **看到你做了什么**：`tmux pipe-pane` 把终端原始输出流写进 `~/.duoterm/<会话>.log`；`read --new` 按游标读取增量并清理颜色码、退格、`\r` 进度条和 OSC 序列（写到一半的转义序列留到下次再读，不会留下残片）。装了 integration 时，你自己敲的命令在 `read --new` / `context` 里也会带上 `[exit N]`。
- **交互程序**：`run` 只用于普通 shell 命令；vim / top / sudo 密码 / y/n 用 `screen` + `type` / `keys`。
- **长任务**：`run` 超时返回“still running”（退出码 124），之后 `duoterm wait` 接着等，或 `duoterm keys C-c` 中断（中断后 `wait` 返回 `[exit 130]`，下一条 `run` 不会被卡住）。

## 安全

Agent 接上之后，相当于拿到了你服务器上的 shell，请认真对待：

- `duoterm run` 内置一个危险命令拦截表（`rm -rf /`、`mkfs`、`dd of=/dev/…`、`reboot`、停 sshd、清防火墙、`git push --force` 等），命中需要 `--force`；这只是安全带，不是沙箱。真正的控制靠 Agent 自身的权限确认（例如 Claude Code 里不要把 `duoterm run` 加进免确认列表）。
- 不要让 Agent 输入密码或密钥；需要 sudo 密码时你自己在终端里输。
- 日志 `~/.duoterm/*.log` 会记录终端里出现过的一切（可能包括敏感输出），目录权限 700、文件 600，不要提交到任何地方；需要时直接删掉。

## 已知限制

- 空闲检测靠提示符结尾字符。fish（`>`）或自定义提示符请设 `DUOTERM_PROMPT_RE`，例如 `export DUOTERM_PROMPT_RE='[$#%>]$'`；不确定时 Agent 可以用 `--force` 跳过（会同时跳过危险命令检查，所以默认需要你确认）。
- 远端如果是 PowerShell / cmd 而不是 bash/zsh/sh，`run` 的标记写法不适用，只能用 `type` / `keys` / `screen`。
- shell integration 支持 bash 和 zsh；sh/dash/fish 里设置代码会报语法错误（无害），`run` 继续用可见的 printf 标记。
- bash < 4.4 的方式会在 `PS1` 末尾追加 `\[${__duoterm_b-}\]`（不可见、零宽，靠 bash 默认开启的 `promptvars` 展开；变量不 export，所以继承了 export 的 PS1 的子 shell 不会输出标记）。conda 之类只在前面加前缀的工具不受影响；如果有工具每次都重写 `PS1`，标记会在每次 `PROMPT_COMMAND` 末尾补回去。这条路径是在 bash 5.2 上强制该模式（`DUOTERM_SI_LEGACY=1`）测试的，没有在真实的 bash 4.2 上跑过。
- integration 只对执行过设置代码的那个 shell 生效（判断用的变量故意不 export）：进了子 shell、`sudo -i` 或再 ssh 一层时，在那里第一次 `run` 会再自动装一次。
- zsh 默认不忽略以空格开头的命令，`duoterm integrate` 那一行会进 zsh 的 history（`setopt HIST_IGNORE_SPACE` 可避免）。设置代码要放在 rc 文件最后：如果之后别的工具把自己的钩子插到最前面且不保留 `$?`，`D` 里的退出码可能不准。
- 依赖 tmux `pipe-pane` 原样转发 OSC 序列（在 tmux 3.4 上验证过；`-O` 是默认方向，不需要额外参数）。如果某个环境里日志里看不到 OSC 133 标记，`status` 会显示 `shell_integration: False`，`run` 自动回退。
- Agent 是“一问一答”的，不会持续盯着屏幕：它在你下一次跟它说话、或它自己调用 `read` 时才看到新内容（Claude Code 的 hook 会自动帮你做这一步）。
- 在装不上 shell integration 的 shell 里（sh、fish、关掉了自动集成时），你会在 SSH 终端里看到 Agent 命令后面带着一段 `printf '__RT_…'` 标记，这是正常的。
- 想让远程上的长任务在网络断开后继续跑，可以在远程里再开一层 tmux/screen（记得改前缀键避免冲突），或者用 `nohup`。
- `scripts/*.ps1` 和 Windows Terminal 配置没有在真实 Windows 上自动化测试过；核心功能在 Linux（WSL 同理）上通过本地 bash 和真实 SSH 连接测试过。

## 开发与测试

```bash
pip install -e '.[mcp,test]'
pytest            # 每个用例起一个独立的 tmux server（tmux -L），用本地 bash 代替 ssh，不影响你自己的 tmux
```

代码结构：`duoterm/tmux.py`（tmux 调用封装）、`duoterm/core.py`（run / wait / 空闲检测 / 日志）、`duoterm/shell_integration.py`（OSC 133 设置代码）、`duoterm/cli.py`（命令行）、`duoterm/mcp_server.py`（MCP）。

测试里有 zsh 时会把 shell integration 的用例在 bash 和 zsh 上各跑一遍，没装 zsh 则跳过 zsh 部分。
