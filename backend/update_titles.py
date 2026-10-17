# 批量总结旧会话的标题（修复总结功能上线前的历史数据）
import sqlite3
import sys
from pathlib import Path

from ai_service import summarize_title

DB_PATH = Path(__file__).parent / 'star_dream.db'


def main():
    sys.stdout.reconfigure(errors='replace')
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute('SELECT id FROM conversations ORDER BY id').fetchall()
    conn.close()

    updated = 0
    for (cid,) in rows:
        conn = sqlite3.connect(DB_PATH)
        msgs = conn.execute(
            'SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id',
            (cid,),
        ).fetchall()
        conn.close()
        if not msgs:
            continue

        dialog = '\n'.join(
            ('用户：' if r[0] == 'user' else '助手：') + (r[1] or '')
            for r in msgs
        )
        try:
            title = summarize_title(dialog)
        except Exception as exc:  # noqa: BLE001
            print('会话 %d 总结失败: %s' % (cid, str(exc)[:60]))
            continue
        if title:
            conn = sqlite3.connect(DB_PATH)
            conn.execute('UPDATE conversations SET title=? WHERE id=?', (title, cid))
            conn.commit()
            conn.close()
            updated += 1
            print('会话 %d 标题更新为: %s' % (cid, title))

    print('\n完成，共更新 %d 个会话' % updated)


if __name__ == '__main__':
    main()
