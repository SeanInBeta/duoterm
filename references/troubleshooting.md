# 故障处理

只修复实际失败环节，不因新对话而重装依赖。

| 现象 | 检查与处理 |
|---|---|
| Windows 调用失败 | 查看 Windows setup.json 的发行版、用户、Python/runtime；环境改变时重新 bootstrap 指定目标。 |
| WSL 找不到 CLI | 检查 ~/.local/bin/duoterm 和登录 PATH。已有 .bash_profile 可能未读取 .profile，展示最小修改并获准后修复。 |
| 没发现会话 | 核对发行版、Linux 用户和 tmux socket；用只读 tmux list-sessions 找旧版候选，用户确认后 start --adopt。 |
| 多窗口内容相同 | 使用了同名会话。保留旧会话，新开独立 A/B/C；别名不重命名实际会话。 |
| SSH 密码/指纹提示 | 用户在 attach 窗口自行处理，Agent 不代输或自动批准。 |
| disconnected | 看 screen 确认是否掉回本地；用户要求重连才使用 start host --reconnect，不嵌套 SSH。 |
| 忙或输入一半 | 看 screen，等待任务/用户，不默认 --force。 |
| printf 标记 | 不支持集成或集成失败时正常回退，用 status/doctor 诊断，不随意改远程配置。 |
| 老 Bash 没有 PS0 | 保留 OSC 133;B 分支。强制 legacy 测试不能替代真实 Bash 4.2 验证。 |
| 横向滚动/提示符消失 | 核对 TERM 和 terminfo，新 pane 默认 screen-256color；不自动重建旧 pane，停会话前确认任务和授权。 |
| 返回125 | duoterm 自身错误，不是工作命令完成；核对目标和运行路径。 |

~/.duoterm/*.log 记录终端输出，不自动脱敏。无后台上传/遥测；Agent 读取输出会进入其上下文。用户状态、日志与密钥不得提交。
