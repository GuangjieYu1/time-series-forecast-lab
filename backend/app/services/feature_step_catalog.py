from __future__ import annotations


FEATURE_STEP_DESCRIPTIONS: dict[str, str] = {
    "source_alignment": "校验目标时间与数值是否一一对应，并按时间顺序整理输入序列。",
    "covariate_loader": "载入用户选择的协变量，并按目标时间轴完成对齐和缺失处理。",
    "calendar_generator": "从时间戳生成小时、星期、月份等日历特征。",
    "holiday_generator": "生成节假日及节假日前后等业务日历特征。",
    "lag_generator": "仅使用历史观测生成滞后特征，帮助模型学习过去值的影响。",
    "rolling_generator": "基于历史窗口生成滚动均值、波动率等统计特征。",
    "feature_merge": "把目标、协变量和生成特征合并成统一训练矩阵。",
    "leakage_guard": "检查并阻止使用预测时点之后的信息，降低数据泄漏风险。",
    "feature_selection": "根据有效性和模型能力保留可用于训练的特征。",
    "matrix_ready": "冻结最终特征列顺序和数据类型，供各模型共享使用。",
}


def feature_step_description(step_id: str) -> str:
    return FEATURE_STEP_DESCRIPTIONS.get(step_id, "执行该阶段的数据处理并记录输入、输出与告警。")