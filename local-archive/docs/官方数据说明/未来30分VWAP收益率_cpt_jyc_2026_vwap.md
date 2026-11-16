# 未来30分VWAP收益率（cpt_jyc_2026_vwap）

记录日期：2026 年 10 月 11 日。

数据表：`cpt_jyc_2026_vwap`。

来源地址：[进益资本空间数据表页面](https://jinyicapital.bigquant.com/data/datasources/cpt_jyc_2026_vwap)。

内容依据：用户在对话中提供的平台表结构文本。下表保留字段名称、类型和描述原文。当前浏览工具未取得在线页面正文。

## 表结构

| 字段 | 字段类型 | 字段描述 |
| --- | --- | --- |
| date | timestamp[ns] | 采样时点（未来30分钟窗口起点） |
| instrument | string | 股票或指数代码 |
| vwap_return | float | 窗口终点价格相对未来30分钟VWAP的收益率 |
| vwap | float | 未来30分钟成交量加权平均价 |
| end_price | float | 未来30分钟窗口终点最新有效成交价 |
| volume | int64 | 未来30分钟成交量 |
| amount | double | 未来30分钟成交额（元） |
| num_trades | int32 | 未来30分钟成交笔数 |
