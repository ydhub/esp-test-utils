# DPS 可编程电源

`esptest.devices.dps` 通过 USB 通信板提供的 Modbus RTU 串口控制 DPS3005 和
DPS5005 可编程电源，可设置输出电压、限流值、输出状态以及硬件
OVP/OCP/OPP 保护门限。

## 硬件连接与支持型号

- 前级直流电源连接到 `IN+`/`IN-`。
- `OUT+`/`OUT-` 连接到 DUT 的电源和地。
- 将 DPS USB 通信板连接到主机。通信板使用 CH340 桥接芯片，在 Linux 上通常枚举为
  `/dev/ttyUSBx`。串口参数既可以使用设备路径，也可以使用 USB location（例如 `1-5.1`）。
- 在 DPS 面板菜单中确认波特率和 Modbus 从站地址。默认值为 9600 波特、地址 1。

### 直流输入要求

DPS3005/DPS5005 是降压型直流电源模块，本身不能升压，也不能直接连接交流电：

- 输入必须是极性正确且稳定的直流电，`IN+` 接正极、`IN-` 接负极。
- 输入电压必须高于目标输出电压并留有降压余量，同时不能超过具体型号规定的输入上限。
  不同硬件版本的输入范围可能不同，应以模块铭牌或数据手册为准。
- 对本驱动允许的 1.8 V 至 4.5 V 输出范围，常用的稳定 12 V 直流输入即可满足降压余量。
- 前级电源需要提供足够的功率并留有余量；供电能力不足时，DPS 输入电压会下降，可能导致
  输出电压不准或无法维持设定值。
- DPS 模块不是隔离电源，不应默认输入地与输出地之间存在电气隔离。
- 驱动只能读取 DPS 报告的输入电压，无法阻止输入反接、过压或前级电源功率不足。

支持的型号：

| 型号 | 额定量程 | 电流寄存器标度 |
|------|----------|----------------|
| DPS3005 | 30 V / 5 A | 1000 (0.001 A) |
| DPS5005 | 50 V / 5 A | 1000 (0.001 A) |

DPS5015 和 DPS5020 使用不同的电流标度。在完成真机验证之前，驱动会拒绝这些型号。

当前实现已在 DPS5005（固件版本 14、9600 波特、从站地址 1）上完成真机验证，包括状态读取、
调压、5 A 限流、输出开关、越界电压拒绝以及危险遗留电压合闸保护。

```{warning}
DPS 通信板和部分继电器板都使用 CH340（`1a86:7523`），无法只通过 VID/PID 区分。
`DPS.auto_detect()` 会向候选串口发送只读 Modbus 请求，并且只接受已知的 DPS 型号。
```

## Python API

可以从 `esptest.devices` 或独立模块导入公开 API：

```python
from esptest.devices import DPS, DPSError

with DPS('/dev/ttyUSB0') as dps:
    dps.set_protection(over_voltage=4.5, over_current=1.5)
    dps.power_output(3.3)  # 默认限流值为 5 A

    status = dps.read_status()
    print(status['voltage_out'], status['current_out'], status['mode'])

    dps.output_off()
```

自动探测：

```python
from esptest.devices import DPS

with DPS.auto_detect() as dps:
    print(dps.port, dps.model_name)
    dps.set_voltage(3.3)
```

主要方法：

| API | 说明 |
|-----|------|
| `set_voltage(volts)` | 设置输出电压 |
| `set_current(amps)` | 设置输出限流值 |
| `set_output(on)`、`output_on()`、`output_off()` | 安全地开启或关闭输出 |
| `power_output(volts, amps, output=True)` | 先设置电压和限流值，再开启输出 |
| `read_status()` | 在一次事务中读取全部工作状态寄存器 |
| `get_voltage()`、`get_current()`、`get_power()` | 读取实际输出值 |
| `set_protection(...)`、`get_protection()` | 写入或读取 OVP、OCP、OPP 门限 |
| `get_protection_state()` | 读取 `none`、`OVP`、`OCP` 或 `OPP` 状态 |
| `set_key_lock(lock)` | 锁定或解锁面板按键 |
| `model_name`、`spec` | 读取型号名称和型号量程 |
| `close()` | 关闭串口，不改变输出状态 |

`read_status()` 返回 `voltage_set`、`current_set`、`voltage_out`、
`current_out`、`power_out`、`voltage_in`、`output`、`mode`、`protection`、
`key_locked`、`model` 和 `version` 字段。

## 安全限值

驱动固定限制在以下 DUT 安全范围内：

| 设置项 | 允许范围 |
|--------|----------|
| 电压 | 1.8 V 至 4.5 V |
| 限流值 | 0.0 A 至 5.0 A |

调用 `power_output()` 时如果不传 `amps`，默认限流值为 5.0 A。

不能通过构造参数或 setter 放宽这些限值。数值超出范围时会在命令写入设备之前抛出
`DPSError`。

调用 `set_output(True)` 或 `output_on()` 时，驱动会先读取模块内保存的电压设定值。
如果该值不在 1.8 V 至 4.5 V 范围内，驱动会拒绝开启输出，避免面板或其它程序遗留的高电压
直接加到 DUT。`output_off()` 不受此检查影响，可以随时关闭输出。

### 限流值的含义

`set_current()` 设置的是输出电流上限，不是要求电源持续输出的目标电流。实际输出电流由
DUT 负载决定：

- 当实际电流低于限流值时，DPS 工作在 CV（恒压）模式，优先维持设定电压。
- 当负载尝试获取超过限流值的电流时，DPS 进入 CC（恒流）模式，将电流限制在设定值附近，
  此时输出电压会下降。
- `read_status()['current_set']` 是限流设定值，`current_out` 才是当前实测输出电流。
- 将限流值设为 0 A 不等同于可靠关闭输出；需要断电时应调用 `output_off()`。
- 默认使用 5 A 是为了避免 DUT 正常瞬时电流触发 CC 模式而导致供电电压下降。若台架或 DUT
  不能承受 5 A，应显式传入更小的 `amps`，并合理设置 OCP。

硬件保护独立于上述软件限值：

```python
dps.set_protection(
    over_voltage=3.6,
    over_current=1.5,
    over_power=5.0,
)
```

OVP/OCP/OPP 门限存储在 DPS 模块内，并依据自动识别到的型号额定量程进行校验。
保护触发后模块会在硬件侧切断输出，必须通过模块面板清除故障。

## 命令行

安装 `esp-test-utils` 后会提供 `esp-dps` 命令：

```bash
# 自动探测并显示状态
esp-dps

# 显示指定串口设备的状态
esp-dps -p /dev/ttyUSB0

# 设置 3.3 V、限流 1.5 A，并开启输出
esp-dps -p /dev/ttyUSB0 -v 3.3 -c 1.5 -o on

# 关闭输出
esp-dps -p /dev/ttyUSB0 -o off

# 设置硬件保护门限
esp-dps -p /dev/ttyUSB0 --ovp 3.6 --ocp 1.5 --opp 5
```

多个操作按以下顺序执行：保护门限、电压、限流值、输出状态、状态回读。这样可确保只有在新设置
全部写入后才开启输出。

## 常见问题

| 现象 | 检查项 |
|------|--------|
| `no valid answer` | 面板波特率和从站地址 |
| `failed to open` | 串口权限以及当前用户是否属于 Linux `dialout` 组 |
| `no DPS module found` | USB 连接，或显式传入 `--port` |
| `unsupported model` | 型号是否已添加到 `MODEL_SPECS` |
| 输出电压偏低 | 输入电压余量、是否进入 CC 模式、是否触发保护 |

驱动仅依赖 `pyserial`，该包已经是 `esp-test-utils` 的核心依赖。
