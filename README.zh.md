# cad-deliver-mcp

[![PyPI](https://img.shields.io/pypi/v/cad-deliver-mcp?logo=pypi)](https://pypi.org/project/cad-deliver-mcp/)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![python](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)

[English](README.md) | 中文

面向 CAD 产物的交付前门禁：**暂存（stage）** → **离线核验（verify）** → **放行（commit）**。

它存在的理由很简单：「模型说做完了」不等于交付完成。这个服务读回产物、判断它是否成立；读不了的时候
它说 `UNKNOWN`，而不是 `PASS`。

> 状态：**阶段 3 已完成**。解析与核验逻辑从
> [`dsh-sw-cad`](https://github.com/27painter/dsh-sw-cad) 迁移而来，行为逐字节一致——在冻结基线退役前，
> 用 12 组用例做了逐字段比对确认。规则层、MCP 接口与状态机均已就位。
> **尚未完成：** 50 题基准集（`benchmarks/`），所以这份文档里没有任何召回率数字。

## 三个调用

```
deliver_stage(paths, profile="GB_T_TIER1")   复制文件、记录 SHA-256  -> STAGED
deliver_verify(staging_id)                   离线判定              -> VERIFIED / FAILED
deliver_commit(staging_id, target_dir)       原子放行              -> COMMITTED
```

`commit` 只接受 `VERIFIED` 状态。它会在放行前重算暂存文件的哈希，与暂存时记录的值不一致就拒绝。目标目录
已存在同名文件时也会拒绝，除非显式传入 `overwrite=true`——同名是版本决策，**绝不自动追加 `_1` / `_v2`
后缀**。

`deliver://audit/{staging_id}` 返回完整记录：哈希、每一次核验尝试、发现项与修复建议。

### 状态机买到了什么，没买到什么

它让「已核验」到「已放行」之间的空档变得可见。模型在核验之后又改了文件，提交时的哈希比对会抓住。

但它**不是**安全边界。模型完全可以把文件改完再 stage 一次，拿到干净的 `VERIFIED`。记录里保留尝试次数
（`attempts`、`history`），让这种重入在审计中可见——这是协议纪律，不是沙箱。

### 文件落在哪里

暂存在 `%TEMP%/cad-deliver-staging/<id>/`（可用 `CAD_DELIVER_STAGING` 覆盖）。提交之前，用户图纸旁边
不会写入任何东西。提交时每个文件先以 `<name>.partial` 落在**目标目录内**，刷盘后再 `os.replace` 到最终
名——崩溃只会留下上一状态或一个 `.partial`，永远不会出现半个正式文件，且跨盘符改名依然原子。

### stdout 是协议通道

stdio 上的 MCP 用 stdout 传 JSON-RPC 帧。`server.py` 在**导入时、传输层启动之前**就把 `print` 指向
stderr，并把日志配置到 stderr，这样一句随手的诊断输出不会污染协议帧。`sys.stdout` 本身不动，因为传输层
要写它。

---

## 目录结构

```
src/cad_deliver/
├── models.py          # ParsedDrawing、Check、Verdict、StageState —— 数据契约
├── core.py            # 常量与文件摘要
├── taxonomy.py        # 七个图层角色、别名表、归一化（geometry/ 与 rules/ 共用）
├── parsers/           # 唯一允许导入 CAD 库的一层
│   ├── dxf.py         #   ezdxf → ParsedDrawing
│   └── dwg.py         #   DWG → DXF 转换（ODA / LibreDWG / 自定义命令模板）
├── geometry/          # 与任何标准无关的检查
│   ├── dxf_checks.py  #   标注、单位、图幅、线宽、字体、标注文字与几何是否一致
│   ├── topology.py    #   轮廓闭合：0.01 mm 容差下的悬空端点
│   ├── pdf_checks.py  #   页面尺寸、文字层是否真实
│   ├── step_checks.py #   schema、实体数量、包围盒
│   ├── model_checks.py
│   └── review_checks.py
├── standards.py       # 半交付模式：取值必须来自 standards.json
├── pipeline.py        # 核验内核：一个路径进，一个判定出
├── state_machine.py   # STAGED/VERIFIED/COMMITTED + 暂存库
├── server.py          # MCP stdio 接口：3 个工具 + 1 个审计资源
├── rules/             # 可插拔的标准规则
│   ├── base.py        #   BaseStandardRule(ABC) + 注册表
│   ├── codes.py       #   稳定的机器码（E_… / W_…）
│   ├── taxonomy.py    #   cad_deliver.taxonomy 的兼容再导出
│   ├── registry.py    #   PROFILES + SEVERITY_PROFILES + 执行器
│   └── gb/            #   GB/T 14689 幅面、GB/T 4457.2 图层、GB/T 10609.1 标题栏
└── cli.py             # dsh-sw-cad 仍在调用的命令行入口
```

## 规则层

两层，而且这个分层是测试强制的，不是口头约定：

| 层 | 知道什么 | 允许导入 |
|---|---|---|
| `geometry/` | 已解析的事实，不含标准 | 任何 CAD 库 |
| `rules/` | 已解析的事实 + 各自一个标准 | 任何 CAD 库 |

一条规则就是 `ParsedDrawing` 上的纯函数。它不打开文件，也不知道是谁调用了它——profile 只决定一个发现项
**代价多大**。这才是「新增一个标准是插插件，不是拉分支」的底气。

`tests/test_layering.py` 会让构建失败：任一层导入了 CAD 库就红。迁移期遗留的债务清单现已清空，测试断言
它保持为空。

### 四条规则，一个 Tier-1 profile

| 规则 | 标准 | 什么情况下阻断 |
|---|---|---|
| `gb.sheet_size` | GB/T 14689-2008 | 图幅不是 A4–A0（横竖均可，±2 mm） |
| `gb.layer_taxonomy` | GB/T 4457.2-2003 | 标注不在标注层、轮廓留在 0 层、图层名无法归类 |
| `gb.closed_profile` | GB/T 4457.2-2003 | 轮廓存在悬空端点 |
| `gb.title_block` | GB/T 10609.1-2008 | 没有标题栏，或必填字段（图名/图号/比例）存在但为空 |

标题栏这条最关键。只查「块存在」什么也证明不了——空标题栏也是存在的。规则读的是块属性，必填字段为空
就判失败，而这正是模型最容易产出的缺陷。

闭合判定看端点，不看 `closed` 标志位。SolidWorks 和 NX 的真实导出经常把闭合环写成标志位为 False、末点
与首点重合，只看标志位会把这些图全部判成断线——一个总在误报的门禁会被关掉。端点按 0.01 mm 容差吸附，
度数为 1 的顶点就是悬空端点。

### Profiles

```python
PROFILES = {
    "LEGACY_COMPAT":  [],                 # 不跑 GB 规则：与 dsh-sw-cad 2.2.0 逐字节兼容
    "GEOMETRY_ONLY":  [],                 # 只做通用几何检查，不含标准
    "GB_T_TIER1":     ["gb.sheet_size", "gb.layer_taxonomy", "gb.closed_profile", "gb.title_block"],
    "ISO_216_TIER1":  ["gb.sheet_size"],  # 同一条规则，不同标准
}
```

`SEVERITY_PROFILES` 按 code 映射到各 profile 下的严重级，所以 `E_TITLE_BLOCK` 可以在一个 profile 里是
警告、在另一个里阻断，**规则代码一行不改**。

```python
from cad_deliver.rules import run_profile

for result in run_profile(drawing, "GB_T_TIER1"):
    print(result.code, result.severity.value, result.detail, result.fix)
```

## 命令行

```bash
cad-deliver <目录|文件>... [--profile LEGACY_COMPAT|GB_T_TIER1|GEOMETRY_ONLY] \
                            [--require drawing,pdf] [--out delivery.json] [--json] [--quiet]
```

`--profile` 默认 `LEGACY_COMPAT`。MCP 服务端则默认 `GB_T_TIER1`——需要显式开启才会有人用的标准，等于
不存在；而现有的 `dsh-sw-cad deliver` 调用必须保持原有含义。

`normal` 与 `half` 作为旧写法仍然接受：分别等同于兼容规则集「带」与「不带」半交付取值表。

退出码，以及为什么是三个：

| 码 | 含义 |
|---:|---|
| 0 | 交付成立 |
| 1 | 交付不成立 |
| 2 | **无法判定**——缺少读取器，交付的一部分根本没被检查过 |

`2` 永远不会是「通过」。被跳过的检查，不能报成成功，因为调用方看到 `PASS` 就不再往下看了。

这不是假设：早期版本在没有 `ezdxf` 的机器上，把每一个 DXF 都判成了 `PASS`，因为导入失败只被记成一条
警告，而警告不影响判定。

## 它到底检查什么

| 类型 | 实际检查的内容 |
|---|---|
| `.dxf` | DIMENSION 实体、图层表、`$INSUNITS`、纸空间内容、图幅是否合 ISO 216、有否写明比例、线宽分级、CJK 字体、标注文字是否重叠、标题栏线索、轮廓闭合，以及**被覆盖的标注文字与其标注的几何是否一致** |
| `.dwg` | 版本标记；装了转换器后转成 DXF 完整检查 |
| `.pdf` | 页面尺寸是否合 ISO 216，文字层是否真实存在 |
| `.step` | `FILE_SCHEMA` → AP203/214/242、实体数量、由原始坐标算出的包围盒 |
| `.sldprt` / `.sldasm` | 存在性、大小、文件签名——几何要开应用才能读，它会如实说明 |
| `*_review_report.json` | `evaluation.status`、`issues` 为空，**外加**非空的 `checks` 区块、为真的预览标记，且凡是声称生成了预览图，报告旁边必须真有图片文件 |

## 它不检查什么

公差与配合（`H7/g6`）、材料选择、热处理、尺寸链是否闭合、零件是否可加工。`pass` 的含义是「这个文件经得
起读取」，不是「这张图可以直接下厂」。

## 安装

```bash
pip install cad-deliver-mcp          # 命令行，含 ezdxf 与 PyMuPDF
pip install "cad-deliver-mcp[mcp]"   # 额外提供 MCP 服务端
```

`ezdxf` 与 `pymupdf` 是默认依赖而不是可选依赖，理由是：少了它们，每个 DXF 和每个 PDF 都会变成
`UNKNOWN`，而一个只会说「判不了」的检查器没有安装价值。

## 开发

```bash
pip install -e ".[dev]"

python tests/test_layering.py       # geometry/ 与 rules/ 不导入任何 CAD 库
python tests/test_geometry.py
python tests/test_parsers.py
python tests/test_topology.py       # 闭合：标志位为假、容差、图层过滤
python tests/test_rules.py          # 22 个用例，纯 ParsedDrawing
python tests/test_server.py         # 9 个用例：stage、verify、commit 及全部拒绝路径
python tests/test_legacy_compat.py  # 各 profile 下的退出码 0/1/2
```

`tests/golden_compare.py` 曾在 12 组用例上，把本包与冻结的旧实现逐字段比对，输出 `PARITY OK`。基线
副本此后已删除——两份交付判定逻辑并存，正是这次重构要消除的漂移——所以脚本现在会报
`baseline retired`，除非用 `CAD_DELIVER_LEGACY` 指向一份旧副本。

## 许可

MIT。