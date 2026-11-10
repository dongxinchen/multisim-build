---
name: multisim-build
description: 把电路截图（可加文字补充）变成 NI Multisim 能打开并仿真的电路。用户给出电路图、要求「照着这张图画到 Multisim」「生成 .ms14」「转成电路」「建个仿真模型」「电路截图转原理图」，或提到 Multisim / EWB / Electronics Workbench / .ms14 / .ewprj / SPICE netlist 导入时用本 skill。也用于解包、查看、修改已有 .ms14 文件。
---

# multisim-build

输入 1..N 张电路截图 + 自然语言补充（型号、参数、要仿真的指标），输出一个 Multisim 14.0 能打开并 `Simulate → Run` 不出错的电路。

**不做**：PCB 布局、Autoroute、Multisim 安装与授权。

## 先自检环境（一条命令）

```bash
python <skill>/tests/test_selfcheck.py     # 全绿才继续
```

只依赖 Python 3.8+ 标准库。不绿就报告真实报错，别绕过。

## 五阶段

### 阶段 1 · 读图

按 `references/vision_spec.md` 逐条读：类型、位号、值、每个引脚接到哪个网络。交叉线只在有实心圆点时才连通；看不清的一律标 `?`。

### 阶段 2 · 写 IR

按 `references/ir_schema.json` 生成 JSON：`components[].pins` 是「引脚号 → 网络名」，地是 `0`。有 `?` 的地方 `confirmed: false`。

### 阶段 3 · 让用户确认（不可跳过）

贴出确认表（格式见 `references/vision_spec.md` 第 5 节）。**任何一项「待确认」都不许往下走。** 用户答复后回填 IR，再继续。

### 阶段 4 · 落地

```bash
python <skill>/scripts/ir_to_spice.py circuit.ir.json -o circuit.cir
```

生成 `.cir` 后交给用户在 Multisim 里 `File → Open` → 文件类型选 `SPICE Netlist (*.cir)`。导入后按 `references/spice_mapping.md` 第 5 节验收（跑仿真不报错、元件数对、关键节点电平对）。

需要直接产出 `.ms14` 时，读 `references/ewb_schema.md`：容器层可以无损解包/打包，但 XML 语义层要照模板法做，不要承诺从零生成。

### 阶段 5 · 自动验证（Multisim 开着就做，别靠眼睛看）

Multisim 有 COM 接口，能把「我以为搭对了」变成「有数值证据」。前提是 Multisim 正在运行。

```powershell
powershell -File <skill>/scripts/mscom/build.ps1            # 首次：编出 mscom.exe（x86，约 11 KB）
<skill>/scripts/mscom/mscom.exe probe                       # 先看版本与连接，返回 version 才继续
<skill>/scripts/mscom/mscom.exe dump circuit.ms14 > circuit.dump.json
python <skill>/scripts/ms14_verify.py circuit.ir.json circuit.dump.json
```

`ms14_verify.py` 查三件并各自报错：元件集合、每个引脚落在哪个网络、R/C/L 的值（相对误差 1e-6）。全对才 `PASS` 且退出 0；有差异就逐条列出，例如：

```
FAIL 1 difference(s):
  - R1 pin 2: on net 'out', IR says 'mid'
  - R1: value 1000 in circuit, IR says 2200 (from '2.2k')
```

拿到 PASS 再交付。`dump` 里的 `netlistOk:false` 表示网表没导出成功，此时引脚与值两项都没比对，不能算通过。

**COM 取不到仿真数据**：无探针的电路 `EnumOutputs` 恒为空，`DoDCOperatingPoint` / `DoACSweep` / `SetOutputRequest` 全返 `E_FAIL`，`DoCommandLine` 是 XSPICE 命令入口不是分析卡。要波形只能 GUI 按 F5，或者用 Python 手算校核（分压比、fc=1/(2πRC)、偏置点）。细节见 `references/mscom.md` 第 2、4 节。

## 落地路径怎么选

| 情况 | 走哪条 | 命令/依据 |
|---|---|---|
| 模拟电路（R/L/C、电源、二极管、三极管、运放） | **SPICE**：生成 `.cir` → Multisim 导入 | `scripts/ir_to_spice.py`，`references/spice_mapping.md` |
| 已有 `.ms14` 要改参数/看内容 | **容器**：解包 → 改 XML → 打包 | `scripts/ms14.py unpack/pack` |
| 目标元件 SPICE 模板覆盖不到（计数器、MCU、仪器） | **模板法**：用户先手画最小骨架存 `.ms14`，解包复制 `CiComponent` 块改参数再打包 | `references/ewb_schema.md` 第 3 节 |
| 以上都不行 | **GUI 兜底**：桌面接管逐个放元件连线 | 慢且脆，6 个元件以上别用 |

## 脚本

```bash
python scripts/ms14.py info   design.ms14        # 容器头 + 块表
python scripts/ms14.py unpack design.ms14 -o design.xml
python scripts/ms14.py pack   design.xml  -o design.ms14          # --magic ewprj 产出 .ewprj
python scripts/ir_to_spice.py circuit.ir.json -o circuit.cir
python scripts/ms14_verify.py circuit.ir.json circuit.dump.json    # IR vs 真电路
python scripts/msfind.py 电阻                     # 中文/英文/型号 -> 库路径（离线，35,303 条）
python scripts/msfind.py LM358 --limit 3          # 具体型号 + 封装 + 厂商
python scripts/msfind.py --groups                 # 20 个组的元件数
python scripts/ms14.py selftest                   # 编解码自检
```

```powershell
powershell -File scripts\mscom\build.ps1          # 编译 COM 工具（需 .NET Framework 4.x）
scripts\mscom\mscom.exe probe                     # 版本 + 连接状态
scripts\mscom\mscom.exe dump  circuit.ms14        # 元件 / 值 / 引脚网络 -> JSON
scripts\mscom\mscom.exe diag  circuit.ms14        # 为什么没有仿真输出
scripts\mscom\mscom.exe saveas circuit.ms14 out.ms14
```

`scripts/pkware.py` 是 PKWare DCL Implode/Explode 的纯 Python 实现，被 `ms14.py` 直接 import，不要单独改它除非重新跑自检。

`scripts/mscom/mscom.exe` 是编译产物（x86，11 KB），源码同目录。**不要用 PowerShell 直接调这个 COM 接口**——会在 `VariantClear` 处 `AccessViolation` 杀进程，原因与绕法见 `references/mscom.md` 第 4 节。

## 硬约束

- 参数看不清 → 标 `?`，不猜。猜错一个三极管会毁掉整张图。
- 先出元件清单和连接表给用户确认，再落地。跳过确认等于交付一个错的电路。
- 落地前备份已有 `.ms14`（`cp x.ms14 x.ms14.bak`）。
- 失败按 **SPICE → 容器 → 模板 → GUI** 顺序回退，并把失败原因写进最终回复。
- 只报实际跑过的命令与结果。没验证的步骤写「未验证」并给出下一条可复现命令。

## 失败回退表

| 现象 | 原因 | 下一步 |
|---|---|---|
| `ir_to_spice.py` 报 `net 'x' not declared` | IR 的 `nodes` 与引脚网络不一致 | 补齐 `nodes`，或删掉 `nodes` 让脚本自动收集 |
| 报 `no component connects to ground net '0'` | 截图里没有接地符号或漏读 | 先确认是否有地；模拟电路必须有参考地 |
| `ms14.py unpack` 报 `not a compressed Electronics Workbench file` | 不是 `.ms14`/`.ewprj`（可能是 `.ms10` 老格式或别的文件） | 打印前 36 字节核对 magic |
| `ms14.py unpack` 报 `block length mismatch` | 容器块表被截断或文件损坏 | 报告块 raw/comp 与偏移，别硬改 |
| Multisim 打开 `.cir` 后报 netlist error | 节点名非法（含空格/中文）、缺模型、元件行顺序错 | 节点名改 ASCII；D/Q/M 必须给型号或 model 名 |
| 导入成功但元件数不对 | SPICE 语句被解析器丢掉（多半是缺值或缺节点） | 逐行核对生成的 `.cir` 与 IR 的 components 数 |
| 打包后的 `.ms14` Multisim 打不开 | XML 语义被改错（容器层没问题） | 用 `ms14.py unpack` 复验容器；XML 改动只做字符串级替换 |
| `mscom` 报 `ProgID ... is not registered` | 该版本没装 `MSInterface.dll` 或改了 ProgID | 注册表搜 `MultisimInterface*` 确认；查不到就放弃 COM，走文件路线 |
| `mscom` 报 `Connect() failed` | Multisim 没启动，或权限/位数不一致 | 先起 Multisim；`mscom.exe` 必须是 x86 编译产物 |
| `mscom dump` 里 `netlistOk:false` | `ReportNetlist` 没写出文件 | 换个可写目录重试；该接口会抛 `E_ACCESSDENIED` 但文件通常已写出，看文件不要看异常 |
| `ms14_verify.py` 说某引脚网络不符 | 要么 IR 错，要么导入时节点被改名 | 先看 dump 的 `nets` 里实际网络名，再判断改哪边 |
| `EnumOutputs` 返回空、`DoDC*` 报 `E_FAIL` | 电路里没有探针 | 正常现象，不是故障。GUI 按 F5 验证，或用 Python 手算 |

## 本机参考路径

```
Multisim 安装     C:\Program Files (x86)\National Instruments\Circuit Design Suite 14.0\
主程序            multisim.exe  (PE32 i386, ImageBase 0x10000000, 无壳)
文件关联          HKCR\.ms14 → ms14file → multisim.exe "%1"
SPICE 映射表      <安装目录>\spiceewb.tpl   （副本在 assets/spiceewb.tpl）
SPICE 导入 DLL    <安装目录>\spice2m.dll    （唯一导出 ImportSpiceNetlist，RVA 0x1acb0，调用约定未验证）
COM 实现 DLL      <安装目录>\MSInterface.dll （32 位；ProgID MultisimInterface.MultisimApp.1）
COM 注册位置      HKLM\SOFTWARE\WOW6432Node\Classes\CLSID （64 位注册表里看不到）
元件库数据        data/mslook_data.json.gz     （35,303 条，已内置，离线查：python scripts/msfind.py 电阻）
元件库来源工程    D:\模拟仿真\multisim_lib\    （本机才有；数据包就是从它的 Jet 只读导出打的）
```

`data/` 里的数据包不依赖 Multisim 是否安装、是否运行，任何机器上都能查。它只用于**告诉你元件在库里叫什么、在哪个组**——SPICE 导入路线本身不需要它。

跨机器时这些路径都要重新探测：`Test-Path` 安装目录，`reg query HKCR\.ms14` 拿实际关联。

## 参考文档

| 文件 | 内容 |
|---|---|
| `references/vision_spec.md` | 截图判定规则、单位换算、连接推断、确认表格式、验收标准 |
| `references/ir_schema.json` | IR 的机器可读定义 |
| `references/ewb_schema.md` | `.ms14` 容器字节布局、PKWare DCL Implode、XML 节点结构、能力边界 |
| `references/spice_mapping.md` | SPICE 导入入口、`spiceewb.tpl` 类型码与占位符、元件库路径、导入限制与验收 |
| `references/mscom.md` | Multisim COM 接口：注册信息与版本核对、可用/不可用成员、`ReportNetlist` 格式、5 个调用坑 |
| `assets/spiceewb.tpl` | Multisim 原版映射表（266 行，照抄） |
