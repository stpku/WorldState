# Studio 的 Tailnet HTTPS 访问

Studio 继续只监听服务器的 `127.0.0.1:18790`，Tailscale Serve 为其单独的 HTTPS 端口提供访问；该端口没有启用 Funnel。修改前后的 Serve 配置对比确认，原有 TCP、Web 及 Funnel 映射均保持不变，独立扫描审核端口没有加入 Serve。实际运行的 Tailnet 地址由部署管理员提供，不写入公开仓库。

`studio_server.py` 默认只允许本机 Host 和对应的 HTTP Origin；运行时可用 `--trusted-origin` 显式增加**精确的** HTTPS 域名及端口。每个请求的 Host 必须匹配配置；POST 的 Origin 必须与该 Host 成对匹配，仍须提供会话令牌。不会信任任意 `X-Forwarded-*` 来扩展白名单。通配符、非 HTTPS、缺失端口、路径和用户信息均被拒绝。独立扫描审核服务仍只在服务器本机运行。

## 验证记录

- 实际经过 Tailscale HTTPS 和受信任证书的服务器端 Chromium 测试：主页和 Modeler 可加载、29 张照片索引可见且图片加载、API 调用和一次**不写入项目**的实际求解成功；浏览器点击下载的 IFC 由 IfcOpenShell 独立读取并生成一面墙的几何。
- 错误 Origin、错误令牌、非白名单 Host 及不匹配的 Host/Origin 均返回 403；扫描审核端口在 Tailscale 地址上不可连接。
- 以上浏览器运行在 Linux，使用 Windows User-Agent，**不是在实际 Windows 设备上的测试**。具体 Windows 设备仍须连接同一 Tailnet 并具备对应 ACL 权限。
- 代码级 Core 与产品测试共 247 通过；本地与精确 HTTPS 来源、错误来源及令牌分别有测试。既有真实模型仍为未验证的局部草稿，不改变产品验收状态。

本次启用用户 `dev` 的 lingering，并创建已启用的用户级 `worldstate-studio.service`，包括持久目录中的 Python 环境、模型权重和工作区；该用户没有其他 systemd 服务被修改。服务已实际重启并在随后通过 HTTPS 测试。`tailscaled` 和 Studio 服务都已启用；[Tailscale Serve 后台配置](https://tailscale.com/docs/reference/tailscale-cli/serve)会在 Tailscale 重启后恢复。为避免打断现有服务，本次**没有重启整台服务器**，因此尚无整机重启后的实测记录。

## 管理与复现

Studio 的 systemd 用户服务文件位于 `~/.config/systemd/user/worldstate-studio.service`；本次的持久 Python 环境位于 `~/.local/share/worldstate/studio-venv`，不得依赖 `/tmp` 在重启后保留。服务使用 `--warm-vision` 和该部署的精确 `--trusted-origin`。可由服务所有者检查：

```bash
systemctl --user status worldstate-studio.service
systemctl --user is-enabled worldstate-studio.service
loginctl show-user "$(id -un)" -p Linger
tailscale serve status --json
```

管理员如需恢复配置，应仅操作 Studio 对应端口；不要运行 `tailscale serve reset`、更改其他入口或向扫描审核端口添加 Serve。真实 HTTPS 浏览器检查脚本为 `benchmarks/ws_realroom/studio_tailnet_browser_check.cjs`；它只执行非持久化求解，使用独立输出目录，不产生真人观察。浏览器截图和 IFC 结果保存在服务器授权缓存，不作为商业资产发布。
