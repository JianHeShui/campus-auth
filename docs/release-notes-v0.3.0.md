# campus-auth v0.3.0

> 自 v0.2.3 以来的累计大版本：CAS 认证稳健性、独立守护进程、日志脱敏、托盘保护状态、门户地址自动获取，以及一批死代码与工程化清理。

## 🐛 认证稳健性

### CAS 多 Cookie 保留（v0.2.5）

门户一次响应可能下发多个 `Set-Cookie`（`SESSION`、`JSESSIONID` 等），旧版只保留第一个，导致后续 CAS 登录因会话不完整被拒。现在全流程使用 Cookie 罐，逐步累积并携带。

### CAS「假成功」判定修复（v0.2.5）

工作流上线步骤（`getCurrentNode → serviceSelection → serviceLogin → userOnline`）每一步都校验 HTTP 状态与业务 `code`；`userOnline` 校验 `data.online`。不再出现"日志显示已上线、实际未放行"。

### 联网探测更准（v0.2.6）

- 优先使用不依赖 DNS 的 NCSI 检测点 IP + 内容校验，再做域名 TLS 探测；
- 校园网 DNS 故障时不再误判「未联网」；
- HTTPS 可达判定放宽为 2xx/3xx；业务 `code` 兼容字符串 `"200"`。

### 门户类型探测（v0.2.6）

- 7 个特征请求**并发**执行，最坏耗时从 6×timeout 降到约 1×timeout；
- CAS 判定改为校验响应正文确实是 JavaScript，**SPA 万能 200 不再误判**；
- HTTPS 自签名门户自动用宽松模式重试。

### 自动获取门户地址修复（v0.2.8）

- 域名 + 公网 IP 多目标探测：**DNS 故障时回退 IP 直连**（网关照样劫持 HTTP），也能取到认证页地址；
- 支持 Location、`location.href`、`window.location`、`location.replace`、meta refresh、表单 action、eportal URL 等多种劫持写法；
- 非标准端口保留为 `host:port`；失败时列出探测记录与排查建议；
- 获取动作在后台线程执行，界面不再卡死。

## 📌 保护状态与托盘（v0.2.7）

- 托盘悬浮提示与右键菜单首行显示「**保护中 / 未保护**」，每 5 秒同步；
- 保护中再点「开始保护」（或配置界面「开始自动保护」）会**自动重启保护**，新配置立即生效；
- 托盘菜单：状态 / 配置 / 开始（重新开始）保护 / 停止保护 / 退出；退出托盘会停止保护。

## 🔒 日志脱敏（v0.2.5）

- 认证日志不再记录账号明文、密码密文、AES 密钥 `croypto`、`execution`、`sessionId`、`ticket`、Cookie 值（此前 CAS 日志同时记录密钥与密文，等价于泄露密码）；
- 日志超过 2MB 自动轮转为 `auth-debug.log.1`。

## 🧹 死代码与工程化（v0.2.6）

- 删除未使用的 `launcher.py`、`config_app.py`；`theme.py` 精简为实际使用的 Token；
- 配置界面：端口/JSON 输入校验、关窗保存失败提示、窗口按屏幕自适应、探测进度反馈；
- 桌面快捷方式图标修正（tray.ico）、含空格路径参数加引号；pip 安装图标回退包内副本；
- 新增 Windows CI（`.github/workflows/tests.yml`）、ruff 配置；
- `build.ps1` 自动读取版本、校验产物并生成发布 zip；
- 测试临时文件改用系统临时目录，**测试 48 → 135 项**，全部通过（不触网）。

## 下载

- **`campus-auth-v0.3.0.zip`**（约 17 MB）

## 安装与使用

1. 解压 zip 到任意目录
2. 双击 `campus-auth.exe`
3. 首次启动：配置界面 + 托盘 + 桌面快捷方式
4. 连上校园网（未认证）→「自动获取」→「一键生成配置」（自动校验类型）→「开始自动保护」
5. 勾选「开机自启」后，重启电脑自动以托盘运行

## 注意事项

- 无需安装 Python，独立运行
- 若杀毒软件提示，请添加信任
- 从旧版升级：解压覆盖 `_internal` 与 `campus-auth.exe`，**不要删除同目录下的 `portal.json`**
- 旧日志可能含敏感内容，建议删除一次：`~/.campus-auth/auth-debug.log`
