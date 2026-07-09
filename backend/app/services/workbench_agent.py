from __future__ import annotations

import os
import re
from typing import Iterable

from app.schemas import (
    WorkbenchCovariatePlan,
    WorkbenchCustomModelSpec,
    WorkbenchCustomModelValidateResponse,
    WorkbenchDataSearchPlan,
    WorkbenchDataSourceCandidate,
    WorkbenchDataSourceSearchRequest,
    WorkbenchIdeaAnalyzeRequest,
    WorkbenchIdeaAnalyzeResponse,
    WorkbenchIdeaRoute,
    WorkbenchOnlineObservation,
)

DATA_KEYWORDS = {
    "holiday", "节假日", "假期", "春节", "天气", "weather", "temperature", "气温",
    "油价", "fuel", "oil", "航油", "促销", "promotion", "活动", "股票", "股价",
    "指数", "行情", "macro", "宏观", "gdp", "cpi", "汇率", "利率", "价格", "外部数据",
}
MODEL_KEYWORDS = {
    "自定义模型", "模型构想", "损失函数", "loss", "objective", "分层模型", "hierarchical",
    "鲁棒", "robust", "分段趋势", "piecewise", "状态空间", "architecture", "结构", "ensemble",
    "集成", "约束", "先验", "bayesian", "贝叶斯", "异常鲁棒",
}
CLARIFY_KEYWORDS = {"优化", "提升", "更准", "改进", "想法", "试试看", "看看"}
UNSUPPORTED_KEYWORDS = {"内幕", "未授权", "密码", "个人隐私", "身份证", "爬取账号", "绕过权限", "敏感客户"}
UNKNOWN_FUTURE_KEYWORDS = {"股票", "股价", "行情", "油价", "天气", "宏观", "gdp", "cpi", "汇率", "利率"}
KNOWN_FUTURE_KEYWORDS = {"节假日", "假期", "星期", "日历", "促销计划", "排班", "航班计划"}

DATA_SOURCE_REGISTRY = [
    WorkbenchDataSourceCandidate(
        id="holiday_calendar_cn",
        name="中国节假日日历",
        category="built_in",
        description="由 Holiday Generator 生成节假日、节日前后窗口和距离特征。",
        frequencySupport=["D", "W", "M"],
        futureAvailability="known_future",
        implementationStatus="available",
    ),
    WorkbenchDataSourceCandidate(
        id="same_sheet_future_rows",
        name="同一 Sheet 未来空目标行",
        category="user_upload",
        description="用户在同一表格中提供未来时间点的协变量，目标列留空。",
        frequencySupport=["H", "D", "W", "M", "Q", "Y"],
        futureAvailability="known_future",
        implementationStatus="available",
    ),
    WorkbenchDataSourceCandidate(
        id="user_covariate_csv",
        name="用户上传协变量 CSV/XLSX",
        category="user_upload",
        description="上传与目标时间轴可对齐的外部数据，进入 Covariate Loader。",
        frequencySupport=["H", "D", "W", "M", "Q", "Y"],
        futureAvailability="unknown_future",
        implementationStatus="available",
        warnings=["普通外部数据若未来不可知，默认不得直接进入最终预测矩阵。"],
    ),
    WorkbenchDataSourceCandidate(
        id="market_index_connector_placeholder",
        name="行情/指数连接器占位",
        category="connector_placeholder",
        description="用于登记股票指数、商品价格、油价等外部行情来源；当前版本不自动抓取。",
        frequencySupport=["D", "W", "M"],
        futureAvailability="unknown_future",
        implementationStatus="placeholder",
        warnings=["行情数据通常存在发布延迟，forecast 时需要先预测或按 analysis-only 丢弃。"],
    ),
    WorkbenchDataSourceCandidate(
        id="weather_connector_placeholder",
        name="天气连接器占位",
        category="connector_placeholder",
        description="用于登记历史天气或天气预报来源；当前版本只生成接口计划。",
        frequencySupport=["H", "D"],
        futureAvailability="unknown_future",
        implementationStatus="placeholder",
        warnings=["历史天气不能在回测中读取测试段真实未来值。"],
    ),
    WorkbenchDataSourceCandidate(
        id="macro_indicator_registry",
        name="宏观指标登记表",
        category="external_registry",
        description="用于登记 GDP、CPI、汇率、利率等低频外部指标，不自动下载。",
        frequencySupport=["M", "Q", "Y"],
        futureAvailability="unknown_future",
        implementationStatus="placeholder",
        warnings=["低频指标发布滞后，必须记录可用时间，避免数据泄漏。"],
    ),
]


def analyze_idea(request: WorkbenchIdeaAnalyzeRequest) -> WorkbenchIdeaAnalyzeResponse:
    idea = _normalize(request.idea)
    route = _classify_route(idea)
    return WorkbenchIdeaAnalyzeResponse(
        route=route,
        confidence=_confidence(route),
        rationale=_rationale(route),
        requiredInputs=_required_inputs(route),
        dataSearchPlan=_build_data_search_plan(request.idea, route),
        candidateDataSources=search_data_sources(
            WorkbenchDataSourceSearchRequest(
                query=request.idea,
                domain=request.context.domain,
                frequency=request.context.frequency,
                route=route,
            )
        ).candidates,
        covariatePlan=_build_covariate_plan(idea, route),
        customModelSpec=build_custom_model_spec(request.idea, request.context) if route in {"custom_model", "hybrid"} else None,
        leakageWarnings=_leakage_warnings(idea, route),
        nextApiCalls=_next_api_calls(route),
        onlineObservation=_online_observation(request.mode, route),
    )


def search_data_sources(request: WorkbenchDataSourceSearchRequest):
    from app.schemas import WorkbenchDataSourceSearchResponse

    query = _normalize(request.query)
    frequency = (request.frequency or "").upper()
    ranked: list[WorkbenchDataSourceCandidate] = []
    for candidate in DATA_SOURCE_REGISTRY:
        haystack = _normalize(" ".join([candidate.id, candidate.name, candidate.description, candidate.futureAvailability]))
        if frequency and candidate.frequencySupport and frequency not in candidate.frequencySupport:
            continue
        if not query or any(token in haystack for token in _tokens(query)) or _source_matches_query(candidate, query):
            ranked.append(candidate)
    if not ranked:
        ranked = [item for item in DATA_SOURCE_REGISTRY if item.id in {"user_covariate_csv", "same_sheet_future_rows"}]
    return WorkbenchDataSourceSearchResponse(query=request.query, candidates=ranked)


def build_custom_model_spec(idea: str, context) -> WorkbenchCustomModelSpec:
    normalized = _normalize(idea)
    target = context.targetColumn or "target"
    if any(word in normalized for word in ["分层", "hierarchical"]):
        objective = "按业务层级共享信息，同时保留局部序列差异。"
        training = "先按层级聚合训练全局组件，再对单序列残差做局部校准。"
    elif any(word in normalized for word in ["鲁棒", "异常", "robust"]):
        objective = "降低异常点对模型参数和预测区间的影响。"
        training = "使用鲁棒损失或异常点权重衰减，并输出异常敏感性诊断。"
    elif any(word in normalized for word in ["分段", "piecewise"]):
        objective = "捕捉结构性变点前后的不同趋势。"
        training = "先检测候选变点，再在分段趋势上叠加季节和残差项。"
    elif any(word in normalized for word in ["loss", "损失"]):
        objective = "用业务损失函数替代默认 MAE 排名口径。"
        training = "将自定义损失约束在 backtest scoring 层，不执行用户代码。"
    else:
        objective = "把用户模型构想整理为可评审、可实现的非执行规格。"
        training = "先定义输入、训练目标、预测接口和失败隔离，再决定是否实现。"
    return WorkbenchCustomModelSpec(
        modelId=_slugify(idea)[:48] or "custom_time_series_model",
        displayName="自定义时间序列模型草案",
        objective=objective,
        requiredInputs=["time", target, "frequency", "horizon"],
        trainingStrategy=training,
        predictionInterface="fit(history, covariates, config) -> predict(horizon, future_covariates)",
        safetyNotes=["第一版只生成规格，不执行任意用户代码。", "新增模型必须接入统一失败隔离和 Manifest。"],
        executableCodeAllowed=False,
    )


def validate_custom_model_spec(spec: WorkbenchCustomModelSpec) -> WorkbenchCustomModelValidateResponse:
    errors: list[str] = []
    warnings: list[str] = []
    if spec.executableCodeAllowed:
        errors.append("当前版本不允许执行自定义模型代码，只允许保存规格。")
    if not spec.objective:
        errors.append("缺少 objective。")
    if not spec.predictionInterface:
        errors.append("缺少 predictionInterface。")
    if not spec.requiredInputs:
        warnings.append("未声明 requiredInputs，后续无法做复现校验。")
    normalized = spec.model_copy(deep=True)
    normalized.executableCodeAllowed = False
    return WorkbenchCustomModelValidateResponse(valid=not errors, errors=errors, warnings=warnings, normalizedSpec=normalized)


def _classify_route(idea: str) -> WorkbenchIdeaRoute:
    if any(word in idea for word in UNSUPPORTED_KEYWORDS):
        return "unsupported"
    data = any(word in idea for word in DATA_KEYWORDS)
    model = any(word in idea for word in MODEL_KEYWORDS)
    if data and model:
        if any(word in idea for word in {"加入", "加进", "参入", "接入", "作为特征", "协变量", "外部变量"}):
            return "hybrid"
        return "custom_model"
    if model:
        return "custom_model"
    if data:
        return "feature_engineering_data"
    return "clarify"


def _build_data_search_plan(idea: str, route: WorkbenchIdeaRoute) -> WorkbenchDataSearchPlan | None:
    if route not in {"feature_engineering_data", "hybrid", "clarify"}:
        return None
    return WorkbenchDataSearchPlan(
        query=idea,
        intent="寻找可与目标时间轴对齐的协变量来源，并判断未来是否可知。",
        requiredFields=["time", "value", "available_at"],
        suggestedJoinKeys=["time", "frequency_bucket"],
        candidateApiCalls=["POST /api/workbench-agent/data-sources/search", "POST /api/forecast/run"],
    )


def _build_covariate_plan(idea: str, route: WorkbenchIdeaRoute) -> WorkbenchCovariatePlan | None:
    if route not in {"feature_engineering_data", "hybrid", "clarify"}:
        return None
    if any(word in idea for word in KNOWN_FUTURE_KEYWORDS):
        cov_type = "known_future"
        backtest = "使用测试集时间轴可提前知道的日历或计划字段。"
        forecast = "由日历生成器或用户未来空目标行提供。"
    elif any(word in idea for word in UNKNOWN_FUTURE_KEYWORDS):
        cov_type = "static"
        backtest = "v0.4 主流程只支持 known_future / static；默认按 static 处理，并建议优先使用 repeat_last_known 或 historical_mean。"
        forecast = "最终预测不会读取真实未来值；如数据未来未知，只能作为 advisory 提示，不直接生成第三种 runnable covariate 类型。"
    else:
        cov_type = "static"
        backtest = "训练、回测和预测均重复最后已知值。"
        forecast = "Repeat last known value。"
    return WorkbenchCovariatePlan(
        suggestedColumns=_suggested_columns(idea),
        covariateType=cov_type,
        backtestPolicy=backtest,
        forecastPolicy=forecast,
        leakagePolicy="所有协变量必须记录 available_at，禁止使用预测时点不可获得的真实未来值。",
    )


def _leakage_warnings(idea: str, route: WorkbenchIdeaRoute) -> list[str]:
    warnings: list[str] = []
    if route in {"feature_engineering_data", "hybrid"} and any(word in idea for word in UNKNOWN_FUTURE_KEYWORDS):
        warnings.append("该想法包含未来不可知或存在发布延迟的数据，默认不能直接进入最终预测矩阵。")
        warnings.append("回测时必须使用当时可获得的数据版本，不能读取测试段真实未来值。")
    return warnings


def _next_api_calls(route: WorkbenchIdeaRoute) -> list[str]:
    if route == "feature_engineering_data":
        return ["POST /api/workbench-agent/data-sources/search", "POST /api/forecast/run"]
    if route == "custom_model":
        return ["POST /api/workbench-agent/custom-models/spec", "POST /api/workbench-agent/custom-models/validate"]
    if route == "hybrid":
        return ["POST /api/workbench-agent/data-sources/search", "POST /api/workbench-agent/custom-models/spec", "POST /api/workbench-agent/custom-models/validate"]
    return []


def _required_inputs(route: WorkbenchIdeaRoute) -> list[str]:
    if route == "feature_engineering_data":
        return ["数据源名称", "时间列", "可用时间 available_at", "未来是否可知"]
    if route == "custom_model":
        return ["模型目标", "训练输入", "预测接口", "失败隔离策略"]
    if route == "hybrid":
        return ["外部数据源", "未来可用性", "模型规格", "公平对比基线"]
    if route == "clarify":
        return ["想优化的业务目标", "可用数据", "希望改变 feature 还是模型"]
    return []


def _rationale(route: WorkbenchIdeaRoute) -> str:
    return {
        "feature_engineering_data": "想法主要是在现有模型前加入可对齐的外部变量，适合进入 Feature Engineering。",
        "custom_model": "想法主要改变模型结构、目标函数或训练方式，适合沉淀为自定义模型规格。",
        "hybrid": "想法同时包含外部数据参入和模型结构变化，需要拆成数据接口与模型规格两条线。",
        "clarify": "当前描述不足以判断应改数据还是改模型，需要补充目标与数据条件。",
        "unsupported": "该想法涉及敏感、未授权或不可复现的数据访问，当前工作台不支持。",
    }[route]


def _confidence(route: WorkbenchIdeaRoute) -> float:
    return {"feature_engineering_data": 0.9, "custom_model": 0.9, "hybrid": 0.86, "unsupported": 0.9}.get(route, 0.62)


def _online_observation(mode: str, offline_route: WorkbenchIdeaRoute) -> WorkbenchOnlineObservation | None:
    if mode == "offline":
        return None
    if not os.getenv("DEEPSEEK_API_KEY"):
        return WorkbenchOnlineObservation(attempted=False, status="not_configured", message="未配置 DEEPSEEK_API_KEY，已仅记录离线规则引擎结果。", route=offline_route)
    return WorkbenchOnlineObservation(attempted=False, status="skipped", message="v0.5 benchmark 中 DeepSeek 在线评分为非阻断观测项；当前接口不自动发起外部请求。", route=offline_route)


def _suggested_columns(idea: str) -> list[str]:
    columns: list[str] = []
    mapping = [
        ("节假日", "is_holiday_period"), ("假期", "holiday_count"), ("天气", "weather_index"),
        ("气温", "temperature"), ("油价", "fuel_price"), ("航油", "jet_fuel_price"),
        ("促销", "promotion_flag"), ("股票", "market_index"), ("指数", "market_index"),
        ("宏观", "macro_indicator"), ("gdp", "gdp"), ("cpi", "cpi"),
    ]
    for keyword, column in mapping:
        if keyword in idea and column not in columns:
            columns.append(column)
    return columns or ["external_covariate"]


def _source_matches_query(candidate: WorkbenchDataSourceCandidate, query: str) -> bool:
    if any(word in query for word in ["节假日", "假期", "日历"]):
        return candidate.id == "holiday_calendar_cn"
    if any(word in query for word in ["股票", "指数", "行情", "油价", "宏观", "cpi", "gdp", "汇率", "利率"]):
        return candidate.category in {"connector_placeholder", "external_registry", "user_upload"}
    if any(word in query for word in ["天气", "气温"]):
        return candidate.id in {"weather_connector_placeholder", "user_covariate_csv"}
    return False


def _tokens(value: str) -> Iterable[str]:
    return [token for token in re.split(r"\W+", value.lower()) if token]


def _normalize(value: str) -> str:
    return str(value or "").strip().lower()


def _slugify(value: str) -> str:
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return ascii_part or "custom_model"
