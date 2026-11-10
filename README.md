# multisim-build

把电路截图变成 NI Multisim 能直接仿真的电路，外加一整套 `.ms14` 文件格式、COM 接口、剪贴板的逆向工具。

同时也是一份 **agent skill**（`SKILL.md`）—— 扔给 Claude Code / DeepSeek Harness / WorkBuddy 这类能读 Markdown 技能的 agent，它就知道怎么帮你搭电路。

全部结论都来自 **Multisim 14.0.593.0 实机实测**，不是文档抄来的。验证不了的东西会明确标「未验证」。

---

## 三个技术发现

这三个是项目的立身之本，每个都有可复现的验证。

### 1. `.ms14` 就是一个 PKWare DCL Implode 容器

`.ms14` / `.ewprj` 的文件头是 `MSMCompressedElectronicsWorkbenchXML`，字面意思就是「压缩的 EWB XML」。试过 zlib、deflate、gzip、LZMA、bz2、XZ、7z、LZ4、Zstd、LZNT1 —— **全部解不开**。

真正的算法是 **PKWare DCL Implode**（`.zip` 的 method 6）。

```
offset 0   36 B   "MSMCompressedElectronicsWorkbenchXML"（.ewprj 少 MSM 前缀）
offset 36   8 B   uint64le   XML 解压后总字节数
offset 44         重复直到累计解压量 == 总字节数：
           4 B   uint32le   本块解压后字节数
           4 B   uint32le   本块压缩后字节数
      n   B   一个完整的 DCL Implode 流（头 3 字节 01 06 00 = ASCII 字面量 + 8KB 字典）
```

`scripts/pkware.py` 是纯 Python 实现（编解码都有，零依赖）：

| 操作 | 实测结果 |
|---|---|
| 解 125,843 B 的 `.ms14` | 1,068,512 B XML，0.19 s，与 node-pkware 输出 **sha256 完全一致** |
| 压回容器 | Multisim 自己解我们的文件：`identical=true` |
| 交叉验证 | node-pkware 解我们压出来的文件，1,068,512 B 逐字节相同 |

### 2. Multisim 有 COM 接口（但官方没公开）

网上流传的说法是「Multisim 没有自动化接口」，那是因为查的是 `Multisim.Application` / `NI.Multisim` 这两个不存在的名字。真名是：

```
MultisimInterface.MultisimApp.1     {D9CBB7A1-6AD6-438B-AD1B-42FB2DB00CAE}
MultisimInterface.MultisimCircuit.1 {D5E270F6-6FFE-4C5D-AB0C-2B7F565494EE}
```

实现在 `<安装目录>\MSInterface.dll`（**32 位**，注册在 `HKLM\SOFTWARE\WOW6432Node\Classes\CLSID`，64 位注册表里看不见），TypeLib `{D360240D-8F60-4FBC-AEC2-B6E14C3042B8}`。

`IMultisimCircuit` 有 **42 个方法**（去掉 7 个 IDispatch 标配）。实测能用的：

| 方法 | 实测 |
|---|---|
| `EnumComponents(filterType)` | 返回元件列表，如 `C1, R1, V1` |
| `RLCValue(name)` 读写 | **返回数值不是字符串**：`C1 → 1E-07`、`R1 → 1000` |
| `ReportNetlist(probes, format, file)` | 导出引脚-网络表 → 这是自动验证拓扑的基础 |
| `Save` / `SaveAs(file)` | 可用 |

试过但**用不了**的（别再浪费时间）：`EnumOutputs` 恒空、`SetOutputRequest` / `DoDCOperatingPoint` / `DoACSweep` 全 `E_FAIL`（无探针电路没有仿真输出定义）、`DoCommandLine` 是 XSPICE 交互命令入口不是分析卡、`GetCircuitImage` 调用 120 秒不返回。

调用有三个坑：PowerShell 的动态 COM 在 `VariantClear` 处 `AccessViolation` 杀进程、必须 x86、`ReportNetlist` 抛 `E_ACCESSDENIED` 但文件其实写出来了。所以工具是 C# 编译的 `mscom.exe`，不是 PowerShell 脚本。

### 3. 复制电路时剪贴板里是完整 EWB XML

`Ctrl+C` 一个电路，剪贴板私有格式 `Multisim 14.0` 里躺着的是 **`CompressedElectronicsWorkbenchXML`** —— 就是 `.ms14` 那套容器（少 `MSM` 前缀）。实测复制 3 元件图纸，得到 28,672 B 容器 → 解出 297,291 B XML，根节点 `ElectronicsWorkbench_Clipboard_data`。

意味着电路片段可以程序化搬运，不用一个个点元件对话框。

坑：Multisim 是 32 位，私有剪贴板格式必须用 **32 位进程**读（64 位读不到），而且要先 `SetForegroundWindow` 到标题含 `Multisim - [` 的电路窗口 —— `MainWindowHandle` 指向的是个空框架窗口。

---

## 能力边界

| 能做 | 证据 |
|---|---|
| 解包 / 打包 `.ms14`、`.ewprj` | 与 node-pkware 交叉验证 |
| 截图 → IR（元件清单 + 引脚网络）→ SPICE 网表 → Multisim 导入 | 端到端跑通，导入后元件值与拓扑正确 |
| 用 COM 把 IR 和真实电路逐引脚比对 | `ms14_verify.py` 抓得出「引脚接错网络」「阻值写错」 |
| 离线查 35,303 个元件的库路径 | `msfind.py` 支持中文名 / 英文名 / 型号 |
| 另存电路、导出网表 | COM `SaveAs` / `ReportNetlist` |

| 不能做 | 原因 |
|---|---|
| 从零生成合法 `.ms14` | XML 是 170 种标签的对象序列化树，要重建符号表 / 位号索引，不是填模板的量级 |
| 用 COM 放元件、连线 | 没有 `AddComponent` / `ConnectPins` |
| 用 COM 取仿真波形 | 无探针电路没有输出定义，相关方法全 `E_FAIL` |
| 从零放数字元件（74 系列、数码管） | SPICE 模板只覆盖 R/C/L/源/二极管/三极管/运放与 8 种数字门，且元件对话框的自动化没打通 |

---

## 快速开始

### 作为 agent skill

```bash
git clone https://github.com/dongxinchen/multisim-build.git
cp -r multisim-build ~/.dsh/skills/          # DeepSeek Harness
# 或
cp -r multisim-build ~/.agents/skills/       # 通用 Agent Skills 约定
```

自检（只依赖 Python 3.8+ 标准库）：

```bash
python tests/test_selfcheck.py
# codec / ir_to_spice / validation / value parse / verify / library / cli
# all checks passed
```

### 作为命令行工具

```bash
# .ms14 <-> XML
python scripts/ms14.py info   design.ms14
python scripts/ms14.py unpack design.ms14 -o design.xml
python scripts/ms14.py pack   design.xml  -o design.ms14

# 电路 IR -> SPICE 网表（Multisim 里 File -> Open 选 *.cir）
python scripts/ir_to_spice.py circuit.ir.json -o circuit.cir

# 元件库查询（离线，35,303 条）
python scripts/msfind.py 电阻
python scripts/msfind.py LM358 --limit 3
python scripts/msfind.py --groups

# IR 与真实电路比对（需要 Multisim 正在运行）
scripts/mscom/mscom.exe dump circuit.ms14 > circuit.dump.json
python scripts/ms14_verify.py circuit.ir.json circuit.dump.json
```

### 编译 COM 工具

仓库里带了编译好的 `mscom.exe` / `clipdump.exe`（x86，各 11 KB / 7.6 KB），也可以自己编：

```powershell
powershell -File scripts\mscom\build.ps1
```

需要 .NET Framework 4.x 的 `csc.exe`（Windows 自带）。

---

## 目录

```
SKILL.md                 agent 入口：五阶段流程、落地路径选择、回退表
references/
  vision_spec.md         截图判定规则、单位换算、连接推断、确认表格式
  ir_schema.json         IR 的机器可读定义
  ewb_schema.md          .ms14 字节布局、DCL Implode、XML 节点结构
  spice_mapping.md       SPICE 导入入口、spiceewb.tpl 类型码、元件库路径
  mscom.md               COM 注册信息、可用/不可用成员、5 个调用坑
scripts/
  pkware.py              PKWare DCL Implode/Explode（纯 Python）
  ms14.py                容器 info/unpack/pack
  ir_to_spice.py         IR -> .cir
  ms14_verify.py         IR vs COM dump 三查
  msfind.py              元件库检索
  mscom/                 C# COM 工具（mscom / clipdump 源码 + 编译产物）
assets/spiceewb.tpl      Multisim 原版 SPICE 映射表（266 行）
data/                    元件库数据包（35,303 元件 + 106 关键词 + 105 中文别名）
tests/                   自检 + 固定用例
```

---

## 一个真实用例

`74LS48D` 驱动共阴数码管（教科书图 2-31 那个电路）：

```
U2 = 74LS48D    A/B/C/D ← 四个拨动开关      OA..OG → 数码管 A..G
                ^LT / ^RBI / ^BI^/RBO ← VCC   VCC / GND 接电源
U1 = SEVEN_SEG_COM_K    COM → 1kΩ → GND
```

`mscom.exe dump` 读出来的实际网络：

```json
{"nets":{"3":["S1:2","U2:A"],"6":["U2:OB","U1:B"],"12":["R1:1","U1:COM"],
         "VCC":["U2:^BI^/RBO","U2:^LT","U2:^RBI","U2:VCC",...],
         "GND":["U2:GND","R1:2","S1:1",...]}}
```

按 F5 仿真，拨开关，数码管数字跟着变。

---

## 已知限制

- 数据包是 2026-10 从本机 Multisim 14.0 的 Jet 库导出的快照。换版本或加了自建元件后会过期，重新导出覆盖 `data/` 两个文件即可，脚本不用改。
- COM 接口是进程内 DLL（`MSInterface.dll`），Multisim 崩它会一起崩；NI 没有公开文档，一切都是实测。
- `ReportNetlist` 导的是 GBK 编码，网络名会保留 SPICE 网表里的原名，所以 IR 的 net 名和它不一致时 verify 会报差异 —— 那是命名问题不是拓扑问题。
- 元件放置对话框（`Ctrl+W`）的自动化没打通，数字元件仍需手工放。

## 参考

- [cinderblock/electronics-workbench-decoder](https://github.com/cinderblock/electronics-workbench-decoder) —— 确认了 Multisim 用 PKWare DCL
- [node-pkware](https://www.npmjs.com/package/node-pkware) —— 移植时的算法参照，也是交叉验证的工具
- [firefly206521/multisim_mcp](https://github.com/firefly206521/multisim_mcp) —— 从它的代码里发现了 COM ProgID 的存在

## License

MIT
