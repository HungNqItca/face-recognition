"""
report.py — Báo cáo check-in của cuộc họp hiện tại.

Chức năng chính (theo yêu cầu): in ra các thành viên CHƯA check-in.
Bổ sung: danh sách đã check-in, xuất CSV.
"""
import os
import csv
from datetime import datetime

import config
import database as db


def get_absent():
    """
    Danh sách người ĐƯỢC TRIỆU TẬP nhưng CHƯA check-in (cuộc họp hiện tại).
    Chỉ xét trong meeting_invitees của cuộc họp đang active.
    """
    meeting = db.get_active_meeting()
    if meeting is None:
        return []
    with db.conn_ctx() as conn:
        rows = conn.execute("""
            SELECT e.employee_id, e.full_name, e.department, e.position
            FROM meeting_invitees mi
            JOIN employees e ON e.employee_id = mi.employee_id
            WHERE mi.meeting_id = ?
              AND e.employee_id NOT IN
                  (SELECT employee_id FROM check_in WHERE meeting_id = ?)
            ORDER BY e.department, e.full_name
        """, (meeting["meeting_id"], meeting["meeting_id"])).fetchall()
    return rows


def get_present():
    """Danh sách đã check-in của cuộc họp hiện tại."""
    meeting = db.get_active_meeting()
    if meeting is None:
        return []
    with db.conn_ctx() as conn:
        rows = conn.execute("""
            SELECT employee_id, full_name, department, position, checkin_time
            FROM check_in WHERE meeting_id = ? ORDER BY checkin_time
        """, (meeting["meeting_id"],)).fetchall()
    return rows


def print_report():
    """In báo cáo ra màn hình."""
    meeting = db.get_active_meeting()
    if meeting is None:
        print("Chưa có cuộc họp nào đang diễn ra. Hãy tạo cuộc họp trước.")
        return

    present = get_present()
    absent = get_absent()
    invited = db.get_invitees(meeting["meeting_id"])
    n_invited = len(invited)

    print("=" * 60)
    print(f"BÁO CÁO ĐIỂM DANH — Cuộc họp #{meeting['meeting_id']}: {meeting['title']}")
    print(f"Thời điểm: {datetime.now().isoformat(timespec='seconds')}")
    print(f"Triệu tập: {n_invited}  |  Đã check-in: {len(present)}  |  "
          f"Vắng: {len(absent)}")
    print("=" * 60)

    print(f"\n>>> ĐÃ CHECK-IN ({len(present)}):")
    if present:
        for r in present:
            print(f"   ✓ {r['employee_id']:8} {r['full_name']:<22} "
                  f"{r['department'] or '':<16} {r['checkin_time']}")
    else:
        print("   (chưa có ai)")

    print(f"\n>>> CHƯA CHECK-IN ({len(absent)}):")
    if absent:
        for r in absent:
            print(f"   ✗ {r['employee_id']:8} {r['full_name']:<22} "
                  f"{r['department'] or '':<16} {r['position'] or ''}")
    else:
        print("   (tất cả đã check-in)")
    print()


def export_absent_csv(path=None):
    """Xuất danh sách chưa check-in ra CSV."""
    meeting = db.get_active_meeting()
    mid = meeting["meeting_id"] if meeting else 0
    path = path or os.path.join(
        config.REPORTS_DIR,
        f"absent_meeting{mid}_"
        f"{datetime.now().strftime(config.CSV_TIMESTAMP_FORMAT)}.csv")
    rows = get_absent()
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["employee_id", "full_name", "department", "position"])
        for r in rows:
            w.writerow([r["employee_id"], r["full_name"],
                        r["department"], r["position"]])
    print(f"[report] Đã xuất {len(rows)} người chưa check-in -> {path}")
    return path


if __name__ == "__main__":
    print_report()
