"""The 2–3%/day owner wish is not what the measured Sharpe is."""
import math

from cryptobot.research.hurdle import compounded_growth, hurdle_verdict, vol_required


def test_two_percent_a_day_compounds_to_more_than_a_thousandfold():
    assert compounded_growth(0.02) > 1000
    assert compounded_growth(0.03) > compounded_growth(0.02)


def test_b4_sharpe_cannot_be_two_percent_a_day():
    sharpe = 4.396271516859604
    dd = 0.004696342385865915
    needed = vol_required(0.02, sharpe)
    # About 8.7% per day. The measured max drawdown is 0.47%.
    assert needed > 0.08
    assert needed > dd
    report = hurdle_verdict(best_sharpe=sharpe, max_drawdown=dd)
    assert report["contradiction"] is True
    assert report["verdict"] == "HURDLE_UNMET"
    assert report["gate"] == "NO-GO"
    assert math.isfinite(report["growth_1y_at_2pct"])
