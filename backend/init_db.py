# 数据库初始化脚本：创建数据表并导入知识库
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / 'star_dream.db'
KNOWLEDGE_PATH = Path(__file__).parent / 'knowledge_data.json'


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('PRAGMA foreign_keys = ON')

    cur.executescript('''
    CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        username    TEXT    NOT NULL UNIQUE,
        password    TEXT    NOT NULL,
        email       TEXT    NOT NULL UNIQUE,
        created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS conversations (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL,
        title       TEXT,
        status      TEXT    NOT NULL DEFAULT 'active',
        created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS messages (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id  INTEGER NOT NULL,
        role             TEXT    NOT NULL,
        content          TEXT    NOT NULL,
        created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS knowledge (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        category    TEXT    NOT NULL,
        question    TEXT    NOT NULL,
        answer      TEXT    NOT NULL,
        created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_conv_user_time ON conversations (user_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_msg_conv_time  ON messages (conversation_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_knowledge_cat  ON knowledge (category);
    ''')

    # 导入知识库
    if KNOWLEDGE_PATH.exists():
        data = json.loads(KNOWLEDGE_PATH.read_text(encoding='utf-8'))
        cur.executemany(
            'INSERT OR IGNORE INTO knowledge (category, question, answer) VALUES (?, ?, ?)',
            [(d['category'], d['question'], d['answer']) for d in data],
        )
        print('知识库导入', len(data), '条')

    conn.commit()
    conn.close()
    print('数据库初始化完成:', DB_PATH)


if __name__ == '__main__':
    init_db()
