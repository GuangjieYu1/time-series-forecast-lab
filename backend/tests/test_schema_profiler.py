from app.services.schema_profiler import infer_column_type


def test_small_numeric_business_values_are_not_excel_dates():
    assert infer_column_type([100, 130, None], "passenger_count") == "number"


def test_yyyymmdd_numeric_values_remain_datetime():
    assert infer_column_type([20230102, 20230103], "event_date") == "datetime"


def test_excel_serial_dates_require_a_time_column_hint():
    assert infer_column_type([45292, 45293], "flight_date") == "datetime"
    assert infer_column_type([45292, 45293], "sales_amount") == "number"


def test_common_date_strings_are_datetime():
    assert infer_column_type(["2026-06-01", "2026/06/02"], "value") == "datetime"
