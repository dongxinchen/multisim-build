# SPICE 网表导入 Multisim

这是当前**最稳的落地路径**：生成纯文本 `.cir`，由 Multisim 自带的 SPICE 导入器转成原理图。不需要理解 EWB XML。

## 1. 两个入口

| 入口 | 做法 | 状态 |
|---|---|---|
| GUI | Multisim `File → Open` → 文件类型选 `SPICE Netlist (*.cir)` → 打开 | 官方路径，字段类型/顺序按 `spiceewb.tpl` 映射 |
| 原生导出 | `spice2m.dll!ImportSpiceNetlist`（RVA `0x1acb0` → VA `0x1001acb0`，ImageBase `0x10000000`） | 未验证调用约定（`__cdecl`? 路径还是内存缓冲?），绕过 GUI 前要先反汇编确认 |

`spice2m.dll` 全库只有 1 个导出，不是 COM。`MultisimEMICtrl.dll` 是给 LabVIEW 的 EMI（字符串 `LabVIEW was unable to find Multisim`），**不是 COM 服务器**；`HKCR` 下没有 `Multisim.Application` / `NI.Multisim` 这类 ProgID。所以没有脚本化 COM 接口。

## 2. `spiceewb.tpl` 映射表（266 行，随 skill 存在 `assets/spiceewb.tpl`）

格式：

```
!17                    ← SPICE 元件类型码
R=%l %0 %1 %j #0       ← 模板：转成 Multisim 元件时怎么填
<scan>=.MODEL <%m> …   ← 可选：附带生成的模型行
```

一个类型码可以有多条模板（按参数形式分支，例如电阻带温度系数/带 model 名）。

### 占位符

| 占位符 | 含义 |
|---|---|
| `%l` | 元件位号（R1、C2…） |
| `%0 %1 %2 %3` | SPICE 语句里的第 0/1/2/3 个节点 |
| `%j` | 元件值（10k、100n） |
| `%m` | model / subcircuit 名 |
| `%n_N` | 该类型在 Multisim 里的内部元件标识 |
| `#N` | 引脚号 |
| `%^4POLY…` | 受控源的多项式系数区 |

### 类型码表（实读 `spiceewb.tpl`）

| 码 | 模板 | 对应 |
|---|---|---|
| 17 | `R=%l %0 %1 %j #0` | 电阻 |
| 18 | `C=%l %0 %1 %j #0` | 电容 |
| 20 | `L=%l %0 %1 #0` | 电感 |
| 19 | `D=%l %0 %1 %m %n_19` | 二极管 |
| 22 / 23 | `Q=%l %1 %0 %2 %m %n_2x` | BJT（两种） |
| 24 / 25 | `J=%l %1 %0 %2 %m %n_2x` | JFET |
| 26 / 27 | `M=%l %1 %0 %2 %3 %m %n_2x` | MOSFET |
| 28 | `E=%l %3 %2 %^4POLY%0 %1 #0` | VCVS |
| 29 | `F=%l %3 %2 %^4POLY%c_0_1 #0` | CCCS |
| 30 | `G=%l %3 %2 %^4POLY%0 %1 #0` | VCCS |
| 31 | `H=%l %3 %2 %^4POLY%c_0_1 #0` | CCVS |
| 32 | `S=…` / 33 `W=…` | 电压/电流控制开关 |
| 0–7 | `U=%l BUF/BUF3/INV/XOR/NXOR/DFF/JKFF/SRFF …` | 数字门与触发器 |

## 3. 器件 → Multisim 库路径

不确定某个元件在库里叫什么、在哪个组，直接查内置数据包（35,303 条，离线，不需要 Multisim 在跑）：

```bash
python scripts/msfind.py 电阻        # 中文意图 -> 系列分布 + 每个系列的代表元件 + 注意事项
python scripts/msfind.py LM358       # 型号 -> 具体元件名 + 封装 + 厂商
python scripts/msfind.py 555 --json  # 机器可读
python scripts/msfind.py --groups    # 20 个组各有多少件
```

常用答案（实测自本机 14.0 库）：

```
主数据库 > Basic > RESISTOR > RESISTOR_VIRTUAL
主数据库 > Basic > CAPACITOR > CAPACITOR_VIRTUAL
主数据库 > Analog > OPAMP > LM358AD
主数据库 > Power > VOLTAGE_REGULATOR > LM7805CT
主数据库 > Mixed > MIXED_VIRTUAL > 555_VIRTUAL
```

库里**没有按阻值/容值分档**的固定电阻电容：选 `RESISTOR_VIRTUAL` / `CAPACITOR_VIRTUAL` 后在属性里改值。虚拟仪器（示波器、万用表、函数发生器）不在元件库里，在右侧仪表栏 —— `msfind.py 示波器` 会直接告诉你这一点。

## 4. 限制

| 限制 | 影响 | 绕法 |
|---|---|---|
| 数字元件只有 `U=` 模板覆盖的几种门/触发器 | 复杂数字电路（计数器、译码器、MCU）导不进 | 走 GUI 或 `.ms14` 模板法 |
| 虚拟仪器（示波器/波特图仪）不能从 SPICE 描述 | 导入后没有仪器 | 导入后手工从仪表栏拖一个 |
| 元件位置由导入器自动排布 | 布局丑，连线可能交叉 | 只保证电气正确，不保证好看 |
| `spice2m.dll` 调用约定未知 | 无法无 GUI 批量导入 | 用 GUI，或反汇编确认后再做 |

## 5. 验收

导入后按顺序查这三条，任一不过就算失败：

1. `Simulate → Run` 不报 netlist error；
2. `Options → Sheet Properties` 或状态栏显示的元件数 == IR 里的 components 数；
3. 关键节点的直流工作点与手算一致（分压比、偏置点）。
