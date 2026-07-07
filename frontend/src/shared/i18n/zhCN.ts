export const zhCN = {
  productName: "时序预测实验室",
  productNameEn: "Time Series Forecast Lab",
  productTagline: "上传表格，比较模型，解释结果，一键生成预测报告。",
  nav: {
    overview: "首页概览",
    upload: "数据导入",
    forecast: "预测实验",
    models: "模型库",
    experiments: "实验历史",
    feedback: "反馈中心",
    settings: "API 设置"
  },
  status: {
    backend: "后端连接",
    device: "计算设备",
    timesfm: "TimesFM",
    deepseek: "DeepSeek",
    connected: "已连接",
    unavailable: "不可用",
    notConfigured: "未配置",
    checking: "检测中"
  },
  common: {
    loading: "加载中...",
    empty: "暂无数据",
    failed: "失败",
    success: "成功",
    available: "可用",
    unavailable: "不可用",
    uploadFile: "上传文件",
    changeData: "更换数据",
    open: "打开",
    delete: "删除",
    search: "搜索",
    details: "详情",
    runExperiment: "运行实验",
    finalForecast: "最终预测",
    recommended: "推荐",
    status: "状态",
    reason: "原因",
    seconds: "秒"
  },
  terms: {
    residual: "Residual（残差）",
    mae: "MAE（平均绝对误差）",
    mse: "MSE（均方误差）",
    rmse: "RMSE（均方根误差）",
    wape: "WAPE（加权绝对百分比误差）",
    holdout: "Holdout（留出测试集）"
  },
  modelDescriptions: {
    naive: "朴素预测模型，默认未来值等于最后一个观测值，适合作为最低基线。",
    seasonal_naive: "季节性朴素模型，未来值等于上一个周期同位置的历史值，适合周周期或月周期明显的数据。",
    moving_average: "移动平均模型，使用最近窗口平均值预测未来，适合平滑短期波动。",
    arima: "经典统计模型，通过自回归、差分和移动平均刻画时间序列自相关结构。",
    ets: "指数平滑模型族，适合趋势和季节性相对稳定的业务数据。",
    prophet: "可解释的可加模型，强调趋势、季节性和节假日效应。",
    timesfm: "Google 提出的时间序列基础模型，强调跨领域 zero-shot 预测能力。",
    xgboost: "基于 lag 特征、滚动统计和日历特征的梯度提升树回归模型，适合非线性业务序列。",
    lightgbm: "基于 lag 特征、滚动统计和日历特征的高效梯度提升树模型，适合较快完成机器学习基线对比。",
    random_forest: "基于 lag 特征、滚动统计和日历特征的随机森林回归模型，稳健但外推趋势能力有限。",
    nbeats: "深度学习预测模型，通过神经基展开进行单变量预测；当前版本先展示计划状态。",
    nhits: "层级插值深度学习预测模型，适合长预测步长场景；当前版本先展示计划状态。",
    patchtst: "Patch 化 Transformer 时间序列模型，面向长序列预测；当前版本先展示计划状态。",
    chronos: "Amazon 提出的时间序列基础模型，强调把时间序列转成语言式 token；当前版本先展示计划状态。",
    moirai: "Salesforce 提出的通用时间序列基础模型，面向多领域预测；当前版本先展示计划状态。",
    lag_llama: "Llama 风格的概率时间序列预测模型，强调不确定性估计；当前版本先展示计划状态。"
  },
  charts: {
    actualVsPredicted: "真实值 vs 预测值",
    residualTimeline: "残差时间序列",
    metricBar: "指标对比",
    residualDistribution: "残差分布",
    predictedResidualScatter: "预测值 vs 残差",
    absoluteErrorTimeline: "绝对误差时间序列",
    normalizedMetric: "归一化指标对比",
    finalForecast: "最终未来预测",
    history: "历史数据",
    actual: "真实值",
    predicted: "预测值",
    lower: "下界",
    upper: "上界"
  }
};

export type ZhCN = typeof zhCN;
