# Benchmark Summary

- schema: `0.5`
- suite: `all`
- profile: `fast`
- agent mode: `offline`
- total cases: `11`
- successful API runs: `11`
- failed API runs: `0`
- failed assertions: `0`
- warning assertions: `0`
- generated at: `2026-07-08T13:28:10.667954+00:00`

| case | suite | category | passed | rows | best_mae | run | seconds | assertions |
| --- | --- | --- | --- | ---: | ---: | --- | ---: | ---: |
| daily_clean | stability | clean | True | 90 | 0 | 200 | 1.743 | 1 |
| daily_dirty | stability | dirty | True | 80 | 14.259 | 200 | 0.8519 | 1 |
| daily_edge_short | stability | edge | True | 12 | 2 | 200 | 0.6494 | 1 |
| large_hourly | stability | large | True | 120000 | 6.68869 | 200 | 7.8308 | 1 |
| etth1_smoke | stability | clean | True | 17420 | 0.860065 | 200 | 2.9638 | 1 |
| raw_detail_sum | aggregation_correctness | aggregation | True | 10 | 6 | 200 | 0.4832 | 2 |
| raw_detail_mean | aggregation_correctness | aggregation | True | 10 | 8 | 200 | 0.4897 | 2 |
| raw_detail_count | aggregation_correctness | aggregation | True | 10 | 0.5 | 200 | 0.4934 | 2 |
| repro_daily_clean | reproducibility | reproducibility | True | - | - | 200 | 1.4503 | 16 |
| feature_lift_covariate_effect | feature_lift | feature | True | - | - | 200 | 3.2261 | 4 |
| workbench_agent_golden_routes | agent_routing | agent | True | - | - | 200 | 0.0125 | 4 |

## daily_clean

- suite: `stability`
- category: `clean`
- passed: `True`
- warning count: `1`

### assertions

| assertion | status | message |
| --- | --- | --- |
| api_run_success | passed | Forecast API run must complete successfully. |

### model results

| model | status | MAE | RMSE | WAPE | warnings | error |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| ETS | success | 0 | 0 | 0 | 0 | - |
| Naive | success | 15 | 17.0294 | 0.100671 | 0 | - |
| Moving Average | success | 21 | 22.4944 | 0.14094 | 0 | - |

## daily_dirty

- suite: `stability`
- category: `dirty`
- passed: `True`
- warning count: `4`

### assertions

| assertion | status | message |
| --- | --- | --- |
| api_run_success | passed | Forecast API run must complete successfully. |

### model results

| model | status | MAE | RMSE | WAPE | warnings | error |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| ARIMA | success | 14.259 | 22.268 | 0.0854342 | 0 | - |
| Naive | success | 20.9 | 28.2259 | 0.125225 | 0 | - |
| Moving Average | success | 25.7571 | 32.2301 | 0.154327 | 0 | - |

## daily_edge_short

- suite: `stability`
- category: `edge`
- passed: `True`
- warning count: `2`

### assertions

| assertion | status | message |
| --- | --- | --- |
| api_run_success | passed | Forecast API run must complete successfully. |

### model results

| model | status | MAE | RMSE | WAPE | warnings | error |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Naive | success | 2 | 2.16025 | 0.0952381 | 0 | - |
| Moving Average | success | 5 | 5.06623 | 0.238095 | 0 | - |

## large_hourly

- suite: `stability`
- category: `large`
- passed: `True`
- warning count: `0`

### assertions

| assertion | status | message |
| --- | --- | --- |
| api_run_success | passed | Forecast API run must complete successfully. |

### model results

| model | status | MAE | RMSE | WAPE | warnings | error |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Moving Average | success | 6.68869 | 8.10004 | 0.0026669 | 0 | - |
| Naive | success | 8.06103 | 9.57077 | 0.00321407 | 0 | - |

## etth1_smoke

- suite: `stability`
- category: `clean`
- passed: `True`
- warning count: `2`

### assertions

| assertion | status | message |
| --- | --- | --- |
| api_run_success | passed | Forecast API run must complete successfully. |

### model results

| model | status | MAE | RMSE | WAPE | warnings | error |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| XGBoost | success | 0.860065 | 0.924568 | 0.088837 | 1 | - |
| Naive | success | 0.940958 | 1.00719 | 0.0971926 | 0 | - |

## raw_detail_sum

- suite: `aggregation_correctness`
- category: `aggregation`
- passed: `True`
- warning count: `2`

### assertions

| assertion | status | message |
| --- | --- | --- |
| golden_series_length | passed | 聚合后的时间点数量必须与 golden series 一致。 |
| golden_series_values | passed | 聚合后的数值必须与 golden series 对齐。 |

### model results

| model | status | MAE | RMSE | WAPE | warnings | error |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Naive | success | 6 | 7.2111 | 0.25 | 0 | - |

## raw_detail_mean

- suite: `aggregation_correctness`
- category: `aggregation`
- passed: `True`
- warning count: `3`

### assertions

| assertion | status | message |
| --- | --- | --- |
| golden_series_length | passed | 聚合后的时间点数量必须与 golden series 一致。 |
| golden_series_values | passed | 聚合后的数值必须与 golden series 对齐。 |

### model results

| model | status | MAE | RMSE | WAPE | warnings | error |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Naive | success | 8 | 8.544 | 0.470588 | 0 | - |

## raw_detail_count

- suite: `aggregation_correctness`
- category: `aggregation`
- passed: `True`
- warning count: `2`

### assertions

| assertion | status | message |
| --- | --- | --- |
| golden_series_length | passed | 聚合后的时间点数量必须与 golden series 一致。 |
| golden_series_values | passed | 聚合后的数值必须与 golden series 对齐。 |

### model results

| model | status | MAE | RMSE | WAPE | warnings | error |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Naive | success | 0.5 | 0.707107 | 0.333333 | 0 | - |

## repro_daily_clean

- suite: `reproducibility`
- category: `reproducibility`
- passed: `True`
- warning count: `0`

### assertions

| assertion | status | message |
| --- | --- | --- |
| manifest_datasetHash | passed | Manifest datasetHash 必须一致。 |
| manifest_configHash | passed | Manifest configHash 必须一致。 |
| manifest_featurePipelineVersion | passed | Manifest featurePipelineVersion 必须一致。 |
| manifest_runtimeEventSchemaVersion | passed | Manifest runtimeEventSchemaVersion 必须一致。 |
| manifest_randomSeed | passed | Manifest randomSeed 必须一致。 |
| aggregated_series_hash | passed | 聚合后的历史序列 hash 必须一致。 |
| metric_naive_mae | passed | naive mae 必须在容差内复现。 |
| metric_naive_mse | passed | naive mse 必须在容差内复现。 |
| metric_naive_rmse | passed | naive rmse 必须在容差内复现。 |
| metric_naive_wape | passed | naive wape 必须在容差内复现。 |
| metric_moving_average_mae | passed | moving_average mae 必须在容差内复现。 |
| metric_moving_average_mse | passed | moving_average mse 必须在容差内复现。 |
| metric_moving_average_rmse | passed | moving_average rmse 必须在容差内复现。 |
| metric_moving_average_wape | passed | moving_average wape 必须在容差内复现。 |
| backtest_predictions | passed | backtest predictions/residual 必须一致。 |
| recommended_model | passed | 推荐模型必须一致。 |

## feature_lift_covariate_effect

- suite: `feature_lift`
- category: `feature`
- passed: `True`
- warning count: `0`

### assertions

| assertion | status | message |
| --- | --- | --- |
| positive_feature_run_success | passed | 启用/禁用协变量的正例实验都必须运行成功。 |
| positive_feature_lift | passed | 正例中协变量参入后 MAE 至少改善 15%。 |
| noise_covariate_not_overclaimed | passed | 噪声协变量不应造成超过 10% 的性能退化。 |
| static_use_test_values_documented | passed | static use_test_values 必须只体现在回测策略说明中，最终预测仍保持 repeat_last_known。 |

## workbench_agent_golden_routes

- suite: `agent_routing`
- category: `agent`
- passed: `True`
- warning count: `0`

### assertions

| assertion | status | message |
| --- | --- | --- |
| route_accuracy | passed | 离线黄金集 route accuracy 必须 >= 90%。 |
| schema_validity | passed | Agent 响应 schema validity 必须为 100%。 |
| leakage_warning_recall | passed | 泄漏风险召回率必须 >= 95%。 |
| unsupported_promise_count | passed | unsupported 场景不能承诺后续执行接口。 |
