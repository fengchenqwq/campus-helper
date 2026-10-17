# 语音转文字（本地 openai-whisper）
import glob
import os
import shutil
import tempfile

_model = None


def _ensure_ffmpeg():
    """确保 ffmpeg 在 PATH 中（whisper 依赖 ffmpeg 解码音频）。"""
    if shutil.which('ffmpeg'):
        return
    # 自动查找 winget 安装的 ffmpeg，并加入 PATH
    candidates = glob.glob(
        os.path.expanduser('~/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg*/**/ffmpeg.exe'),
        recursive=True,
    )
    if candidates:
        os.environ['PATH'] = os.path.dirname(candidates[0]) + os.pathsep + os.environ.get('PATH', '')


_ensure_ffmpeg()


def _get_model():
    global _model
    if _model is None:
        import whisper
        _model = whisper.load_model('base')
    return _model


def transcribe(audio_bytes: bytes) -> str:
    """将音频字节转为文字。"""
    model = _get_model()
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name
    try:
        result = model.transcribe(tmp_path)
        return result['text'].strip()
    finally:
        os.unlink(tmp_path)
