# 1分钟K线（cpt_jyc_2026_stock_bar1m）

记录日期：2026 年 10 月 11 日。

数据表：`cpt_jyc_2026_stock_bar1m`。

来源地址：[进益资本空间数据表页面](https://jinyicapital.bigquant.com/data/datasources/cpt_jyc_2026_stock_bar1m)。

内容依据：用户在对话中提供的平台表结构文本。下表保留字段名称、类型和描述原文。当前浏览工具未取得在线页面正文。

## 表结构

| 字段 | 字段类型 | 字段描述 |
| --- | --- | --- |
| date | timestamp[ns] | 日期(bar结束时刻) |
| instrument | string | 股票代码 |
| instrument_id | int16 | 股票代码ID |
| adjust_factor | float | 复权因子 |
| pre_close | float | 前收盘价 |
| high | float | 最高价 |
| open | float | 开盘价 |
| low | float | 最低价 |
| close | float | 收盘价 |
| deal_number | int64 | 区间成交笔数 |
| volume | int64 | 区间成交量 |
| amount | double | 区间成交额 |
| ask_price1 | float | 1档委卖价 |
| ask_price2 | float | 2档委卖价 |
| ask_price3 | float | 3档委卖价 |
| ask_price4 | float | 4档委卖价 |
| ask_price5 | float | 5档委卖价 |
| bid_price1 | float | 1档委买价 |
| bid_price2 | float | 2档委买价 |
| bid_price3 | float | 3档委买价 |
| bid_price4 | float | 4档委买价 |
| bid_price5 | float | 5档委买价 |
| ask_volume1 | int32 | 1档委卖量 |
| ask_volume2 | int32 | 2档委卖量 |
| ask_volume3 | int32 | 3档委卖量 |
| ask_volume4 | int32 | 4档委卖量 |
| ask_volume5 | int32 | 5档委卖量 |
| bid_volume1 | int32 | 1档委买量 |
| bid_volume2 | int32 | 2档委买量 |
| bid_volume3 | int32 | 3档委买量 |
| bid_volume4 | int32 | 4档委买量 |
| bid_volume5 | int32 | 5档委买量 |
| ask_num_orders1 | int32 | 卖1档委托笔数 |
| ask_num_orders2 | int32 | 卖2档委托笔数 |
| ask_num_orders3 | int32 | 卖3档委托笔数 |
| ask_num_orders4 | int32 | 卖4档委托笔数 |
| ask_num_orders5 | int32 | 卖5档委托笔数 |
| bid_num_orders1 | int32 | 买1档委托笔数 |
| bid_num_orders2 | int32 | 买2档委托笔数 |
| bid_num_orders3 | int32 | 买3档委托笔数 |
| bid_num_orders4 | int32 | 买4档委托笔数 |
| bid_num_orders5 | int32 | 买5档委托笔数 |
