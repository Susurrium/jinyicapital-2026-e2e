# A 成员：数据与输入编码

本目录保存个人负责的 A 模块：数据适配、字段与时间合同、冻结预处理、惰性窗口、输入编码、审计工具、参照模型以及交接材料。方案见 [A 成员方案](docs/A成员数据与输入编码方案.md)，规则参照见 [比赛规则与流程](docs/比赛规则与流程.md)。

## 安装与验证

使用 Python 3.12。在本目录执行：

```powershell
.\tools\setup.ps1
.venv\Scripts\python.exe tools\smoke.py --output work\synthetic-check
```

`setup.ps1` 使用 `uv.lock` 安装依赖并运行测试。合成流程输出目录必须尚不存在。常规使用所需 Qlib 组件已包含于 `src/ptop/_vendor/qlib/`；只有显式原版对照验证需要外部 Qlib。

## 模块

| 模块 | 职责 |
| --- | --- |
| `schema`、`data`、`official` | raw25 字段、单位、观测掩码、规范数据和官方查询接口 |
| `windows` | 显式分钟网格、当日窗口、完整决策截面和引用原始行并集 |
| `preprocessing` | N0/N1/N2 拟合、尺度诊断、冻结、JSON 保存及变换 |
| `encoders`、`models` | 原始拼接、ALSTM、Net、分组、Patch、DeepLOB 及完整参照模型 |
| `targets`、`output` | 标签支持区间、时间折跨界检查及逐时点输出覆盖审核 |
| `bundle` | 九种固定候选与 v2 JSON 模型包 |
| `local_archive`、`local_preflight`、`preprocessing_audit` | 真实数据授权环境中的审计、数值与预处理检查工具 |

输入为 `float32[B,L,25]`、`bool observed[B,L,25]`、`bool step_valid[B,L]`，True 表示有效。字段顺序固定为 `ptop.schema.FEATURES`。全空窗口须在模型调用前分流；标准化仅拟合训练窗口引用的唯一原始行，推理复用冻结状态。

本目录的模型包格式为 v2。完整训练集成使用 [project/](../project/README.md) 的 v3/v4 保存协议。两部分使用各自的环境和模型包。

## 文档与交接

[开发验证记录](docs/开发验证记录.md)列出可公开验证材料；[内置组件验证](docs/内置Qlib组件验证.md)说明来源与等价检查。历史交接说明见 [handoff/](handoff/README.md)，归档文件见 [deliverables/](deliverables/)。

Qlib 来源与许可见 [vendor/NOTICE.md](vendor/NOTICE.md) 和内置组件目录；历史 Windows wheel 随其对应许可证保存。原始行情、标签、映射、完整文档和真实数据分析结果见 [完整归档](../ARCHIVE.md)。
