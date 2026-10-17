# 数据库连接管理
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / 'star_dream.db'


def get_db():
    """获取数据库连接，开启外键约束，返回 Row 对象（可按列名取值）。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn
