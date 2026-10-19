"""T0.4: doctor must label the configured engine truthfully.

Regression: engine_kind="live" configs fell through to the
reference-fake-venue label, misreporting a venue engine as the fake.
No network: doctor only imports the adapter module for live configs.
"""
import argparse

from cryptobot import cli


def _doctor(capsys, config):
    rc = cli.cmd_doctor(argparse.Namespace(config=config, capture=None))
    return rc, capsys.readouterr().out


def test_doctor_labels_live_engine_not_reference(capsys):
    rc, out = _doctor(capsys, "configs/prod.toml")
    assert "binance-live" in out
    assert "reference-fake-venue" not in out
    assert rc == 0


def test_doctor_labels_demo_live_engine(capsys):
    rc, out = _doctor(capsys, "configs/demo.toml")
    assert "binance-live" in out
    assert "demo=True" in out
    assert rc == 0


def test_doctor_labels_reference_engine(capsys):
    rc, out = _doctor(capsys, "configs/paper.toml")
    assert "reference-fake-venue" in out
    assert rc == 0
