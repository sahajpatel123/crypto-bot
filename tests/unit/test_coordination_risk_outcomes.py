"""RiskOutcomeSink protocol test (manager-owned). A recording stub of the
shape E-003 will build must satisfy the runtime-checkable protocol."""

from cryptobot.coordination import RiskOutcomeSink


class RecordingSink:
    def __init__(self):
        self.calls = []

    def note_fill_delta(self, reservation_id, exec_id, symbol, venue_side,
                          qty, price, fee, ts_utc):
        self.calls.append(("delta", reservation_id, exec_id))

    def note_fill(self, reservation_id):
        self.calls.append(("fill", reservation_id))

    def release(self, reservation_id):
        self.calls.append(("release", reservation_id))
        return True

    def note_flat(self):
        self.calls.append(("flat",))


def test_recording_stub_satisfies_protocol():
    sink = RecordingSink()
    assert isinstance(sink, RiskOutcomeSink)
    sink.note_fill("r1")
    assert sink.release("r2") is True
    sink.note_flat()
    assert sink.calls == [("fill", "r1"), ("release", "r2"), ("flat",)]
