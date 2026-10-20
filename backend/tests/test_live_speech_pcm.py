from app.services.live_speech_pcm import frame_pcm, unframe_pcm


def test_frame_round_trip() -> None:
    framed = frame_pcm(12, b"\x00\x01\x02\x03")
    assert unframe_pcm(framed) == (12, b"\x00\x01\x02\x03")


def test_unframe_rejects_short_payload() -> None:
    assert unframe_pcm(b"\x00\x01") is None
