# Coze 配置项：优先读环境变量，其次读本地 .env 文件
import os
from pathlib import Path

# 读取本地 .env（不提交到仓库）
_env_path = Path(__file__).parent / '.env'
if _env_path.exists():
    for _line in _env_path.read_text(encoding='utf-8').splitlines():
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _k, _v = _line.split('=', 1)
            os.environ.setdefault(_k.strip(), _v.strip())

COZE_API_TOKEN = os.getenv('COZE_API_TOKEN', '')
COZE_API_BASE = os.getenv('COZE_API_BASE', 'https://api.coze.cn')
COZE_BOT_ID = os.getenv('COZE_BOT_ID', '')
