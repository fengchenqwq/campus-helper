# 语音转文字（faster-whisper，CTranslate2 加速，输出简体中文）
import glob
import os
import shutil
import tempfile

_model = None
_cc = None

# 本地 faster-whisper 模型目录（从 ModelScope 下载）
_MODEL_DIR = os.path.expanduser('/home/ubuntu/faster-whisper-models/models/pengzhendong--faster-whisper-base/snapshots/master')


def _ensure_ffmpeg():
    """确保 ffmpeg 在 PATH 中（whisper 依赖 ffmpeg 解码音频）。"""
    if shutil.which('ffmpeg'):
        return
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
        from faster_whisper import WhisperModel
        # 本地模型 + int8 量化，CPU 上速度快
        if os.path.isdir(_MODEL_DIR):
            _model = WhisperModel(_MODEL_DIR, device='cpu', compute_type='int8')
        else:
            _model = WhisperModel('small', device='cpu', compute_type='int8')
    return _model


def _to_simplified(text: str) -> str:
    """繁体转简体。"""
    global _cc
    if _cc is None:
        try:
            from opencc import OpenCC
            _cc = OpenCC('t2s')
        except Exception:
            _cc = False
    if _cc:
        return _cc.convert(text)
    return text


def transcribe(audio_bytes: bytes) -> str:
    """将音频字节转为简体中文文字。"""
    model = _get_model()
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name
    try:
        segments, _ = model.transcribe(
            tmp_path,
            language='zh',
            beam_size=1,
            vad_filter=True,
            initial_prompt='以下是普通话的简体中文内容。',
        )
        text = ''.join(seg.text for seg in segments).strip()
        return _to_simplified(text)
    finally:
        os.unlink(tmp_path)
