"""Create the empty training archive. Existing databases are never overwritten."""
from pathlib import Path
import os
import sqlite3
import tempfile

ROOT = Path(__file__).resolve().parent

def main():
    target = ROOT.parent / "训练日志.sqlite3"
    if target.exists():
        raise SystemExit("数据库已存在，已保留原文件。")
    with tempfile.TemporaryDirectory(dir=target.parent) as folder:
        staged = Path(folder) / "empty.sqlite3"
        with sqlite3.connect(staged) as db:
            db.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        db.close()
        (target.parent / "backups").mkdir(exist_ok=True)
        os.link(staged, target)
    print("空数据库已创建。")

if __name__ == "__main__":
    main()
