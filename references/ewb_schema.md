# `.ms14` 容器与 EWB XML 结构（实测）

全部数字来自本机实测（Multisim 14.0.593.0，样例 `设计1.ms14` 125,843 B），不是推测。

## 1. 容器格式

```
offset 0   36 B   ASCII magic
  .ms14 : "MSMCompressedElectronicsWorkbenchXML"
  .ewprj: "CompressedElectronicsWorkbenchXML"      (注意少了 MSM 前缀)
offset 36   8 B   uint64le  XML 解压后总字节数
offset 44         重复直到累计解压量 == 总字节数：
           4 B   uint32le  本块解压后字节数
           4 B   uint32le  本块压缩后字节数
      comp_len B   压缩载荷 = 一个完整的 PKWare DCL Implode 流
```

样例实测：

| 项 | 值 |
|---|---|
| 文件总长 | 125,843 |
| 头部声明的 XML 长度 | 1,068,512 |
| 块 0 | raw=900,000 comp=88,484，载荷从 offset 52 开始 |
| 块 1 | raw=168,512 comp=37,299，载荷从 offset 88,544 开始 |
| 压缩载荷前 3 字节 | `01 06 00` → 压缩类型 1=ASCII 字面量、字典码 6=8 KB |

块大小固定 900,000（= `DEFAULT_BLOCK_SIZE`），写回时保持一致最保险。

## 2. 压缩算法：PKWare DCL Implode

`MSMCompressed...` 的字面意思就是「压缩的 EWB XML」，压的就是 DCL Implode（`.zip` 的 method 6）。
zlib / deflate / gzip / LZMA / bz2 / LZ4 / Zstd / LZNT1 **全部解不开**，因为它们都不是这个算法。

已排除的记录（免得重做）：

| 试过 | 结果 |
|---|---|
| zlib、raw deflate、gzip | ❌ |
| LZMA、bz2、XZ、7z | ❌ |
| Windows `RtlDecompressBuffer`(LZNT1) | ❌ |
| LZ4 frame / Zstd magic 扫描 | ❌（文件里根本没有这些 magic） |
| **PKWare DCL Implode** | ✅ 解出 `<?xml version="1.0" encoding="ASCII"?>` |

参考实现来源：[cinderblock/electronics-workbench-decoder](https://github.com/cinderblock/electronics-workbench-decoder)（formats.ts 明确写 Multisim 10–19 = PKWare DCL，decode/encode 双向）与 [node-pkware](https://www.npmjs.com/package/node-pkware)。本 skill 的 `scripts/pkware.py` 是该算法的**纯 Python 移植**，无第三方依赖。

### 验证方式（可重跑）

```bash
# 1. 解真实文件，输出 sha256 与 node-pkware 的结果逐字节相同
python scripts/ms14.py unpack 设计1.ms14 -o a.xml
# 2. 自解自压再解回，sha256 必须一致
python scripts/ms14.py pack a.xml -o r.ms14 && python scripts/ms14.py unpack r.ms14 -o b.xml
# 3. 交叉验证（可选，需 node）
#    node-pkware 解我们压出来的文件，1068512 字节，identical=true
```

压缩率参考：同一份 XML，本实现压出 271,094 B，node-pkware 压出 271,093 B，原文件 125,843 B（Multisim 自己的压缩器更好，但容量不影响可用性）。

> DLL 侧的对应实现未反汇编确认。`spice2m.dll` 只有 1 个导出（`ImportSpiceNetlist`，RVA `0x1acb0`），与容器编解码无关；容器处理应在 `EwbBase.dll` / `Database.dll`。

## 3. XML 结构

根节点 `<MSMElectronicsWorkbench Schema="67">`。样例电路共 **170 种标签、6,265 个 `<Item>`**，是一个对象序列化树，不是简洁的电路描述。

顶层树（实测路径）：

```
MSMElectronicsWorkbench
└─ Project            Class=CProject  ProgramVersion=14.0.0.0  ProjectID={GUID}
   ├─ UniqueSheets
   ├─ DesignSheet     Class=CDrwSubSheet
   ├─ UniqueSheetGroups
   ├─ ViewState
   ├─ Extensions
   └─ …
      └─ CIITHierDoc > Diagram > CIITDiagram
         └─ Elements > Item > CiComponent        ← 元件在这里
```

### 元件节点

```xml
<CiComponent Class="CiComponent"
             LocalName="&ASCVCC"                 ← 符号名，经 &ASC 前缀查 strings 符号表
             SymCompID="114171368"               ← 符号定义 ID
             InstanceID="{B1DAA438-…}"           ← 实例 GUID，连线/标签按它引用
             Circuit="114072464" >
  <Attributes> <Item/> … </Attributes>           ← 显示属性（位号、值、位置…）
  <Ports> <Item CiID="114522824"/> … </Ports>    ← 引脚，CiID 指向连接
</CiComponent>
```

其他关键容器：

| 节点 | 作用 | 样例出现次数 |
|---|---|---|
| `Parameters` / `parameters` + `<Item Value="&ASC5.0"/>` | 元件参数值（带符号表前缀） | 42 |
| `ConnectList` | 引脚到网络的连接 | 154 |
| `CSchDesignNetLabel` | 网络标签 | 38 |
| `RefDesMgrs > RefDesMgr > ComponentPins` | 位号/引脚索引（`CSCH_CAPVirtualComponentPin` 等 per-type 节点） | 76 |
| `strings` | `&ASC…` 符号表 | 169 |
| `Elements` / `ElectricalObject` / `Element` | 图形/电气对象容器 | 281 / 264 / 281 |
| `CiModel`、`CiaSpiceTmpltExprt` | 器件模型与 SPICE 模板 | 4 / 23 |

### 对「直接生成 .ms14」的判断

要凭空生成一个 Multisim 能打开的文件，必须同时重建：符号表（`&ASC` 引用）、每个元件的 `SymCompID` 与图形对象、引脚到 `CiID` 的映射、`ConnectList` 网络表、`RefDesMgr` 位号索引、`CiaSpiceTmpltExprt` 模型模板。**这不是「填一个模板字符串」的量级**，本 skill 不承诺从零生成。

当前可行的替代做法（**模板法**）：

1. 让用户在 Multisim 里手画一个含目标元件类型的最小骨架并存成 `template.ms14`；
2. `ms14.py unpack` → 在 XML 里复制 `CiComponent` 块、改 `LocalName`/`InstanceID`/参数值/坐标；
3. `ms14.py pack` 写回；
4. 在 Multisim 里打开验证；连不上就说明 `ConnectList` / `CiID` 的映射没同步，回退到 SPICE 路线。

容器层是安全的：解包→改字符串→打包→再解包，字节一致（`tests/test_selfcheck.py` 覆盖）。风险只在 XML 语义层。

## 4. 实测：Multisim 自己存出的最小电路

用本 skill 生成 `rc_lowpass.cir`（V1 AC 1 / R1 1k / C1 100n），Multisim 14.0 导入、`F5` 仿真 39.9 s 无报错、`Ctrl+S` 存成 `rc_lowpass.ms14`：

| 项 | 值 |
|---|---|
| 文件 | 39,506 B |
| XML | 395,263 B，**1 个块**（raw=395263 comp=39454） |
| `CiComponent` | **5 个**：`&ASC0` ×2（两处接地）、`&ASCC1`、`&ASCR1`、`&ASCV1` |
| `parameters/Item/@Value` | `&ASC1k`（R1）、`&ASC100n`（C1）、`&ASC1`（V1） |
| `ConnectList` | 16 |

三个元件 + 两个地 = 5 个 `CiComponent` 就够了。**这说明模板法的映射表只需要「元件类型 → `SymCompID`」这一列**（R1=126840912、V1=126841288、C1=126196968 是这台机器这份文件里的值，跨版本/跨符号库会变，不能硬编码）。参数值全部走 `&ASC` 符号表引用，改值就是改符号表里的字符串。

接地不是特殊符号：它就是一个 `LocalName="&ASC0"` 的普通 `CiComponent`。

## 5. 能力边界

| 能做 | 不能做 |
|---|---|
| 解出任意 `.ms14` / `.ewprj` 的 XML | 从零构造合法 XML |
| XML 改完压回容器，Multisim 能读到容器层 | 保证改动后的电路拓扑被 Multisim 接受 |
| 读元件的 `LocalName`、参数、引脚 `CiID` | 反推出元器件型号与 `SymCompID` 的对应表（需样例库） |
