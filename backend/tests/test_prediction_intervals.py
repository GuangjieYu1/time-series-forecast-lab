from datetime import datetime, timedelta

import numpy as np
import pytest

from app.models.naive import NaiveModel
from app.models.moving_average import MovingAverageModel
from app.models.seasonal_naive import SeasonalNaiveModel
from app.models.arima import ArimaModel


def times(n):
    return [datetime(2025, 1, 1) + timedelta(days=i) for i in range(n)]


@pytest.mark.parametrize('factory', [NaiveModel, MovingAverageModel, SeasonalNaiveModel])
@pytest.mark.parametrize('values', [[1.0], [1.0, 2.0], [2.0] * 12])
def test_short_and_constant_history_has_finite_ordered_intervals(factory, values):
    model = factory()
    model.fit(times(len(values)), values, 'D')
    output = model.predict(4)
    assert np.isfinite(output.lower).all()
    assert np.isfinite(output.upper).all()
    assert np.all(np.asarray(output.lower) <= output.predictions)
    assert np.all(np.asarray(output.upper) >= output.predictions)


@pytest.mark.parametrize('factory', [NaiveModel, MovingAverageModel, SeasonalNaiveModel])
def test_refitting_does_not_reuse_old_uncertainty(factory):
    model = factory()
    values = [float(i * i % 13) for i in range(40)]
    model.fit(times(len(values)), values, 'D')
    model.fit(times(1), [7.0], 'D')
    output = model.predict(2)
    assert output.lower == [7.0, 7.0]
    assert output.upper == [7.0, 7.0]


def test_arima_uses_native_ndarray_confidence_intervals():
    values = [float(i % 7 + i / 10) for i in range(40)]
    model = ArimaModel()
    model.fit(times(len(values)), values, 'D')
    assert model.model is not None
    expected = np.asarray(model.model.get_forecast(steps=5).conf_int(alpha=0.05))
    output = model.predict(5)
    np.testing.assert_allclose(output.lower, expected[:, 0])
    np.testing.assert_allclose(output.upper, expected[:, 1])
    assert not any('interval generation failed' in warning for warning in output.warnings)
