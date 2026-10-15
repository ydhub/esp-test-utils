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
- 对常见的低压 DUT 输出，稳定的 12 V 直流输入通常可以满足降压余量。
- 前级电源需要提供足够的功率并留有余量；供电能力不足时，DPS 输入电压会下降，可能导致
  输出电压不准或无法维持设定值。
- DPS 模块不是隔离电源，不应默认输入地与输出地之间存在电气隔离。
- 驱动只能读取 DPS 报告的输入电压，无法阻止输入反接、过压或前级电源功率不足。

支持的型号：

| 型号 | 额定量程 | 电流寄存器标度 |
|------|----------|----------------|
| DPS3005 | 30 V / 5 A | 1000 (0.001 A) |
| DPS5005 | 50 V / 5 A | 1000 (0.001 A) |

```{warning}
本驱动仅支持 DPS3005 和 DPS5005，不能用于 DPS5015、DPS5020 或其它型号。
DPS5015/DPS5020 使用不同的电流寄存器标度，使用本驱动可能写入错误的限流值。
驱动不会在每次写操作前自动核对型号，调用方必须先确认面板型号。
```

当前实现已在 DPS5005（固件版本 14、9600 波特、从站地址 1）上完成真机验证，包括状态读取、
调压、5 A 限流和输出开关。

```{warning}
DPS 驱动不支持自动寻找串口，调用时必须显式传入设备路径或 USB location。
```

通信板使用 CH340（USB ID `1a86:7523`）。在 Linux 上可执行以下命令查看 CH340 对应的
串口和 USB location：

```bash
python -m serial.tools.list_ports -v
```

在输出中查找 `VID:PID=1A86:7523`，记录对应的 `/dev/ttyUSBx` 和 `LOCATION`。部分继电器板
和 DUT console 也使用 CH340，仅凭 VID/PID 无法区分；存在多个 CH340 时，可以先记录列表，
拔下 DPS 通信板后再次执行命令，消失的设备就是 DPS 串口。确认后建议在台架配置中保存 USB
location（例如 `1-5.1`），它通常比 `/dev/ttyUSBx` 更稳定。

## Python API

从 `esptest.devices.dps` 导入公开 API：

```python
from esptest.devices.dps import DPS, DPSError

with DPS('/dev/ttyUSB0') as dps:
    dps.set_protection(over_voltage=4.5, over_current=1.5)
    dps.power_output(3.3)  # 不传 amps 时保留设备当前限流值

    status = dps.read_status()
    print(status['voltage_out'], status['current_out'], status['mode'])

    dps.output_off()
```

主要方法：

| API | 说明 |
|-----|------|
| `set_voltage(volts)` | 设置输出电压 |
| `set_current(amps)` | 设置输出限流值 |
| `set_output(on)`、`output_on()`、`output_off()` | 开启或关闭输出 |
| `power_output(volts, amps=None, output=True)` | 不关断已有输出；设置电压，可选设置限流值，`output=True` 时确保输出开启 |
| `read_status()` | 在一次事务中读取全部工作状态寄存器 |
| `get_voltage()`、`get_current()`、`get_power()` | 读取实际输出值 |
| `set_protection(...)`、`get_protection()` | 写入或读取 OVP、OCP、OPP 门限 |
| `get_protection_state()` | 读取 `none`、`OVP`、`OCP` 或 `OPP` 状态 |
| `set_key_lock(lock)` | 锁定或解锁面板按键 |
| `model_name`、`spec` | 读取型号名称和型号量程 |
| `close()` | 释放驱动使用的串口，不关闭电源输出 |

`read_status()` 返回 `voltage_set`、`current_set`、`voltage_out`、
`current_out`、`power_out`、`voltage_in`、`output`、`mode`、`protection`、
`key_locked`、`model` 和 `version` 字段。

如果输出已经开启，调用 `set_voltage()` 或使用默认 `output=True` 的 `power_output()` 不会先关闭输出；
新电压会立即作用于 DUT。该行为用于需要保持 DUT 持续供电的在线调压场景。
`power_output(..., output=False)` 只关闭输出，不修改电压和限流值。

退出 `with DPS(...)` 上下文时（包括发生异常时）会调用 `close()`，电源输出会继续保持。
由 `DPS(port)` 打开的底层串口会被关闭。需要让 DUT 断电时，必须在退出前显式调用
`output_off()`。

`read_status()`、`set_voltage()` 等通信方法抛出异常时不会自动关闭串口，以便调用方决定是否
重试。未使用 `with` 长期持有 `DPS` 对象时，应通过 `try/finally` 确保最终调用 `close()`。

## 设置范围

驱动不对输出电压和限流值施加固定的软件范围限制。调用方应根据 DPS 型号额定量程、DUT
允许范围和台架接线自行保证设置安全；超出模块能力的值可能被硬件拒绝或限制。

调用 `power_output()` 时如果不传 `amps`，不会修改设备当前的限流值。

### 限流值的含义

`set_current()` 设置的是输出电流上限，不是要求电源持续输出的目标电流。实际输出电流由
DUT 负载决定：

- 当实际电流低于限流值时，DPS 工作在 CV（恒压）模式，优先维持设定电压。
- 当负载尝试获取超过限流值的电流时，DPS 进入 CC（恒流）模式，将电流限制在设定值附近，
  此时输出电压会下降。
- `read_status()['current_set']` 是限流设定值，`current_out` 才是当前实测输出电流。
- 将限流值设为 0 A 不等同于可靠关闭输出；需要断电时应调用 `output_off()`。

硬件保护独立于输出设置：

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
# 显示指定串口设备的状态
esp-dps -p /dev/ttyUSB0

# 也可以使用 USB location
esp-dps -p 1-5.1

# 设置 3.3 V、限流 1.5 A，并开启输出
esp-dps -p /dev/ttyUSB0 -v 3.3 -c 1.5 -o on

# 关闭输出
esp-dps -p /dev/ttyUSB0 -o off

# 设置硬件保护门限
esp-dps -p /dev/ttyUSB0 --ovp 3.6 --ocp 1.5 --opp 5
```

使用 `-o off` 时只关闭输出并回读状态，同时传入的保护门限、电压和限流值不会写入；其他情况下
依次设置保护门限、电压、限流值和输出状态，最后回读状态。若输出原本已经开启且未传入 `-o off`，
通过 `-v` 或 `-c` 写入的新设定会立即生效。
为避免直接使用面板或上一次操作遗留的电压，`-o on` 必须同时传入 `-v`。

## 常见问题

| 现象 | 检查项 |
|------|--------|
| `no valid answer` | 面板波特率和从站地址 |
| `failed to open` | 串口权限以及当前用户是否属于 Linux `dialout` 组 |
| `unsupported model` | 型号是否已添加到 `MODEL_SPECS` |
| 输出电压偏低 | 输入电压余量、是否进入 CC 模式、是否触发保护 |

驱动仅依赖 `pyserial`，该包已经是 `esp-test-utils` 的核心依赖。
