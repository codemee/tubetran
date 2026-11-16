"""faster-whisper 讀得了音檔（不需要下載模型）。

回歸：av 19 拿掉了 av.open() 的 metadata_errors 參數，faster-whisper 1.2.1 讀音檔時還在傳它，
無字幕影片一走到語音辨識就失敗（TypeError: open() got an unexpected keyword argument 'metadata_errors'）。
pyproject.toml 因此限制 av<19；升級 av 或 faster-whisper 時，這個測試會告訴你能不能放寬。"""
import math
import struct
import wave

from faster_whisper import decode_audio


def test_faster_whisper_can_decode_an_audio_file(tmp_path):
    path = tmp_path / "tone.wav"
    rate = 44100
    with wave.open(str(path), "wb") as w:  # 0.5 秒、440 Hz 的雙聲道音檔
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(struct.pack("<hh", v, v) for v in
                          (int(8000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(rate // 2)))
        w.writeframes(frames)
    audio = decode_audio(str(path))
    assert abs(len(audio) - 8000) <= 50  # 轉成 16 kHz 單聲道：0.5 秒 ≈ 8000 個取樣
    assert float(abs(audio).max()) > 0.1
