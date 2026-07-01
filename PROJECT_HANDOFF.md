# Time Series Forecast Lab 项目完整记录

> 更新时间：2026-06-29  
> 当前版本：v0.1 加固版  
> 项目名称：`time-series-forecast-lab`

## 1. 项目目标

Time Series Forecast Lab 是一个中文 AI 时间序列预测实验工作台，核心闭环为：

```text
上传 CSV / XLS / XLSX
  -> 后端解析与字段识别
  -> Sheet 选择和前 100 行预览
  -> 基础数据清洁
  -> 构建聚合时间序列
  -> 多模型 Holdout 回测
  -> residual 和指标排名
  -> 多图表对比
  -> 推荐并选择最终模型
  -> 使用完整历史预测未来
  -> 保存实验历史
  -> 可选生成 DeepSeek 中文报告
```

系统不永久保存上传的原始文件，也不将完整业务明细写入数据库。

## 2. 项目位置与访问地址

### 本地正式仓库

```text
D:\VisualStudioProjects\AgentDevelopment\time-series-forecast-lab
```

### Codex 工作区副本

```text
C:\Users\11926\Documents\Codex\2026-06-25\codex-plan-v2-time-series-forecast\time-series-forecast-lab
```

### 本地地址

```text
前端：http://127.0.0.1:5173
后端：http://127.0.0.1:8100
```

### 公网部署

```text
http://39.106.96.209
```

服务器环境：

- Ubuntu 22.04.5 LTS
- Nginx
- systemd 服务：`time-series-forecast-lab`
- 部署目录：`/opt/time-series-forecast-lab`
- 当前无域名和 HTTPS
- 服务器约 1.6 GB RAM、2 GB Swap

## 3. 技术栈

### 前端

- React
- Vite
- TypeScript
- TailwindCSS
- ECharts
- TanStack Table
- Zustand
- React Router

### 后端

- Python
- FastAPI
- Pydantic
- Pandas
- OpenPyXL
- xlrd
- SQLAlchemy
- SQLite
- Uvicorn
- Statsmodels / StatsForecast
- Prophet
- TimesFM
- PyTorch
- XGBoost
- LightGBM
- scikit-learn

## 4. 当前页面

| 路径 | 页面 | 状态 |
|---|---|---|
| `/` | 产品首页和系统状态 | 已完成 |
| `/upload` | 数据上传、Sheet 和字段预览 | 已完成 |
| `/forecast` | 数据清洁、实验配置、实时进度和结果 | 已完成 |
| `/models` | 模型库、时间线和科技树 | 已完成 |
| `/experiments` | 实验历史 | 已完成 |
| `/experiments/:id` | 实验详情和图表回放 | 已完成 |
| `/settings` | DeepSeek API 设置 | 已完成 |

## 5. 文件上传与解析

支持：

- `.csv`
- `.xlsx`
- `.xls`

处理原则：

- 浏览器不解析完整大文件。
- 文件上传到后端临时目录。
- 前端只接收前 100 行预览。
- Excel 支持多个 Sheet。
- CSV 和 Excel 均由后端识别列名、类型、样例值和空值数量。

临时文件目录：

```text
backend/tmp/uploads
```

临时文件规则：

1. 通过 `uploadId` 访问。
2. 实验完成后删除。
3. 实验异常时也执行清理。
4. 服务启动时清理过期文件。
5. 原始文件不进入 SQLite。

## 6. 时间格式支持

第一版支持：

- `2026-06-01`
- `2026/06/01`
- `2026.06.01`
- `20260601`
- `2026-06`
- `2026/06`
- `2026年6月1日`
- `2026-06-01 12:00:00`
- `2026/06/01 12:00:00`
- `2026-06-01T12:00:00`
- Excel serial date
- Unix timestamp seconds
- Unix timestamp milliseconds
- 科学计数法日期，例如 `2.0230102E7`

特别规则：

- `20230102` 优先按 `yyyyMMdd` 解析。
- 普通业务数值列不会仅因为可解释为 Excel serial date 就被误判为时间列。
- Excel serial date 需要时间字段名称提示或明确时间上下文。

## 7. 时间粒度

支持：

- `H`：小时
- `D`：日
- `W`：周
- `M`：月
- `Q`：季度
- `Y`：年

识别依据：

1. 解析时间值。
2. 排序。
3. 分析相邻时间差。
4. 使用众数和中位数推断频率。
5. 年月格式优先识别为月。
6. 年格式优先识别为年。

约束：

- 不允许选择比源数据更细的预测粒度。
- 日粒度不能预测小时。
- 月粒度不能预测日或小时。

## 8. 数据模式

### 已聚合时间序列

示例：

```csv
date,passenger_count
2026-06-01,12000
2026-06-02,12500
```

处理：

- 选择时间列和一个或多个目标列。
- 重复时间根据用户策略处理。
- 按时间排序后构建序列。

### 原始明细数据

示例：

```csv
flight_no,flight_date,airport,passenger_count
CZ001,2026-06-01,CAN,180
CZ002,2026-06-01,CAN,210
```

支持聚合方式：

- `sum`
- `mean`
- `count`
- `max`
- `min`

## 9. 基础数据清洁

数据清洁只作用于本次实验构建的序列，不修改上传原文件。

### 清洁能力

- 清理时间列和目标列首尾空白。
- 支持千分位数值，例如 `1,200`。
- 删除无法解析的时间。
- 将目标列转换为数值。
- 识别空值、无效数值、正负无穷。
- 自动按时间排序。
- 检测并处理重复时间。
- 检测缺失时间点。
- 检测 IQR 异常值。

### 缺失值策略

- 删除缺失值，默认且最保守。
- 线性插值。
- 前向填充，并在开头使用后向填充。
- 填充为 0。

同一策略同时用于：

- 原文件目标列缺失值。
- 补齐时间轴后产生的缺失时间点。

### 重复时间策略

已聚合数据支持：

- 平均值
- 求和
- 保留第一条
- 保留最后一条

原始明细数据使用用户选择的聚合方式。

### 异常值策略

- 默认仅检测，不修改。
- 可选使用 IQR 边界截尾。
- IQR 倍数可设置为 `1.0` 至 `5.0`，默认 `1.5`。

### 清洁审计

结果中保存并展示：

- 无效时间数量
- 原始目标缺失数量
- 无效目标数值数量
- 重复时间数量
- 缺失时间点数量
- 填充值数量
- 异常值数量
- 被调整异常值数量
- 清洁动作列表
- 丢弃行数量

## 10. 多目标处理

第一阶段不做真正的多变量联合建模。

当用户选择多个目标列时：

- 每个目标列独立运行一轮单变量预测。
- 排行榜和图表按目标列分组。
- 前端显示能力提示。

## 11. 模型库

### 当前可运行模型

- Naive
- Seasonal Naive
- Moving Average
- ARIMA
- ETS
- Prophet
- XGBoost
- LightGBM
- Random Forest Regressor
- TimesFM

### 计划中模型

- Linear Trend
- SARIMA
- Theta
- TBATS
- CatBoost
- N-BEATS
- N-HiTS
- DeepAR
- TFT
- PatchTST
- Chronos
- Moirai
- Lag-Llama

计划中模型只用于模型库展示，不能被选入实验，也不会伪造预测结果。

### 模型能力元数据

模型注册表包含：

- 模型 ID 和名称
- 分类
- 简介
- 论文标题和链接
- 单变量支持
- 多目标支持
- 协变量支持
- 置信区间支持
- 最小和最大 horizon
- GPU 要求
- Foundation Model 标记
- MVP 可用状态
- 安装状态和不可用原因
- 安装命令

## 12. 模型资源压力

预测配置页显示：

- 绿色：无压力
- 黄色：有压力
- 红色：高压力
- 灰色：无法运行

当前运行前内存压力仍是工程估算，不是模型官方工具返回值。

估算依据：

- 文件大小
- 预估行数
- 列数
- 原始或聚合模式
- 目标列数量
- horizon
- testSize
- 模型基础内存
- 模型数据倍率
- 主机可用内存
- GPU 状态

模型完成后，后端会记录真实：

- `fitSeconds`
- `predictSeconds`

## 13. 实时进度上报

前端已取消固定时间权重模拟，改为后端真实阶段事件。

### 进度接口

```text
GET /api/forecast/progress/{runId}
GET /api/forecast/progress/{runId}/events
```

第二个接口使用 Server-Sent Events。

### 真实阶段

- 校验实验配置
- 读取文件和 Sheet
- 清洁并构建时间序列
- 模型拟合
- 模型预测
- residual 和指标计算
- 模型成功或失败
- 模型排名
- 保存实验
- 完成

每个模型独立展示：

- 排队中
- 拟合中
- 预测中
- 计算指标
- 已完成
- 失败
- 阶段百分比
- 拟合耗时
- 预测耗时
- 错误信息

说明：

- 模型库不提供内部迭代比例时，只展示后端确认的真实阶段。
- 快速模型的阶段事件带历史缓冲，不会因 SSE 轮询间隔丢失。
- 单模型失败不会终止整个实验。

## 14. Holdout 回测

完整序列长度为 `T`，测试集长度为 `testSize`：

```text
训练集 = 前 T - testSize 个点
测试集 = 最后 testSize 个点
```

默认：

```text
testSize = horizon
```

约束：

- 测试集至少 1 个点。
- 测试集不能覆盖全部序列。
- 训练数据少于 30 个点时返回警告。

## 15. Residual 和指标

Residual 定义：

```text
residual = actual - predicted
```

含义：

- residual 大于 0：模型低估。
- residual 小于 0：模型高估。

指标：

- MSE
- MAE
- RMSE
- WAPE

WAPE：

```text
sum(abs(actual - predicted)) / sum(abs(actual))
```

当真实值绝对值之和为 0 时：

- WAPE 返回 `null`。
- 返回受控 warning。
- 实验不会崩溃。

默认按 MAE 从小到大排名。

## 16. 最终预测

流程：

1. 系统按最低 MAE 推荐模型。
2. 用户可以接受推荐或手动选择其他成功模型。
3. 最终模型使用完整历史数据重新拟合。
4. 预测未来 `horizon` 个点。
5. 支持区间的模型返回 `lower` 和 `upper`。

测试集对比图不显示区间。

最终未来预测图只显示最终模型的预测区间。

## 17. 图表

已实现 8 类 ECharts 图表：

1. 测试集实际值与多模型预测
2. Residual 时间序列
3. 指标对比柱状图
4. Residual 分布图
5. Predicted 与 Residual 散点图
6. Absolute Error 时间序列
7. 归一化指标对比图
8. 最终未来预测图

另有模型排行榜表格。

统一规则：

- Actual 使用最醒目的主线。
- TimesFM 使用紫色。
- Prophet 使用蓝色。
- ARIMA 使用橙色。
- ETS 使用绿色。
- XGBoost 使用红色。
- LightGBM 使用青色。
- Random Forest 使用粉色。
- Naive 使用灰色虚线。
- Moving Average 使用黄色。
- 所有图表共用 `modelColorMap`。

默认展示：

- Top 3 模型
- 成功运行的 TimesFM

TimesFM 失败时不会强制显示。

## 18. 模型库视觉

模型库有三种视图：

- 分层模型卡片
- 多泳道模型发展时间线
- 暗色企业级技术科技树

科技树：

- 自上而下。
- 主路线居中。
- 支线向两侧展开。
- 尽量减少节点和连线交叉。
- 推荐路线使用发光连线。
- 可运行、未安装、需下载、计划中使用不同状态颜色。
- 点击节点打开详情抽屉。
- Hover 高亮上下游路径。

时间线：

- 从左向右。
- 基线、统计、机器学习、深度学习、Transformer、基础模型分泳道。
- 同年模型错位，减少重叠。
- 点击模型打开详情。

## 19. 移动端支持

最新移动端导航修复：

- 手机顶部提供菜单按钮。
- 点击后打开左侧导航抽屉。
- 点击模块后自动关闭抽屉。
- 点击遮罩关闭。
- 按 Esc 关闭。
- 打开抽屉时锁定背景滚动。
- 导航项提供足够触摸尺寸。
- 顶部状态标签支持横向滚动。
- 手机端主题按钮使用紧凑图标。
- 科技树和时间线支持横向触摸滚动。

相关提交：

```text
f70d810 Fix mobile navigation drawer
```

## 20. 实验历史

SQLite 保存：

- 实验 ID
- 实验名称
- 文件名
- Sheet 名称
- 字段信息
- 时间列
- 目标列
- 聚合方式
- 清洁配置和清洁审计
- 模型选择
- 指标结果
- Backtest 图表数据
- 最终预测
- 模型运行日志
- 失败模型状态
- 创建时间
- DeepSeek 报告

不保存：

- 原始上传文件
- 完整原始明细
- 敏感业务数据表

历史详情页不依赖 `tmp/uploads`，删除原始临时文件后仍可完整回放。

## 21. API

### 系统

```text
GET /api/health
GET /api/models
GET /api/models/device
```

### 上传

```text
POST /api/upload/preview
GET /api/upload/{uploadId}/sheets/{sheetName}/preview
```

### 预测

```text
POST /api/forecast/run
POST /api/forecast/final
GET /api/forecast/progress/{runId}
GET /api/forecast/progress/{runId}/events
```

### 历史

```text
GET /api/experiments
GET /api/experiments/{experimentId}
DELETE /api/experiments/{experimentId}
```

### DeepSeek

```text
POST /api/llm/deepseek/test
POST /api/reports/generate
```

统一错误格式：

```json
{
  "message": "可读错误信息",
  "code": "ERROR_CODE",
  "details": {}
}
```

## 22. DeepSeek 报告

报告面板支持：

- 配置 API Key
- 测试连接
- 生成中文报告
- 业务或技术风格
- 短、中、长篇幅
- 模型比较
- Residual 分析
- 最终预测
- 风险和 warning
- 保存报告到实验历史

核心环境不依赖 DeepSeek。

未配置 API Key 时不影响上传、清洁、回测和预测。

## 23. 测试数据

基础 fixture：

```text
backend/tests/fixtures/daily_air_passengers.csv
backend/tests/fixtures/monthly_air_passengers.xlsx
backend/tests/fixtures/raw_flight_detail_multi_sheet.xlsx
backend/tests/fixtures/invalid_date.csv
backend/tests/fixtures/duplicate_dates.xlsx
backend/tests/fixtures/missing_values.xlsx
backend/tests/fixtures/short_series.csv
backend/tests/fixtures/legacy_daily_air_passengers.xls
```

专业测试集：

```text
backend/tests/fixtures/professional/ETTh1.csv
```

ETTh1 约有 17,420 个小时级数据点。

## 24. 高负载模型测试结果

本机测试环境：

- 约 16 GB RAM
- NVIDIA GeForce RTX 4060 Ti
- 当前 PyTorch 为 CPU 版本
- TimesFM 实际走 CPU
- 测试集：ETTh1
- 目标列：`OT`
- `horizon=24`
- `testSize=24`

| 模型 | 状态 | MAE | RMSE | WAPE | 进程峰值工作集 |
|---|---|---:|---:|---:|---:|
| Random Forest | 成功 | 0.5774 | 0.7320 | 5.96% | 约 721 MB |
| TimesFM | 成功 | 0.6097 | 0.7627 | 6.30% | 约 2.41 GB |
| LightGBM | 成功 | 0.7112 | 0.7688 | 7.35% | 约 500 MB |
| XGBoost | 成功 | 0.8562 | 0.9185 | 8.84% | 约 332 MB |
| Prophet | 成功 | 1.8858 | 1.9677 | 19.48% | 约 537 MB |

TimesFM 最终预测：

- 使用 17,420 个历史点。
- 返回 24 个未来点。
- 所有预测值为有限数。
- 24 个置信区间全部有效。
- 最终预测阶段峰值工作集约 2.86 GB。
- 峰值私有内存约 4.90 GB。

注意：

- TimesFM 请求结束后，PyTorch 分配器可能保留约 2.4 GB 工作集。
- 重启后端可立即释放。
- 1.6 GB RAM 的云服务器不适合实际运行 TimesFM。

## 25. 自动化测试

已覆盖：

- 时间格式解析
- 科学计数法日期
- Excel serial date
- Unix 秒和毫秒
- H/D/W/M/Q/Y 粒度
- 粒度约束
- Raw 聚合
- Aggregated 模式
- 缺失值策略
- 缺失时间点
- 重复时间策略
- 千分位数值
- 空白清理
- IQR 异常值
- Holdout 边界
- Residual 定义
- MSE/MAE/RMSE/WAPE
- WAPE 零分母
- NaN 预测失败隔离
- Fit 和 predict 异常隔离
- 模型实时阶段事件
- 进度历史缓冲
- 上传清理
- 历史回放
- 字段类型误判修复

最近验证：

- 后端全量测试 36 项通过。
- 新增字段识别与清洁相关回归通过。
- 前端 `npm run typecheck` 通过。
- 前端 `npm run build` 通过。

## 26. 本地启动

### 后端

```powershell
cd D:\VisualStudioProjects\AgentDevelopment\time-series-forecast-lab\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8100
```

或：

```powershell
uvicorn app.main:app --reload --port 8100
```

### 前端

```powershell
cd D:\VisualStudioProjects\AgentDevelopment\time-series-forecast-lab\frontend
npm run dev
```

### 前端检查

```powershell
npm run typecheck
npm run build
```

### 后端检查

```powershell
cd D:\VisualStudioProjects\AgentDevelopment\time-series-forecast-lab
.\backend\.venv\Scripts\python.exe -m pytest
```

## 27. 可选依赖

文件：

```text
backend/requirements-optional.txt
```

核心环境可以不安装 Prophet 和 TimesFM。

未安装可选模型时：

- 模型列表显示不可用原因。
- 单模型失败被隔离。
- 其他模型继续运行。
- 排行榜排除失败模型。
- 历史保存失败状态。

TimesFM：

- 首次允许联网下载。
- 后续使用本地缓存。
- 模型缓存位于 `backend/.model_cache`。
- 下载失败只影响 TimesFM。

## 28. 部署方式

前端：

- Vite 生产构建。
- Nginx 服务 `frontend/dist`。

后端：

- FastAPI + Uvicorn。
- systemd 管理。
- 服务名称：`time-series-forecast-lab`。

常用服务器检查：

```bash
systemctl status time-series-forecast-lab
systemctl status nginx
curl http://127.0.0.1:8100/api/health
free -m
df -h
```

## 29. 关键提交

```text
79c702a Refine model map layout for mobile
07d6a3f Add realtime progress and data cleaning
f70d810 Fix mobile navigation drawer
```

其他相关提交：

```text
5a2a992 Redesign model timeline and tech tree
c1debbc Add chart scaling and model load indicators
38d515f Add model progress and library views
590c3ed Avoid selecting TimesFM by default
722d171 Improve forecast experiment progress UI
```

## 30. Git 状态

本地仓库当前没有配置 `origin`。

已连接的 GitHub 账户没有可写的同名仓库。

因此：

- 版本已经本地提交。
- 版本已经部署到阿里云。
- GitHub 推送仍需一个有写权限的仓库 URL。

不要将搜索到的其他同名公开仓库误设为远端。

## 31. 已知限制

1. 第一阶段不是多变量联合预测。
2. 暂不支持外生变量。
3. 暂不支持 Rolling Backtest。
4. 暂不支持自动调参。
5. 暂不支持自动模型集成。
6. PatchTST、Chronos、Moirai 等仍为计划中。
7. 云服务器内存不足以稳定运行 TimesFM。
8. 本机虽然有 NVIDIA GPU，但当前 PyTorch 是 CPU 构建。
9. TimesFM 运行后可能保留较大内存，建议使用独立工作进程隔离。
10. 前端主 bundle 超过 500 KB，后续应进行路由和图表代码分包。
11. 公网目前使用 HTTP，没有域名和 HTTPS。
12. 当前没有用户账号、权限和认证系统。
13. 内存压力仍是运行前估算，尚未使用历史实测自动校准。

## 32. 推荐后续顺序

### P0：稳定性

1. 为模型任务增加独立 worker 进程。
2. TimesFM 完成后自动释放 worker。
3. 增加任务取消和超时。
4. 增加并发队列。
5. 用历史实测数据校准 RAM 和耗时估算。

### P1：部署安全

1. 配置域名。
2. 配置 HTTPS。
3. 限制 SSH 安全组来源。
4. 增加最基础的访问认证。
5. 增加日志轮转和服务监控。

### P2：产品体验

1. 增加清洁后序列预览。
2. 增加清洁前后对比。
3. 增加异常值可视化确认。
4. 增加实验复制和重新运行。
5. 增加路由级代码分包。
6. 继续优化手机端图表和表格。

### P3：建模扩展

在 v0.1 稳定后再考虑：

- Rolling Backtest
- Covariates
- 自动调参
- PatchTST
- N-BEATS
- N-HiTS
- Chronos
- Moirai
- 自动模型集成

## 33. v0.1 验收结论

当前版本已形成完整可运行闭环：

```text
文件导入
  + Sheet 选择
  + 字段识别
  + 基础数据清洁
  + 时间序列构建
  + 多模型回测
  + 实时模型进度
  + Residual 和指标
  + 图表与排行榜
  + 最终预测
  + 历史回放
  + 可选 AI 报告
```

可以继续进行真实业务文件验收，但在扩展更多深度模型之前，应优先处理任务进程隔离、服务器资源限制、HTTPS 和访问安全。
