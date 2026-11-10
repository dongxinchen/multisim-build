# Multisim COM 接口（实测）

## 0. 先纠正一条旧结论

早先查过 `HKCR\Multisim.Application`、`HKCR\NI.Multisim`，都是空的，于是得出了「Multisim 没有 COM 自动化接口」。**那是查错了名字。**真名在 `MultisimInterface.*` 下面，本机实测可用。

## 1. 注册信息（版本相关，先核对）

| 项 | 值 |
|---|---|
| ProgID（应用） | `MultisimInterface.MultisimApp.1` |
| CLSID | `{D9CBB7A1-6AD6-438B-AD1B-42FB2DB00CAE}` |
| ProgID（电路） | `MultisimInterface.MultisimCircuit.1` |
| CLSID | `{D5E270F6-6FFE-4C5D-AB0C-2B7F565494EE}` |
| 实现 | `C:\Program Files (x86)\National Instruments\Circuit Design Suite 14.0\MSInterface.dll`（32 位） |
| 注册位置 | `HKLM\SOFTWARE\WOW6432Node\Classes\CLSID`（**32 位视图**，64 位注册表里看不到） |
| TypeLib | `{D360240D-8F60-4FBC-AEC2-B6E14C3042B8}` 1.0，名称 `NI Circuit Design Suite Multisim 14.0`，14 个 typeinfo |

实测环境：Multisim **14.0.593.0**，`VersionInfo` 返回 `Multisim 14.0`。

**换版本先跑 `mscom.exe probe`**：能返回 `"version":"Multisim 1x.y"` 且 `connected:true` 才算这个接口在本机成立。如果 `probe` 报「ProgID 未注册」，说明该版本没装 `MSInterface.dll` 或 ProgID 改名，本文件其余内容不适用 —— 去注册表搜 `MultisimInterface*` 重新确认。

其它版本注意：CLSID 与 TypeLib GUID 随大版本重新生成是正常现象，代码里**不要硬编码 CLSID**，一律 `Type.GetTypeFromProgID`。`IMultisimCircuit` 的方法集也可能增减，缺方法时按第 4 节的办法重新 dump TypeLib 对一遍。

## 2. 实测可用的接口

`IMultisimApp`（18 个成员，去掉 7 个 IDispatch 标准成员后 11 个）：

```
Connect()  Disconnect()  OpenFile(FileName)  NewFile()
Path  IsConnected  LastErrorMessage  VersionInfo  LogFile
```

`IMultisimCircuit`（49 个成员，去掉 7 个 IDispatch 标准成员后 42 个）。分三档：

### 已验证可用

| 成员 | 实测结果 |
|---|---|
| `EnumComponents(filterType)` | 返回活跃元件列表（本机 3 元件电路返回 `C1, R1, V1`）；`filterType` 0=All, 1=AllRLC, 2=R, 3=C, 4=L |
| `RLCValue(name)` 读 | **返回数值不是字符串**：`C1 → 1E-07`、`R1 → 1000`；电压源调用返回 `E_FAIL`（本来就没有 RLC 值） |
| `ReportNetlist(probesFlag, format, file)` | 导出引脚-网络表，见第 3 节 |
| `Save`, `SaveAs(FileName)` | 可用 |
| `CircuitName`, `FileName`, `SimulationState` | 可用 |

### 存在但未验证（按需再试）

`ReplaceComponent(name, section, db, group, family, srcName, model)`（7 个参数，会改电路，没敢乱试）、`EnumSections`、`EnumCircuitParameters` / `CircuitParameterValue`、`ReportBOM`、`SaveDesignAsSnippet` / `CreateSnippet`、`ActiveVariant` / `EnumVariants`、`GetCircuitImage`（**见第 4 节的卡死问题**）。

### 实测不可用（别再试）

| 成员 | 现象 | 原因 |
|---|---|---|
| `EnumOutputs(任何 filterType)` | 全部返回空 | 电路里没有探针就没有"仿真输出"定义 |
| `SetOutputRequest(...)` | `E_FAIL` | 同上 |
| `DoDCOperatingPoint` / `DoACSweep` / `DoACSingleFrequency` | `E_FAIL` | 依赖输出定义 |
| `GetOutputData` / `OutputReady` | `E_FAIL` | 同上 |
| `DoCommandLine(deck, log)` | 不报错，但日志里每条都是 `no such command available in XSPICE` | 它是 **XSPICE 交互命令**入口，不吃 SPICE 分析卡 |

**结论**：没有任何探针的电路，仿真数据拿不到。想用 COM 取波形，只能先在电路里放探针（Multisim 右侧探针栏拖到节点），而放探针本身没有 COM 接口 —— 得回到 GUI。所以本 skill 的仿真校验走「GUI 里按 F5 看有没有报错 + Python 手算校验」，不走 COM。

## 3. `ReportNetlist` 的输出格式

两个坑：

1. **它抛 `E_ACCESSDENIED`（0x80070005）但文件是正常写出来的。** 判断成功要看文件，不要看 HRESULT。
2. **文件是 GBK 编码**，按 UTF-8 读会全是替换字符。

内容是按列排的固定格式（列宽约 20/17/...，用两个以上空格切分）：

```
0                    rc_lowpass       C1                        2
0                    rc_lowpass       V1                        2
in                   rc_lowpass       V1                        1
in                   rc_lowpass       R1                        1
out                  rc_lowpass       R1                        2
out                  rc_lowpass       C1                        1
```

四列 = 网络名、电路名、元件位号、引脚号。前三行表头是乱码（本地化字符串），按「列数 ≥ 4 且位号在元件列表里」过滤即可。

网络名保留了 SPICE 网表里的原名（`in` / `out` / `0`），所以能直接和 IR 对比 —— 这是自动验证能成立的前提。

## 4. 调用坑（每一个都踩过）

| 现象 | 原因 | 做法 |
|---|---|---|
| PowerShell 里 `$app.Path` 之后进程崩，`AccessViolationException in VariantClear` | PowerShell 动态 COM 调用点清理 VARIANT 时踩到实现不规范的内存 | **不要用 PowerShell 动态绑定**。用 C# 编译后 `InvokeMember` 反射调用（`mscom.exe` 就是这么写的），或者 `SysWOW64` 的 32 位 PowerShell + 同样反射 |
| 64 位宿主完全连不上 | `MSInterface.dll` 只有 32 位 | `csc /platform:x86`；宿主也必须 32 位 |
| `GetCircuitImage` 调用 > 120 s 不返回 | 未查明（疑似要 UI 线程空闲或弹了模态框），杀掉进程才恢复 | 别用。需要图就 GUI 截图 |
| `ReportNetlist` 报 `E_ACCESSDENIED` 却写出了文件 | 实现问题 | 检查文件存在且非空 |
| `RLCValue(电压源)` 抛 `E_FAIL` | 源没有 RLC 值 | 只对 R/C/L 调用，其余吞掉异常 |
| 一条命令结束进程后 COM 对象没释放 | `Disconnect()` 没调 | 每个命令结束都 `Disconnect`，`mscom` 已经放在 finally 里 |

## 5. `mscom` 用法

```powershell
powershell -File scripts\mscom\build.ps1                 # 编出 mscom.exe（约 11 KB）
scripts\mscom\mscom.exe probe                            # 版本 + 连接状态
scripts\mscom\mscom.exe dump  circuit.ms14               # 元件 / RLC 值 / 引脚网络，JSON
scripts\mscom\mscom.exe diag  circuit.ms14               # 为什么没有仿真输出（诊断）
scripts\mscom\mscom.exe saveas circuit.ms14 out.ms14     # 另存
```

前置条件：Multisim **已经启动**。`OpenFile` 会按文件路径拿到活电路对象，所以传的 `.ms14` 必须是当前要操作的那个。

`dump` 的输出交给 Python 侧对比：

```bash
python scripts/ir_to_spice.py circuit.ir.json -o circuit.cir
#   → 在 Multisim 里导入并保存成 circuit.ms14
mscom.exe dump circuit.ms14 > circuit.dump.json
python scripts/ms14_verify.py circuit.ir.json circuit.dump.json
```

`ms14_verify.py` 查三件事，任何不符就以非 0 退出：元件集合、每个引脚的所属网络、R/C/L 的值（相对误差 1e-6，支持 `1k` / `100n` / `4.7u` / `1E-07` 这些写法）。实测它能抓出「R1 pin 2 接到 mid 而不是 out」和「R1 写成 2.2k 而电路是 1k」这两种错。

## 6. 无 GUI 时的完整能力边界

| 能（COM） | 不能（COM） |
|---|---|
| 读当前电路的元件、值、引脚网络 | 放元件 / 连线（没有 AddComponent / ConnectPins） |
| 另存为 `.ms14` | 取仿真数据（除非电路本来就有探针） |
| 导出引脚-网络表做校验 | 出原理图（`GetCircuitImage` 卡死） |
