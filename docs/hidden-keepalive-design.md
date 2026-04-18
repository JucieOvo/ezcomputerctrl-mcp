# EZComputerCtrl 隐藏启动与保活方案说明

## 1. 目标

本次改造的目标如下：

1. 继续保留 `scripts/start_ezcomputerctrl_hidden.vbs` 作为隐藏启动入口。
2. 在用户执行隐藏启动后，由脚本在后台持续守护 `ezcomputerctrl` 服务进程。
3. 当服务进程异常退出时，由守护脚本自动重新拉起，不依赖计划任务、系统服务或开机自启。
4. 保活持续到以下任一条件成立为止：
   - 电脑关机或当前会话结束。
   - 用户显式执行停止脚本。
5. 防止重复启动多个守护实例，避免出现多个服务进程竞争同一端口。

## 2. 当前现状

当前仓库中的启动链路如下：

1. `start_ezcomputerctrl_hidden.vbs` 负责隐藏执行 PowerShell。
2. `run_ezcomputerctrl_http.ps1` 负责启动一次 `python[w].exe -m ezcomputerctrl`。
3. `stop_ezcomputerctrl.ps1` 负责按 PID 结束该次启动的服务进程。

现状问题如下：

1. 没有独立守护循环，服务进程退出后不会自动重启。
2. 没有独立的守护进程 PID 标识，无法区分“启动器”和“被守护服务”。
3. 停止脚本只能结束当前业务进程，无法通知未来不要重启。

## 3. 设计原则

本次改造遵循以下原则：

1. 优先复用现有脚本，避免额外新增复杂入口。
2. 保持 `run_ezcomputerctrl_http.ps1` 同时支持“单次启动”和“保活启动”两种模式。
3. 明确区分守护进程与业务进程的 PID 文件。
4. 停止动作必须是显式、可重复执行且结果可预测的。
5. 遇到真实错误直接报错，不引入伪成功、伪回退或假状态。

## 4. 文件与职责划分

### 4.1 `scripts/start_ezcomputerctrl_hidden.vbs`

职责：

1. 作为最终用户常用入口。
2. 以隐藏窗口方式调用 PowerShell。
3. 默认传入保活参数，启动守护模式。

### 4.2 `scripts/run_ezcomputerctrl_http.ps1`

职责：

1. 统一负责环境加载、PID 文件管理和服务启动。
2. 单次启动模式下，启动一次服务后退出。
3. 保活模式下，作为守护脚本持续监控子进程。
4. 若子进程退出且未收到停止指令，则等待短暂间隔后重新拉起。

### 4.3 `scripts/stop_ezcomputerctrl.ps1`

职责：

1. 写入停止信号，阻止守护脚本继续重启。
2. 优先结束业务进程。
3. 再结束守护进程。
4. 清理运行期文件，恢复干净状态。

## 5. 运行期文件设计

计划使用以下运行期文件：

1. `.runtime/ezcomputerctrl.pid`
   - 保存当前业务进程 PID。
2. `.runtime/ezcomputerctrl.guardian.pid`
   - 保存当前守护脚本宿主进程 PID。
3. `.runtime/ezcomputerctrl.stop`
   - 作为显式停止信号文件。
4. `.runtime/ezcomputerctrl.env.ps1`
   - 保持原有本地环境配置用途不变。

## 6. 数据流与执行顺序

### 6.1 隐藏启动流程

1. 用户执行 `start_ezcomputerctrl_hidden.vbs`。
2. VBS 隐藏调用 `run_ezcomputerctrl_http.ps1 -KeepAlive`。
3. PowerShell 检查是否已有活跃守护实例。
4. 若无守护实例，则登记守护 PID。
5. 守护脚本启动业务进程并写入业务 PID。
6. 守护脚本等待业务进程结束。
7. 若未收到停止信号，则重新拉起业务进程。

### 6.2 显式停止流程

1. 用户执行 `stop_ezcomputerctrl.ps1`。
2. 停止脚本写入 `.runtime/ezcomputerctrl.stop`。
3. 停止脚本结束当前业务进程。
4. 停止脚本结束守护进程。
5. 停止脚本清理 PID 文件与停止信号文件。

## 7. 风险点

1. 如果守护脚本与停止脚本并发执行，可能出现文件已被另一方清理的情况。
   - 处理方式：清理文件前统一做存在性判断。
2. 如果服务由于端口占用等问题启动即失败，守护模式会持续重试。
   - 处理方式：保留短暂重启间隔，避免紧密空转。
3. 如果重复执行隐藏启动，必须避免产生多个守护脚本实例。
   - 处理方式：启动前校验 `guardian.pid` 对应进程是否仍存活。

## 8. 验证方案

本次改造完成后，按以下真实流程验证：

1. 执行隐藏启动，确认生成 `ezcomputerctrl.guardian.pid` 与 `ezcomputerctrl.pid`。
2. 手动结束业务进程，确认守护脚本会自动拉起新的业务 PID。
3. 执行停止脚本，确认业务进程和守护进程都退出。
4. 再次检查 `.runtime` 中的 PID 文件是否被正确清理。
5. 重复执行启动脚本，确认不会产生多个守护实例。
