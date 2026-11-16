# 本地分区训练与实验

`ptop.local_training.LocalBarStore` 按 Arrow batch 读取月度 Feather，为选定日期生成私人日分区缓存。`prepare_local_fold` 通过 A 的规范化、窗口和冻结预处理向 Trainer 提供可重入 loader。

正式入口使用 `local_training_factory`，配置须显式提供数据目录、cache、expected、股票映射、分钟网格、LabelSpec、时间折，以及 targets 或 labels/support。必要合同不完整时在读取行情前报错。

`diagnostic_training_factory` 只用于工程检查，目标由样本键人工构造。诊断结果不用于金融预测评价，也不导出正式提交包。示例配置中的路径对应原验证环境，执行前填写本人的授权路径。

实验矩阵支持九种 A 候选和四种 B 主干、多窗口、多 seed、独立时间预算、状态报告和协议指纹。学习后的 token 不进入缓存。模型比较保持预处理、采样键、目标及预算一致。

完整 CLI 见 [训练交接](b_training_handoff.md)，配置示例位于 [configs/](../configs/)。真实数据、派生统计、分区 cache 和诊断日志保留在授权环境。
