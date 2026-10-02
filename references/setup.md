# 初始化与副终端指引

## 首次初始化

状态保存在用户目录，不在 Skill 下载目录。`setup.json` 是完成依据；`setup.md` 显示 `[x] 首次环境检查已完成`。机器初始化不等于本次副终端已经就绪。

Windows 主 Agent 使用 Skill 安装目录的绝对路径：

```powershell
& 'C:/path/to/duoterm/scripts/bootstrap.ps1'
```

脚本记录 WSL 发行版、Linux 用户、运行位置和源码指纹。完成且版本未变时跳过完整检查。多个 Ubuntu/Debian 发行版时先让用户选择，再传 `-Distro Ubuntu -LinuxUser username`；不要使用 docker-desktop 或 root 用户。

需要依赖时展示缺少的包和 apt 操作，获准后加 `-InstallDependencies`。sudo 口令由用户在 WSL 输入；脚本仅使用非交互 sudo，失败就停止。PATH 失败时查看 `.profile`/`.bash_profile`，展示最小修改，获准后加 `-RepairPath`，不覆盖原配置。

没有 WSL：准备 `wsl --install -d Ubuntu`，获准后在管理员 PowerShell 执行；已有管理员会话也可使用 `-InstallWsl`。首次开 Ubuntu、创建 Linux 用户、必要重启由用户完成，然后恢复 bootstrap。未完成/中断时保持未勾选。

WSL/Linux Agent 使用：

```bash
bash /absolute/path/to/duoterm/scripts/install.sh
```

获准安装依赖后加 `--install-packages`，获准补充登录 PATH 后加 `--repair-path`。自动安装支持 Ubuntu/Debian，macOS 未支持。运行代码复制到私有安装目录，移除下载源码后 CLI 仍可运行。Windows Agent 仍需找到安装的 Skill invoke 脚本。

显式重新验证：bootstrap 加 `-Recheck`，Linux installer 加 `--recheck`。只检查：`duoterm doctor --json`。隔离测试输出、退出码、OSC 133 和 legacy 分支：`duoterm doctor --smoke --json`，使用独立 UUID tmux server。

## 每次对话先发现

Windows：`& 'C:/path/to/duoterm/scripts/invoke.ps1' list --json`。Linux：`duoterm list --json`。

已有终端时列出实际名字和状态，用户可以继续指定或补充。默认 `remote` 询问用户称呼；别名仅在当前对话。旧版本会话需用户确认实际名字后 `duoterm -s NAME start --adopt`，不自动接管其他 tmux 会话。

## 用户手动打开副终端

一个终端：新开选定发行版/用户的 WSL 窗口，输入：

```bash
duoterm start
duoterm attach
```

多个独立终端：每个窗口使用自己的名字：

```bash
# 第一个窗口
duoterm -s A start
duoterm -s A attach
```

```bash
# 第二个窗口
duoterm -s B start
duoterm -s B attach
```

第三个使用 C。名字只用字母、数字、`_`、`-`。省略 `-s` 的窗口接入同一个 `remote`，不是独立终端。`attach` 不创建会话。

连接服务器：`duoterm -s A start user@host`，然后 attach。可用该 WSL 用户已有 SSH alias/密钥。密码、密钥口令和主机指纹由用户在副终端处理；不自动复制 Windows 密钥或改变远程账户/rc 配置。

副终端必须使用相同 WSL 发行版和 Linux 用户。提供选定信息，必要时用 `wsl.exe -d Ubuntu -u username` 打开。`Ctrl+b` 后按 `d` 可 detach，任务继续存在。

## 用户回复完成后

再次发现，检查 `attached`、`idle_at_prompt`、`pending_agent_command`、`connection_state`。SSH 状态是启发式提示，身份或连接不清楚时看 screen，标为需要验证。忙碌终端可读取，不能执行新 shell 命令。会话确认后才启用当前对话默认规则。
