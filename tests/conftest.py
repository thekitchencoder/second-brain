import sqlite3

collect_ignore = []

try:
    import mcp
except ImportError:
    collect_ignore.append("test_mcp_transport.py")

try:
    conn = sqlite3.connect(":memory:")
    conn.enable_load_extension(True)
    conn.close()
except AttributeError:
    collect_ignore.append("test_brain_index.py")
    collect_ignore.append("lib/test_db.py")
