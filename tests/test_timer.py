from app.player.timer import PlaybackTimer


def test_not_started_returns_none():
    assert PlaybackTimer().position(10.0) is None


def test_position_advances_from_start():
    t = PlaybackTimer()
    t.start(100.0)
    assert t.position(130.0) == 30.0


def test_pause_freezes_position():
    t = PlaybackTimer()
    t.start(100.0)
    t.pause(110.0)
    assert t.position(150.0) == 10.0


def test_resume_subtracts_paused_time():
    t = PlaybackTimer()
    t.start(100.0)
    t.pause(110.0)
    t.resume(140.0)
    assert t.position(150.0) == 20.0  # 경과 50초 - 정지 30초


def test_multiple_pause_cycles_accumulate():
    t = PlaybackTimer()
    t.start(0.0)
    t.pause(10.0)
    t.resume(20.0)  # 10초 정지
    t.pause(30.0)
    t.resume(35.0)  # 5초 정지
    assert t.position(40.0) == 25.0


def test_double_pause_and_resume_ignored():
    t = PlaybackTimer()
    t.start(0.0)
    t.pause(10.0)
    t.pause(20.0)   # 무시
    t.resume(30.0)
    t.resume(40.0)  # 무시
    assert t.position(40.0) == 20.0


def test_stop_resets():
    t = PlaybackTimer()
    t.start(0.0)
    t.stop()
    assert t.position(10.0) is None


def test_restart_clears_pause_state():
    t = PlaybackTimer()
    t.start(0.0)
    t.pause(5.0)
    t.start(100.0)
    assert t.position(110.0) == 10.0
