# 安装

官方项目仓库：https://github.com/KawaroX/bnul

优先以该仓库 README 为准。macOS、Windows PowerShell、Linux 均可使用：

```sh
uv tool install git+https://github.com/KawaroX/bnul.git
uv tool update-shell
```

重开终端后：

```sh
bnul --help
bnul auth install-browser
bnul auth setup
bnul skill install
```

替代安装方法为 `pipx install git+https://github.com/KawaroX/bnul.git`，然后 `pipx ensurepath`。uv/pipx 需按其官方指引先安装。不需要克隆项目或手动建立虚拟环境。

如果安装后 PATH 暂未更新，重新打开终端/agent 任务；macOS/Linux 可用 command -v bnul，PowerShell 可用 Get-Command bnul 检查。不要把另一台机器的绝对路径当作解决方式。

Linux 缺少系统库时执行 `bnul auth install-browser --with-deps`（可能需要管理员权限）。无桌面自动登录遇到学校人工验证时，仍需可见环境。完整说明见仓库 README。

更新：uv tool upgrade bnul（或 pipx upgrade bnul），再运行 bnul auth install-browser 和 bnul skill install。skill 安装目标可通过 bnul skill install --dest 指定；默认遵循 CODEX_HOME。
