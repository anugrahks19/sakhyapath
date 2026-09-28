from __future__ import annotations

from fractions import Fraction

import av
import numpy as np

from app.ingest.capture import CaptureWorker


class StubDatabase:
    def __init__(self):
        self.health = []

    def camera(self, _camera_id):
        return {"stream_generation": 0}

    def update_health(self, *_args):
        self.health.append(_args)


class FakeFrame:
    time_base = Fraction(1, 1000)

    def __init__(self, pts, brightness):
        self.pts = pts
        self.brightness = brightness

    def to_ndarray(self, *, format):
        assert format == "bgr24"
        return np.full((36, 64, 3), self.brightness, dtype=np.uint8)


class FakePacket:
    def __init__(self, frames=None, invalid=False):
        self.frames = frames or []
        self.invalid = invalid

    def decode(self):
        if self.invalid:
            raise av.error.InvalidDataError(0, "join-warning")
        return self.frames


class FakeContainer:
    def __init__(self, packets):
        self.packets = packets

    def demux(self, *, video):
        assert video == 0
        return iter(self.packets)


def test_join_warning_variable_pts_and_scene_discontinuity():
    db = StubDatabase()
    worker = CaptureWorker("camera-a", db, idle_seconds=1000, on_exit=lambda *_: None)
    worker.acquire()
    frames = [FakeFrame(0, 0), FakeFrame(100, 0), FakeFrame(450, 0),
              FakeFrame(900, 255), FakeFrame(100, 255)]
    container = FakeContainer([FakePacket(invalid=True)] +
                              [FakePacket([frame]) for frame in frames])
    assert worker._decode(container, "government_live") == 5
    assert worker.frame_sequence == 5
    assert worker.latest.source_pts == 0.1
    assert worker.latest.pts_timebase == "1/1000"
    assert worker.generation >= 2  # Abrupt scene cut and PTS reset.
    assert worker.latest.source_mode == "government_live"
    assert worker.decoded_connected is True
    assert db.health
