# cad-deliver-mcp

[![PyPI](https://img.shields.io/pypi/v/cad-deliver-mcp?logo=pypi)](https://pypi.org/project/cad-deliver-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/27painter/cad-deliver-mcp/blob/main/LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24625649.svg)](https://doi.org/10.5281/zenodo.24625649)

[English](README.md) | 中文

面向 CAD 产物的交付前门禁：**暂存、离线核验、再放行。**

它存在的理由是：*「模型说做完了」不等于交付*。这个服务不需要启动任何商业 CAD 运行时就能解析生成的
CAD 文件，按几何完整性与制图规范判断图纸是否成立；只要某个文件无法被检查，它返回 `UNKNOWN`，而不是
`PASS`。

---

## 快速开始与 MCP 客户端配置

### 安装

```bash
pip install "cad-deliver-mcp[mcp]"   # 命令行 + MCP 服务端
pip install cad-deliver-mcp          # 仅命令行
```

`ezdxf` 与 `PyMuPDF` 是默认依赖，这是有意的：少了它们，每个 DXF 和每个 PDF 都会被报成 `UNKNOWN`，
而一个只会说「判不了」的检查器没有安装价值。若想跟踪仓库而非发布版：

```bash
pip install "cad-deliver-mcp[mcp] @ git+https://github.com/27painter/cad-deliver-mcp.git"
```

### 客户端配置（`mcp_config.json`）

任何支持 MCP 的客户端都能接入，例如 Codex CLI、Claude Code、DeepSeek Harness。把下面这段加进它的
MCP 配置。**Windows 上强烈建议设置 `PYTHONUTF8=1`**，因为国标图层名与标题栏属性都是中文：

```json
{
  "mcpServers": {
    "cad-deliver": {
      "command": "python",
      "args": ["-m", "cad_deliver.server"],
      "env": {
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

本包同时注册了两个命令行入口，所以下面这种写法等价：

```json
{ "mcpServers": { "cad-deliver": { "command": "cad-deliver-mcp", "args": [] } } }
```

---

## 三阶段提交协议

```text
deliver_stage(paths, profile="GB_T_TIER1")  ──▶  STAGED    （复制文件、记录 SHA-256）
deliver_verify(staging_id)                  ──▶  VERIFIED  （离线确定性检查）
deliver_commit(staging_id, target_dir)      ──▶  COMMITTED （原子放行到目标目录）
```

* **`deliver_commit` 只接受 `VERIFIED` 状态。**
* 它在提交时重新计算暂存文件的哈希，核验之后被改动过的文件会被拒绝放行。
* 它拒绝覆盖 `target_dir` 中的同名文件，除非显式传入 `overwrite=True`——同名是版本决策，
  **绝不自动发明 `_1` 或 `_v2` 后缀**。
* **`deliver://audit/{staging_id}`** 作为 MCP 资源暴露完整审计记录：文件哈希、每一次核验尝试、
  结构化发现项，以及确定性的修复指令。

### 状态机买到了什么，没买到什么

它让「已核验」到「已放行」之间的空档变得可见。模型在核验之后又改了文件，提交时的 SHA-256 比对会抓住。

但它**不是**安全沙箱。模型完全可以把文件改完再 stage 一次，拿到干净的 `VERIFIED`。审计库记录
`attempts` 与 `history`，让这种重入循环在审计中可见——这是**协议纪律**，不是安全边界。

### 原子落盘与协议隔离

* **文件落在哪里：** 暂存在 `%TEMP%/cad-deliver-staging/<id>/`（可用 `CAD_DELIVER_STAGING` 覆盖）。
  提交之前不会碰用户的交付目录。提交时每个文件先写成 `<target_dir>/<name>.partial`，刷盘后通过
  `os.replace` 原子提升为正式名——崩溃不会留下半个文件，也避免了跨盘符改名失败。
* **`stdout` 是协议通道：** `stdio` 上的 MCP 用 `stdout` 传 JSON-RPC 帧。`server.py` 在**传输层
  初始化之前的导入阶段**就把 `print` 重定向并把 `logging` 配置到 `stderr`，确保随手的诊断输出不会
  污染协议帧。

---

## 架构与目录结构

```text
src/cad_deliver/
├── models.py          # ParsedDrawing、Check、Verdict、StageState —— 核心契约
├── core.py            # 常量与 SHA-256 文件摘要
├── taxonomy.py        # 七个图层角色、别名表、归一化
├── parsers/           # 唯一允许导入 CAD 库的一层
│   ├── dxf.py         #   ezdxf → ParsedDrawing
│   └── dwg.py         #   DWG → DXF 转换（ODA / LibreDWG / 自定义命令模板）
├── geometry/          # 与制图标准无关的几何完整性检查
│   ├── dxf_checks.py  #   标注、单位、图幅、线宽、字体、标注文字与几何是否一致
│   ├── pdf_checks.py  #   页面尺寸与文字层验证
│   ├── step_checks.py #   FILE_SCHEMA、实体数量、原始坐标包围盒
│   ├── topology.py    #   轮廓闭合：0.01 mm 容差下的悬空端点
│   ├── model_checks.py
│   └── review_checks.py
├── standards.py       # 半交付模式：取值必须来自 standards.json
├── pipeline.py        # 核验内核：一个路径进，一个判定出
├── state_machine.py   # STAGED / VERIFIED / COMMITTED + 持久化审计库
├── server.py          # MCP stdio 接口：3 个工具 + 1 个审计资源
├── rules/             # 可插拔的制图标准规则
│   ├── base.py        #   BaseStandardRule(ABC) + 注册表
│   ├── codes.py       #   稳定的机器码（E_… / W_…）
│   ├── taxonomy.py    #   cad_deliver.taxonomy 的兼容再导出
│   ├── registry.py    #   PROFILES + SEVERITY_PROFILES + 执行器
│   └── gb/            #   GB/T 14689 幅面、GB/T 4457.2 图层与闭合、GB/T 10609.1 标题栏
└── cli.py             # 由 dsh-sw-cad 调用的向后兼容命令行
```

### 被强制的正交分层

| 层 | 知道什么 | 允许导入 |
| :--- | :--- | :--- |
| `parsers/` | 原始 CAD 格式（`.dxf`、`.dwg`、`.pdf`、`.step`） | `ezdxf`、`pymupdf` |
| `geometry/` | 只有 `ParsedDrawing` 事实（不含制图标准） | 标准库 + `models` |
| `rules/` | `ParsedDrawing` 事实 + 某一项制图标准 | 标准库 + `models` |

一条规则就是 `ParsedDrawing` 上的纯函数。它从不打开磁盘文件，也不知道是谁调用了它——profile 单独
决定严重级。只要 `geometry/` 或 `rules/` 导入了 CAD 库，`tests/test_layering.py` 就会让测试失败。

分层有**两种**强制手段，不是一种。导入检查挡住新增依赖；`ParsedDrawing` 上**没有**活文档字段挡住另一
条路——某个实现完全可以把 CAD 对象塞进一个不透明的字段，通过导入扫描，却照样读到文档。
`tests/test_parsers.py` 断言这个属性不会回来。

---

## 制图规则与 Profile

### `GB_T_TIER1` 中的四条规则

| 规则 ID | 标准 | 什么情况下阻断 |
| :--- | :--- | :--- |
| `gb.sheet_size` | GB/T 14689-2008 | 图幅超出 A4–A0（横竖均可，±2 mm 容差） |
| `gb.layer_taxonomy` | GB/T 4457.2-2003 | 标注不在其语义层、轮廓留在 `0` 层，或图层名无法归类 |
| `gb.closed_profile` | GB/T 4457.2-2003 | 轮廓环留下悬空端点（`0.01 mm` 容差下 `degree == 1`） |
| `gb.title_block` | GB/T 10609.1-2008 | 缺少标题栏块引用，或必填属性（`图名` / `图号` / `比例`）为空 |

* **为什么标题栏必须查到属性级：** 只查块是否存在什么也证明不了——空标题栏也是存在的。
  `gb.title_block` 检查 `ATTRIB` 的值，必填字段为空就阻断，而这正是 LLM 模型最容易产出的缺陷。
* **为什么闭合要按端点度数判：** SolidWorks 与 NX 的真实导出经常把视觉上闭合的环写成 DXF
  `closed` 标志位为 `False`、末点与首点重合。只信标志位会在合法工业图上误报——*一个总喊狼来了的门禁
  会被关掉*。端点按 `0.01 mm` 容差吸附，只有真正的悬空顶点（`degree == 1`）才报。
  注意吸附必须用邻域搜索而不是 `round(x / 容差)`：按格子取整只能把半个格内的点合并，0.008 mm 的
  往返误差仍会被判成断点。

每一条失败都附带可执行动作。只说「有问题」的发现项，对 agent 而言就是噪声；闭合规则会报出缺口坐标
以及该怎么补。

### Profile 与严重级覆盖

```python
PROFILES = {
    "LEGACY_COMPAT":  [],                 # 与 dsh-sw-cad 2.2.0 逐字节兼容
    "GEOMETRY_ONLY":  [],                 # 只做通用几何检查，不含制图标准
    "GB_T_TIER1":     ["gb.sheet_size", "gb.layer_taxonomy", "gb.closed_profile", "gb.title_block"],
    "ISO_216_TIER1":  ["gb.sheet_size"],  # 同一条规则在 ISO 216 下复用
}
```

`SEVERITY_PROFILES` 把机器码（`E_TITLE_BLOCK`、`E_SHEET_SIZE` 等）按 profile 映射到 `ERROR` 或
`WARNING`，使得 `GB_T_TIER1` 下可以严格阻断，而 `LEGACY_COMPAT` 下保持向后兼容。

```python
from cad_deliver.rules import run_profile

for result in run_profile(drawing, "GB_T_TIER1"):
    print(result.code, result.severity.value, result.detail, result.fix)
```

---

## 命令行用法与退出码

```bash
cad-deliver <目录|文件>... [--profile LEGACY_COMPAT|GB_T_TIER1|GEOMETRY_ONLY] \
                            [--require drawing,pdf] [--out delivery.json] [--json] [--quiet]
```

* **默认 profile 的差异：** 命令行默认 `LEGACY_COMPAT`，让现有的 `dsh-sw-cad` 工作流保持完全一致的
  向后兼容；而 MCP 服务端默认 `GB_T_TIER1`，让 agent 一接入就处于严格门禁之下。`normal` 与 `half`
  作为 `LEGACY_COMPAT` 的旧写法仍然接受。

| 退出码 | 含义 |
| :---: | :--- |
| **`0`** | **PASS** —— 在当前 profile 下交付成立 |
| **`1`** | **FAIL** —— 至少一项 `ERROR` 级检查失败 |
| **`2`** | **UNKNOWN** —— 无法判定（缺少解析器/转换器，或文件不可读） |

**`2` 永远不会是「通过」。** 被跳过的检查不能伪装成成功，因为下游 agent 看到 `PASS` 就不再往下查了。

即使工具自身跑不起来，这条契约依然成立：`cad-deliver-mcp` 无法导入时，`dsh-sw-cad` 入口仍会写出一份
`verdict: unknown` 的 `delivery.json` 并以 `2` 退出。报告缺席会被调用方理解成*「没什么可抱怨的」*。

---

## 支持的格式与能力边界

| 格式 | 检查内容 |
| :--- | :--- |
| **`.dxf`** | `DIMENSION` 实体、语义图层分类、`$INSUNITS`、纸空间布局、ISO 216 / GB/T 14689 图幅、比例声明、线宽分级、CJK 字体、重叠标注文字、标题栏属性、轮廓闭合，以及被覆盖的标注文字与底层几何是否一致 |
| **`.dwg`** | 版本标记；装有 ODA / LibreDWG 时转换后按 `.dxf` 完整检查 |
| **`.pdf`** | 页面尺寸是否合 ISO 216，以及是否存在真实的矢量文字层 |
| **`.step`** | `FILE_SCHEMA`（AP203 / AP214 / AP242）、实体数量、原始坐标包围盒 |
| **`.sldprt` / `.sldasm`** | 文件存在性、非零大小、二进制签名（没有原生 CAD 运行时时，对内部 B-Rep 几何明确报 `UNKNOWN`） |
| **`*_review_report.json`** | `evaluation.status`、issues 列表为空、checks 区块非空，以及声称生成的预览图在磁盘上确实存在 |

### 明确不做的事

本门禁**不**判断工程设计意图：尺寸公差与配合（`H7/g6`）、材料选择、热处理、尺寸链闭合，以及可加工性。
`PASS` 保证的是结构与制图规范的完整性——不是车间签字放行。

---

## 开发与路线图

```bash
pip install -e ".[dev]"
pytest
```

测试套件同时也是普通脚本，所以 pytest 是可选的：

```bash
python tests/test_rules.py
```

各测试套件：
* `tests/test_layering.py` —— 强制 `geometry/` 与 `rules/` 零 CAD 库导入
* `tests/test_geometry.py` 与 `tests/test_topology.py` —— 包围盒退化、容差吸附的环闭合、图层过滤
* `tests/test_rules.py` —— 28 个单元测试，全部基于纯内存 `ParsedDrawing` 夹具
* `tests/test_server.py` —— 端到端 `stage → verify → commit`、SHA-256 篡改拒绝、同名冲突拒绝
* `tests/test_legacy_compat.py` —— 退出码 `0 / 1 / 2` 与 `LEGACY_COMPAT` 门禁一致性
* `tests/test_packaging.py` —— 版本一致性，以及 PyPI 会在上传时拒绝的分类器

### 路线图
- [x] **核心引擎与 2PC MCP 服务端：** 正交 `ParsedDrawing` 契约、`GB_T_TIER1` 规则集、原子提交库，以及 `dsh-sw-cad` 命令行集成。
- [x] **50 题混合基准集（`benchmarks/`）：** 15 个脱敏的真实 SolidWorks/NX 导出 + 15 个参数化 `ezdxf` 夹具 + 20 个确定性缺陷注入用例，在 G1–G3 基线上评估召回率、误杀率与耗时。

## 归档与引用

与论文 *Abstention Is Not a Pass: Pre-Delivery Verification for LLM-Generated CAD Drawings*（Aochen Wang, School of Mechanical Engineering, Liuzhou Institute of Technology）配套的冻结源码、74 项自动化测试、50 题混合基准集、15 件 AutoCAD 2025 / SolidWorks 2025 导出、24 次闭环修复实验与可复现日志，已永久归档于 Zenodo：

- **DOI：** [10.5281/zenodo.24625649](https://doi.org/10.5281/zenodo.24625649)

## 许可

[MIT](https://github.com/27painter/cad-deliver-mcp/blob/main/LICENSE)