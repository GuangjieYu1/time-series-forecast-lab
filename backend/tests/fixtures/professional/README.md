Professional Forecasting Dataset Fixture

Dataset: ETT-small / ETTh1
Source: https://github.com/zhouhaoyi/ETDataset
Downloaded file: ETTh1.csv

Background:
ETT datasets are commonly used in long-term time-series forecasting research. ETTh1 contains hourly electricity transformer temperature and load features.

Recommended app test:
- file: ETTh1.csv
- data mode: aggregated time series
- time column: date
- target column: OT
- horizon: 24
- testSize: 24
- models: Naive, Seasonal Naive, Moving Average, ARIMA, ETS; Prophet/TimesFM may fail unless optional dependencies are installed.

Notes:
- This CSV is already in row-wise time-series format.
- Use OT as the main univariate target for a clean first acceptance run.
