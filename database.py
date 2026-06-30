"""
database.py — Khởi tạo schema SQLite và các thao tác với DB.

4 bảng:
  - employees         : sơ yếu lý lịch nhân viên
  - meetings          : danh sách cuộc họp
  - check_in          : check-in của cuộc họp HIỆN TẠI (bị reset khi tạo họp mới)
  - check_in_history  : lưu lại check-in của các cuộc họp trước
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
import config


def get_conn():
    conn = sqlite3.connect(config.SQLITE_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def conn_ctx():
    """
    Context manager cho kết nối SQLite: tự commit khi thoát bình thường,
    tự rollback khi có lỗi, và LUÔN đóng kết nối (tránh rò rỉ).
    Dùng: `with conn_ctx() as conn: conn.execute(...)`.
    """
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_db_initialized = False


def init_db(force=False):
    """Tạo toàn bộ bảng nếu chưa tồn tại. Chỉ chạy thực sự 1 lần mỗi tiến trình."""
    global _db_initialized
    if _db_initialized and not force:
        return
    with conn_ctx() as conn:
        _create_schema(conn.cursor())
    _db_initialized = True
    print("[database] Đã khởi tạo schema SQLite.")


def _create_schema(cur):
    # --- Nhân viên / cán bộ ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS employees (
        employee_id   TEXT PRIMARY KEY,      -- mã cán bộ, vd 'NV001'
        full_name     TEXT NOT NULL,
        department    TEXT,                  -- phòng ban
        position      TEXT,                  -- chức vụ
        email         TEXT,
        phone         TEXT,
        created_at    TEXT NOT NULL
    )""")

    # --- Cuộc họp ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS meetings (
        meeting_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        title         TEXT NOT NULL,
        started_at    TEXT NOT NULL,
        is_active     INTEGER NOT NULL DEFAULT 1   -- 1 = cuộc họp đang diễn ra
    )""")

    # --- Danh sách nhân viên được TRIỆU TẬP cho mỗi cuộc họp ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS meeting_invitees (
        meeting_id    INTEGER NOT NULL,
        employee_id   TEXT NOT NULL,
        PRIMARY KEY (meeting_id, employee_id),
        FOREIGN KEY (meeting_id)  REFERENCES meetings(meeting_id)  ON DELETE CASCADE,
        FOREIGN KEY (employee_id) REFERENCES employees(employee_id) ON DELETE CASCADE
    )""")

    # --- Check-in cuộc họp hiện tại ---
    # Khoá ghép (meeting_id, employee_id) -> mỗi người chỉ 1 row / cuộc họp,
    # INSERT OR IGNORE dùng ràng buộc này để chống trùng đúng theo từng cuộc họp.
    cur.execute("""
    CREATE TABLE IF NOT EXISTS check_in (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_id    INTEGER NOT NULL,
        employee_id   TEXT NOT NULL,
        full_name     TEXT,
        department    TEXT,
        position      TEXT,
        checkin_time  TEXT NOT NULL,
        UNIQUE (meeting_id, employee_id),
        FOREIGN KEY (meeting_id)  REFERENCES meetings(meeting_id)  ON DELETE CASCADE,
        FOREIGN KEY (employee_id) REFERENCES employees(employee_id) ON DELETE CASCADE
    )""")

    # --- Lịch sử check-in các cuộc họp trước ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS check_in_history (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_id    INTEGER NOT NULL,
        employee_id   TEXT NOT NULL,
        full_name     TEXT,
        department    TEXT,
        position      TEXT,
        checkin_time  TEXT NOT NULL,
        FOREIGN KEY (meeting_id) REFERENCES meetings(meeting_id) ON DELETE CASCADE
    )""")

    # --- Nhật ký nghi giả mạo (anti-spoofing) ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS spoof_log (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_id    INTEGER,
        employee_id   TEXT,                  -- người nhận diện được (có thể NULL)
        full_name     TEXT,
        level         TEXT NOT NULL,         -- 'suspect' | 'spoof'
        score         REAL,                  -- điểm 'thật' tổng hợp
        model_score   REAL,                  -- điểm từ MiniFASNet (nếu có)
        multiframe_static INTEGER,           -- 1 nếu đa frame nghi tĩnh
        mode          TEXT,                  -- chế độ anti-spoof khi ghi
        capture_path  TEXT,                  -- ảnh bằng chứng
        created_at    TEXT NOT NULL,
        FOREIGN KEY (meeting_id) REFERENCES meetings(meeting_id) ON DELETE CASCADE
    )""")


# ------------------------------------------------------------------
# Quản lý cuộc họp
# ------------------------------------------------------------------
def create_meeting(title, invitee_ids=None):
    """
    Tạo cuộc họp mới:
      1) Chuyển toàn bộ check_in hiện tại -> check_in_history
      2) Xóa sạch check_in
      3) Đánh dấu các cuộc họp cũ là không còn active
      4) Tạo bản ghi cuộc họp mới (active)
      5) Ghi danh sách triệu tập

    invitee_ids:
      - None hoặc []  -> TRIỆU TẬP TẤT CẢ nhân viên hiện có.
      - list mã NV    -> chỉ triệu tập những người này (ID không tồn tại sẽ bị bỏ).
    Trả về meeting_id mới.
    """
    with conn_ctx() as conn:
        cur = conn.cursor()

        # 1) Lưu lịch sử
        cur.execute("""
            INSERT INTO check_in_history
                (meeting_id, employee_id, full_name, department, position, checkin_time)
            SELECT meeting_id, employee_id, full_name, department, position, checkin_time
            FROM check_in
        """)
        moved = cur.rowcount

        # 2) Reset bảng check_in
        cur.execute("DELETE FROM check_in")

        # 3) Đóng các cuộc họp cũ
        cur.execute("UPDATE meetings SET is_active = 0 WHERE is_active = 1")

        # 4) Tạo cuộc họp mới
        now = datetime.now().isoformat(timespec="seconds")
        cur.execute(
            "INSERT INTO meetings (title, started_at, is_active) VALUES (?, ?, 1)",
            (title, now),
        )
        meeting_id = cur.lastrowid

        # 5) Danh sách triệu tập — chỉ giữ ID thật sự tồn tại trong employees.
        all_ids = {r["employee_id"]
                   for r in cur.execute("SELECT employee_id FROM employees").fetchall()}
        if not invitee_ids:                       # None hoặc rỗng -> tất cả
            valid_ids = sorted(all_ids)
        else:
            requested = [str(x).strip() for x in invitee_ids if str(x).strip()]
            valid_ids = [eid for eid in requested if eid in all_ids]
            missing = [eid for eid in requested if eid not in all_ids]
            if missing:
                print(f"[database] Bỏ qua {len(missing)} mã NV không tồn tại: "
                      f"{', '.join(missing)}")
        for eid in valid_ids:
            cur.execute(
                "INSERT OR IGNORE INTO meeting_invitees (meeting_id, employee_id) "
                "VALUES (?, ?)", (meeting_id, eid))

    print(f"[database] Tạo cuộc họp mới #{meeting_id} '{title}'. "
          f"Triệu tập {len(valid_ids)} người. "
          f"Đã chuyển {moved} bản ghi check-in cũ vào lịch sử.")
    return meeting_id


def get_invitees(meeting_id):
    """Danh sách mã NV được triệu tập cho cuộc họp."""
    with conn_ctx() as conn:
        rows = conn.execute(
            "SELECT employee_id FROM meeting_invitees WHERE meeting_id = ?",
            (meeting_id,)).fetchall()
    return {r["employee_id"] for r in rows}


def is_invited(meeting_id, employee_id):
    """Kiểm tra 1 người có thuộc diện triệu tập của cuộc họp không."""
    with conn_ctx() as conn:
        row = conn.execute(
            "SELECT 1 FROM meeting_invitees WHERE meeting_id = ? AND employee_id = ?",
            (meeting_id, employee_id)).fetchone()
    return row is not None


def get_active_meeting():
    """Lấy cuộc họp đang diễn ra. Trả về Row hoặc None."""
    with conn_ctx() as conn:
        row = conn.execute(
            "SELECT * FROM meetings WHERE is_active = 1 "
            "ORDER BY meeting_id DESC LIMIT 1").fetchone()
    return row


# ------------------------------------------------------------------
# Check-in
# ------------------------------------------------------------------
def is_checked_in(employee_id):
    """Kiểm tra nhân viên đã check-in trong cuộc họp hiện tại chưa."""
    with conn_ctx() as conn:
        row = conn.execute(
            "SELECT 1 FROM check_in WHERE employee_id = ?", (employee_id,)
        ).fetchone()
    return row is not None


def insert_check_in(meeting_id, employee_id):
    """
    Thử check-in 1 người vào cuộc họp.
    Quy tắc: chỉ check-in nếu người đó thuộc diện TRIỆU TẬP.

    Trả về một trong các trạng thái:
      'checked_in'  : vừa insert thành công
      'already'     : đã check-in trước đó
      'not_invited' : KHÔNG thuộc diện triệu tập -> không ghi (chỉ cảnh báo)
      'no_profile'  : không có hồ sơ trong employees
    """
    with conn_ctx() as conn:
        cur = conn.cursor()

        # Chặn người ngoài diện triệu tập
        invited = cur.execute(
            "SELECT 1 FROM meeting_invitees WHERE meeting_id = ? AND employee_id = ?",
            (meeting_id, employee_id)).fetchone()
        if invited is None:
            return "not_invited"

        emp = cur.execute(
            "SELECT full_name, department, position FROM employees "
            "WHERE employee_id = ?", (employee_id,)).fetchone()
        if emp is None:
            return "no_profile"

        now = datetime.now().isoformat(timespec="seconds")
        cur.execute("""
            INSERT OR IGNORE INTO check_in
                (meeting_id, employee_id, full_name, department, position, checkin_time)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (meeting_id, employee_id, emp["full_name"], emp["department"],
              emp["position"], now))
        return "checked_in" if cur.rowcount > 0 else "already"


# ------------------------------------------------------------------
# Nhật ký nghi giả mạo
# ------------------------------------------------------------------
def insert_spoof_log(meeting_id, employee_id, full_name, level, score,
                     model_score, multiframe_static, mode, capture_path=None):
    """Ghi 1 bản ghi nghi giả mạo."""
    now = datetime.now().isoformat(timespec="seconds")
    with conn_ctx() as conn:
        conn.execute("""
            INSERT INTO spoof_log
                (meeting_id, employee_id, full_name, level, score, model_score,
                 multiframe_static, mode, capture_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (meeting_id, employee_id, full_name, level, score, model_score,
              1 if multiframe_static else 0, mode, capture_path, now))


def get_spoof_log(meeting_id=None):
    """Lấy nhật ký nghi giả mạo (của 1 cuộc họp, hoặc tất cả nếu None)."""
    with conn_ctx() as conn:
        if meeting_id is None:
            rows = conn.execute(
                "SELECT * FROM spoof_log ORDER BY id DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM spoof_log WHERE meeting_id = ? ORDER BY id DESC",
                (meeting_id,)).fetchall()
    return rows


# ------------------------------------------------------------------
# Nhân viên
# ------------------------------------------------------------------
def upsert_employee(employee_id, full_name, department=None,
                    position=None, email=None, phone=None):
    """Thêm mới hoặc cập nhật thông tin nhân viên."""
    now = datetime.now().isoformat(timespec="seconds")
    with conn_ctx() as conn:
        conn.execute("""
            INSERT INTO employees
                (employee_id, full_name, department, position, email, phone, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(employee_id) DO UPDATE SET
                full_name=excluded.full_name,
                department=excluded.department,
                position=excluded.position,
                email=excluded.email,
                phone=excluded.phone
        """, (employee_id, full_name, department, position, email, phone, now))


if __name__ == "__main__":
    init_db()
