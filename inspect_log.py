import sqlite3
import sys

db_path = sys.argv[1] if len(sys.argv) > 1 else "data/applications.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

print("\nAPPLICATIONS\n")
for row in conn.execute(
    "SELECT * FROM applications ORDER BY created_at DESC LIMIT 20"
):
    print(dict(row))

print("\nDECISIONS\n")
for row in conn.execute(
    "SELECT * FROM decisions ORDER BY id DESC LIMIT 100"
):
    print(dict(row))

conn.close()
