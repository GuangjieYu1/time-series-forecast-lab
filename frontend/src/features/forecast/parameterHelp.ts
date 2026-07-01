export interface ParameterHelp {
  title: string;
  description: string;
  increaseEffect: string;
  decreaseEffect: string;
  recommended: string;
}

const parameterHelp: Record<string, ParameterHelp> = {
  "moving_average.window": {
    title: "窗口长度",
    description: "决定移动平均会回看多少个历史点。",
    increaseEffect: "更平滑，更抗噪，但对突变反应更慢。",
    decreaseEffect: "更灵敏，更容易跟随短期波动，但也更容易抖动。",
    recommended: "日频从 7 或 14 起步；周内周期明显时优先用 7。"
  },
  "arima.p": {
    title: "AR 阶 p",
    description: "控制模型向过去观测值回看的深度。",
    increaseEffect: "能表达更长的自相关，但更容易过拟合。",
    decreaseEffect: "结构更简单，更稳，但可能欠拟合。",
    recommended: "通常先从 1 到 2 开始。"
  },
  "arima.d": {
    title: "差分 d",
    description: "决定序列为了更平稳需要差分几次。",
    increaseEffect: "更强地去除趋势，但可能损失真实结构。",
    decreaseEffect: "保留更多原始趋势，但平稳性可能不足。",
    recommended: "大多数业务序列优先试 0 或 1。"
  },
  "arima.q": {
    title: "MA 阶 q",
    description: "控制模型如何吸收短期随机扰动。",
    increaseEffect: "更能拟合短期噪声模式，但复杂度更高。",
    decreaseEffect: "更简洁，但可能漏掉局部扰动。",
    recommended: "通常先从 1 开始。"
  },
  "prophet.seasonalityMode": {
    title: "季节性模式",
    description: "控制季节波动是按固定幅度变化，还是随趋势同比例放大。",
    increaseEffect: "切到 multiplicative 后，旺季/低谷会随总体水平一起放大。",
    decreaseEffect: "保持 additive 时，季节振幅更稳定。",
    recommended: "数据量随总体规模扩大而同步放大时优先 multiplicative。"
  },
  "prophet.changepointPriorScale": {
    title: "趋势拐点灵活度",
    description: "控制 Prophet 对趋势转折的敏感程度。",
    increaseEffect: "更容易追随结构变化，但更容易过拟合局部噪声。",
    decreaseEffect: "趋势更平滑稳定，但会更迟钝。",
    recommended: "先从 0.05 起步，波动剧烈时再提高。"
  },
  "xgboost.nEstimators": {
    title: "树数量",
    description: "决定 boosting 过程总共叠加多少棵树。",
    increaseEffect: "表达力更强，但训练更慢，也更可能过拟合。",
    decreaseEffect: "训练更快，但上限更低。",
    recommended: "先配合较小学习率，从 120 到 300 之间试。"
  },
  "xgboost.maxDepth": {
    title: "最大深度",
    description: "控制每棵树能学到多复杂的切分关系。",
    increaseEffect: "更能拟合复杂模式，但更吃内存，也更容易过拟合。",
    decreaseEffect: "更稳更快，但可能欠拟合。",
    recommended: "时序 lag 特征通常从 2 到 5 开始。"
  },
  "xgboost.learningRate": {
    title: "学习率",
    description: "控制每轮 boosting 的步长。",
    increaseEffect: "收敛更快，但波动更大。",
    decreaseEffect: "更稳但通常需要更多树。",
    recommended: "0.03 到 0.1 是常见起点。"
  },
  "lightgbm.nEstimators": {
    title: "树数量",
    description: "控制 LightGBM 累积多少轮弱学习器。",
    increaseEffect: "拟合能力增强，但训练耗时和过拟合风险上升。",
    decreaseEffect: "更快，但容量更小。",
    recommended: "200 到 400 是较稳妥的常用区间。"
  },
  "lightgbm.numLeaves": {
    title: "叶子数",
    description: "决定每棵树分裂后的复杂程度。",
    increaseEffect: "能表达更细的非线性结构，但更容易过拟合。",
    decreaseEffect: "更保守，泛化通常更稳。",
    recommended: "31 是一个很常见的起点。"
  },
  "lightgbm.learningRate": {
    title: "学习率",
    description: "控制每一轮树对最终预测的影响大小。",
    increaseEffect: "学习更激进，但结果更容易不稳定。",
    decreaseEffect: "更稳，但通常需要更多树数量配合。",
    recommended: "0.03 到 0.08 往往比较平衡。"
  },
  "random_forest.nEstimators": {
    title: "树数量",
    description: "决定森林中包含多少棵树。",
    increaseEffect: "结果更稳定，但训练更慢。",
    decreaseEffect: "训练更快，但方差更大。",
    recommended: "120 到 220 通常够用。"
  },
  "random_forest.maxDepth": {
    title: "最大深度",
    description: "控制单棵树能长多深。",
    increaseEffect: "拟合能力更强，但更可能过拟合噪声。",
    decreaseEffect: "更稳更省内存，但可能欠拟合。",
    recommended: "12 到 24 比较常见。"
  },
  "random_forest.minSamplesLeaf": {
    title: "叶节点最少样本",
    description: "限制叶子节点至少保留多少样本。",
    increaseEffect: "更平滑，抗过拟合更强。",
    decreaseEffect: "更灵活，但容易学到噪声。",
    recommended: "先从 2 开始。"
  },
  "timesfm.maxContext": {
    title: "上下文长度",
    description: "决定模型最多会读取多少历史点作为上下文。",
    increaseEffect: "可利用更长历史，但更吃显存和内存。",
    decreaseEffect: "更轻量，但长周期信息可能不足。",
    recommended: "先按默认 512，内存吃紧时再降。"
  },
  "timesfm.normalizeInputs": {
    title: "输入归一化",
    description: "在送入基础模型前先对输入幅度做归一化。",
    increaseEffect: "开启后通常更稳，尤其在量级变化很大时。",
    decreaseEffect: "关闭后保留原始幅度，但有时更不稳定。",
    recommended: "默认保持开启。"
  }
};

export function getParameterHelp(modelId: string, parameterKey: string): ParameterHelp | null {
  return parameterHelp[`${modelId}.${parameterKey}`] ?? null;
}
