"""
gui.py — Giao diện PyQt6 cho hệ thống điểm danh khuôn mặt.

5 tab:
  1) Nhân viên      : danh sách, thêm/sửa, enroll ảnh
  2) Cuộc họp       : tạo cuộc họp mới (reset check-in, lưu lịch sử)
  3) Điểm danh      : camera RTSP/webcam -> nhận diện -> check-in tự động
  4) Demo Realtime  : camera + list người nhận diện (ID, Họ tên, Đơn vị, Time)
  5) Báo cáo        : đã / chưa check-in, xuất CSV

Chạy:  python gui.py
"""
import os
import sys
import cv2

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QTableWidget, QTableWidgetItem, QFileDialog,
    QMessageBox, QHeaderView, QComboBox, QFormLayout, QGroupBox, QSplitter,
    QAbstractItemView, QRadioButton, QButtonGroup, QCheckBox, QInputDialog,
    QProgressDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QPixmap, QImage

import config
import database as db
import face_engine as fe
import report as report_mod
from gui_worker import CameraWorker, EnrollWorker


# ===================================================================
# Tab 1 — Nhân viên
# ===================================================================
class EmployeeTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        # --- Form thêm/sửa ---
        form_box = QGroupBox("Thêm / Cập nhật nhân viên")
        form = QFormLayout()
        self.in_id = QLineEdit();    self.in_name = QLineEdit()
        self.in_dept = QLineEdit();  self.in_pos = QLineEdit()
        self.in_email = QLineEdit(); self.in_phone = QLineEdit()
        form.addRow("Mã NV *:", self.in_id)
        form.addRow("Họ tên *:", self.in_name)
        form.addRow("Phòng ban:", self.in_dept)
        form.addRow("Chức vụ:", self.in_pos)
        form.addRow("Email:", self.in_email)
        form.addRow("Điện thoại:", self.in_phone)
        btn_save = QPushButton("Lưu nhân viên")
        btn_save.clicked.connect(self.save_employee)
        form.addRow(btn_save)
        form_box.setLayout(form)

        # --- Enroll ---
        enroll_box = QGroupBox("Đăng ký khuôn mặt (sinh embedding)")
        ev = QVBoxLayout()
        info = QLabel("• Cách 1: Đăng ký 1 nhân viên — chọn 1–3 ảnh cho Mã NV ở form trên.\n"
                      "• Cách 2: Đăng ký hàng loạt — từ thư mục images/ (mỗi NV 1 thư mục con).")
        info.setWordWrap(True)
        h = QHBoxLayout()
        btn_enroll_one = QPushButton("Chọn ảnh & đăng ký NV này")
        btn_enroll_one.clicked.connect(self.enroll_one)
        btn_enroll_all = QPushButton("Đăng ký hàng loạt từ images/")
        btn_enroll_all.clicked.connect(self.enroll_all)
        h.addWidget(btn_enroll_one); h.addWidget(btn_enroll_all)
        ev.addWidget(info); ev.addLayout(h)
        enroll_box.setLayout(ev)

        top = QHBoxLayout()
        top.addWidget(form_box, 2); top.addWidget(enroll_box, 3)

        # --- Bảng danh sách ---
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Mã NV", "Họ tên", "Phòng ban", "Chức vụ", "Email", "Số ảnh"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.cellClicked.connect(self.fill_form_from_row)

        btn_refresh = QPushButton("Tải lại danh sách")
        btn_refresh.clicked.connect(self.refresh)

        layout.addLayout(top)
        layout.addWidget(QLabel("Danh sách nhân viên:"))
        layout.addWidget(self.table)
        layout.addWidget(btn_refresh)
        self.refresh()

    def save_employee(self):
        eid = self.in_id.text().strip()
        name = self.in_name.text().strip()
        if not eid or not name:
            QMessageBox.warning(self, "Thiếu dữ liệu", "Mã NV và Họ tên là bắt buộc.")
            return
        db.upsert_employee(eid, name, self.in_dept.text().strip(),
                           self.in_pos.text().strip(), self.in_email.text().strip(),
                           self.in_phone.text().strip())
        QMessageBox.information(self, "OK", f"Đã lưu nhân viên {eid}.")
        self.refresh()

    def enroll_one(self):
        eid = self.in_id.text().strip()
        if not eid:
            QMessageBox.warning(self, "Thiếu Mã NV", "Nhập Mã NV trước khi chọn ảnh.")
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, f"Chọn 1-3 ảnh cho {eid}", "",
            "Ảnh (*.jpg *.jpeg *.png *.bmp)")
        if not files:
            return
        self.save_employee()  # đảm bảo có hồ sơ
        fe.delete_employee_faces(eid)
        ok, fail = 0, 0
        for i, fp in enumerate(files[:3]):
            img = cv2.imread(fp)
            if img is None:
                fail += 1; continue
            faces = fe.detect_faces(img)
            if not faces:
                fail += 1; continue
            face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0])*(f.bbox[3]-f.bbox[1]))
            fe.add_face(f"{eid}#{i}", eid, face.normed_embedding)
            ok += 1
        QMessageBox.information(self, "Kết quả đăng ký",
                               f"{eid}: {ok} ảnh thành công, {fail} ảnh bỏ qua.")
        self.refresh()

    def enroll_all(self):
        # Chạy trong luồng nền + hộp thoại tiến độ để GUI không bị treo.
        if getattr(self, "_enroll_worker", None) is not None:
            return  # đang chạy
        worker = EnrollWorker()
        dlg = QProgressDialog("Đang chuẩn bị (lần đầu có thể tải model)...",
                              "Hủy", 0, 0, self)
        dlg.setWindowTitle("Đăng ký hàng loạt từ images/")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        self._enroll_worker = worker
        self._enroll_dlg = dlg

        def on_progress(done, total, msg):
            if total > 0:
                dlg.setMaximum(total)
                dlg.setValue(done)
            dlg.setLabelText(f"({done}/{total}) {msg}")

        def cleanup():
            dlg.close()
            self._enroll_worker = None
            self._enroll_dlg = None

        def on_done(summary):
            cleanup()
            self.refresh()
            if summary.get("cancelled"):
                QMessageBox.warning(self, "Đã hủy",
                    "Đăng ký hàng loạt đã bị hủy.\n"
                    f"Đã xử lý: {summary.get('employees', 0)} nhân viên, "
                    f"{summary.get('faces', 0)} embedding.")
            else:
                QMessageBox.information(self, "Hoàn tất",
                    "Đã đăng ký hàng loạt từ images/.\n"
                    f"Nhân viên: {summary.get('employees', 0)}  |  "
                    f"Embedding: {summary.get('faces', 0)}  |  "
                    f"Ảnh bị bỏ: {summary.get('skipped', 0)}")

        def on_error(msg):
            cleanup()
            self.refresh()
            QMessageBox.critical(self, "Lỗi", msg)

        worker.progress.connect(on_progress)
        worker.finished_ok.connect(on_done)
        worker.error.connect(on_error)
        dlg.canceled.connect(worker.cancel)
        worker.start()
        dlg.show()

    def fill_form_from_row(self, row, _col):
        self.in_id.setText(self.table.item(row, 0).text())
        self.in_name.setText(self.table.item(row, 1).text())
        self.in_dept.setText(self.table.item(row, 2).text())
        self.in_pos.setText(self.table.item(row, 3).text())
        self.in_email.setText(self.table.item(row, 4).text())

    def refresh(self):
        db.init_db()
        with db.conn_ctx() as conn:
            rows = conn.execute(
                "SELECT employee_id, full_name, department, position, email "
                "FROM employees ORDER BY employee_id").fetchall()
        # đếm số ảnh trong ChromaDB
        col = fe.get_collection()
        layout_counts = {}
        try:
            got = col.get()
            for md in got["metadatas"]:
                eid = md["employee_id"]
                layout_counts[eid] = layout_counts.get(eid, 0) + 1
        except Exception as e:
            print(f"[gui] Không đếm được embedding trong ChromaDB: {e}")

        self.table.setRowCount(0)
        for r in rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            vals = [r["employee_id"], r["full_name"], r["department"] or "",
                    r["position"] or "", r["email"] or "",
                    str(layout_counts.get(r["employee_id"], 0))]
            for c, v in enumerate(vals):
                self.table.setItem(i, c, QTableWidgetItem(v))


# ===================================================================
# Tab 2 — Cuộc họp
# ===================================================================
class MeetingTab(QWidget):
    meeting_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        box = QGroupBox("Tạo cuộc họp mới")
        v = QVBoxLayout()
        warn = QLabel("⚠ Tạo cuộc họp mới sẽ CHUYỂN check-in hiện tại vào lịch sử "
                      "và RESET bảng check-in.")
        warn.setWordWrap(True)
        warn.setStyleSheet("color:#b35900;")
        h = QHBoxLayout()
        self.in_title = QLineEdit()
        self.in_title.setPlaceholderText("Tên cuộc họp, vd: Họp giao ban tháng 6")
        h.addWidget(QLabel("Tên:")); h.addWidget(self.in_title)
        v.addWidget(warn); v.addLayout(h)

        # --- Chọn diện triệu tập ---
        mode_box = QGroupBox("Thành phần triệu tập")
        mv = QVBoxLayout()
        self.rb_all = QRadioButton("Triệu tập TẤT CẢ nhân viên")
        self.rb_some = QRadioButton("Chỉ triệu tập nhóm được chọn bên dưới")
        self.rb_all.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.rb_all); grp.addButton(self.rb_some)
        self.rb_all.toggled.connect(self._toggle_select)

        # thanh công cụ chọn nhanh + lọc
        tools = QHBoxLayout()
        self.in_filter = QLineEdit()
        self.in_filter.setPlaceholderText("Lọc theo tên / mã / phòng ban...")
        self.in_filter.textChanged.connect(self._apply_filter)
        btn_all = QPushButton("Chọn tất cả (đang hiện)")
        btn_none = QPushButton("Bỏ chọn tất cả")
        btn_dept = QPushButton("Chọn theo phòng ban...")
        btn_all.clicked.connect(lambda: self._set_all_visible(True))
        btn_none.clicked.connect(lambda: self._set_all_visible(False))
        btn_dept.clicked.connect(self._select_by_dept)
        tools.addWidget(self.in_filter, 1)
        tools.addWidget(btn_all); tools.addWidget(btn_none); tools.addWidget(btn_dept)

        # bảng nhân viên có checkbox
        self.emp_table = QTableWidget(0, 4)
        self.emp_table.setHorizontalHeaderLabels(["Chọn", "Mã NV", "Họ tên", "Phòng ban"])
        self.emp_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.emp_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.emp_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        self.lbl_count = QLabel("Đã chọn: 0")
        mv.addWidget(self.rb_all); mv.addWidget(self.rb_some)
        mv.addLayout(tools)
        mv.addWidget(self.emp_table)
        mv.addWidget(self.lbl_count)
        mode_box.setLayout(mv)

        btn = QPushButton("Tạo cuộc họp")
        btn.clicked.connect(self.create_meeting)

        v.addWidget(mode_box)
        v.addWidget(btn)
        box.setLayout(v)

        self.lbl_active = QLabel()
        self.lbl_active.setStyleSheet("font-weight:bold; padding:8px;")

        # Lịch sử cuộc họp
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Mã họp", "Tên cuộc họp", "Bắt đầu", "Triệu tập", "Trạng thái"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        layout.addWidget(box)
        layout.addWidget(self.lbl_active)
        layout.addWidget(QLabel("Lịch sử cuộc họp:"))
        layout.addWidget(self.table)
        self.refresh()
        self._toggle_select()

    # ---- thao tác chọn ----
    def _toggle_select(self):
        enabled = self.rb_some.isChecked()
        self.emp_table.setEnabled(enabled)
        self.in_filter.setEnabled(enabled)

    def _checkbox_at(self, row):
        w = self.emp_table.cellWidget(row, 0)
        return w.findChild(QCheckBox) if w else None

    def _set_all_visible(self, checked):
        for r in range(self.emp_table.rowCount()):
            if not self.emp_table.isRowHidden(r):
                cb = self._checkbox_at(r)
                if cb:
                    cb.setChecked(checked)
        self._update_count()

    def _apply_filter(self, text):
        text = text.lower().strip()
        for r in range(self.emp_table.rowCount()):
            hay = " ".join(self.emp_table.item(r, c).text().lower()
                           for c in (1, 2, 3))
            self.emp_table.setRowHidden(r, text not in hay)

    def _select_by_dept(self):
        depts = sorted({self.emp_table.item(r, 3).text()
                        for r in range(self.emp_table.rowCount())
                        if self.emp_table.item(r, 3).text()})
        if not depts:
            return
        dept, ok = QInputDialog.getItem(
            self, "Chọn phòng ban", "Phòng ban:", depts, 0, False)
        if ok and dept:
            for r in range(self.emp_table.rowCount()):
                if self.emp_table.item(r, 3).text() == dept:
                    cb = self._checkbox_at(r)
                    if cb:
                        cb.setChecked(True)
            self._update_count()

    def _update_count(self):
        n = sum(1 for r in range(self.emp_table.rowCount())
                if (cb := self._checkbox_at(r)) and cb.isChecked())
        self.lbl_count.setText(f"Đã chọn: {n}")

    def _selected_ids(self):
        ids = []
        for r in range(self.emp_table.rowCount()):
            cb = self._checkbox_at(r)
            if cb and cb.isChecked():
                ids.append(self.emp_table.item(r, 1).text())
        return ids

    def create_meeting(self):
        title = self.in_title.text().strip()
        if not title:
            QMessageBox.warning(self, "Thiếu tên", "Nhập tên cuộc họp.")
            return
        if self.rb_all.isChecked():
            invitee_ids = None  # tất cả
        else:
            invitee_ids = self._selected_ids()
            if not invitee_ids:
                QMessageBox.warning(self, "Chưa chọn ai",
                                    "Hãy chọn ít nhất 1 nhân viên triệu tập, "
                                    "hoặc chọn 'Triệu tập tất cả'.")
                return
        mid = db.create_meeting(title, invitee_ids=invitee_ids)
        n = len(db.get_invitees(mid))
        self.in_title.clear()
        QMessageBox.information(self, "OK",
                               f"Đã tạo cuộc họp #{mid}: {title}\nTriệu tập {n} người.")
        self.refresh()
        self.meeting_changed.emit()

    def _load_employees(self):
        """Nạp danh sách nhân viên vào bảng chọn (kèm checkbox)."""
        with db.conn_ctx() as conn:
            rows = conn.execute(
                "SELECT employee_id, full_name, department FROM employees "
                "ORDER BY department, full_name").fetchall()
        self.emp_table.setRowCount(0)
        for r in rows:
            i = self.emp_table.rowCount()
            self.emp_table.insertRow(i)
            # checkbox căn giữa
            cell = QWidget(); lay = QHBoxLayout(cell)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb = QCheckBox(); cb.stateChanged.connect(self._update_count)
            lay.addWidget(cb)
            self.emp_table.setCellWidget(i, 0, cell)
            self.emp_table.setItem(i, 1, QTableWidgetItem(r["employee_id"]))
            self.emp_table.setItem(i, 2, QTableWidgetItem(r["full_name"]))
            self.emp_table.setItem(i, 3, QTableWidgetItem(r["department"] or ""))
        self._update_count()

    def refresh(self):
        db.init_db()
        self._load_employees()
        m = db.get_active_meeting()
        if m:
            n = len(db.get_invitees(m["meeting_id"]))
            self.lbl_active.setText(
                f"Cuộc họp hiện tại: #{m['meeting_id']} — {m['title']} "
                f"(triệu tập {n} người, bắt đầu {m['started_at']})")
            self.lbl_active.setStyleSheet(
                "font-weight:bold; padding:8px; background:#e6ffe6;")
        else:
            self.lbl_active.setText("Chưa có cuộc họp đang diễn ra.")
            self.lbl_active.setStyleSheet(
                "font-weight:bold; padding:8px; background:#ffe6e6;")

        with db.conn_ctx() as conn:
            rows = conn.execute("""
                SELECT m.meeting_id, m.title, m.started_at, m.is_active,
                       (SELECT COUNT(*) FROM meeting_invitees mi
                        WHERE mi.meeting_id = m.meeting_id) AS n_inv
                FROM meetings m ORDER BY m.meeting_id DESC""").fetchall()
        self.table.setRowCount(0)
        for r in rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            vals = [str(r["meeting_id"]), r["title"], r["started_at"],
                    str(r["n_inv"]),
                    "ĐANG HỌP" if r["is_active"] else "đã đóng"]
            for c, val in enumerate(vals):
                self.table.setItem(i, c, QTableWidgetItem(val))


# ===================================================================
# Tab video dùng chung (cơ sở cho Điểm danh & Demo)
# ===================================================================
class BaseVideoTab(QWidget):
    """Khung video + điều khiển nguồn camera. Lớp con quyết định do_checkin và xử lý kết quả."""
    do_checkin = True

    def __init__(self):
        super().__init__()
        self.worker = None
        self.main_layout = QVBoxLayout(self)

        # Hàng điều khiển nguồn
        ctrl = QHBoxLayout()
        self.in_source = QLineEdit()
        self.in_source.setPlaceholderText(
            "rtsp://user:pass@192.168.1.10:554/stream1  (hoặc gõ 0 cho webcam)")
        self.btn_start = QPushButton("Bắt đầu")
        self.btn_stop = QPushButton("Dừng")
        self.btn_stop.setEnabled(False)
        self.btn_start.clicked.connect(self.start)
        self.btn_stop.clicked.connect(self.stop)
        ctrl.addWidget(QLabel("Nguồn:"))
        ctrl.addWidget(self.in_source, 1)
        ctrl.addWidget(self.btn_start)
        ctrl.addWidget(self.btn_stop)
        self.main_layout.addLayout(ctrl)

        # Khung hiển thị video
        self.video = QLabel("Chưa kết nối camera")
        self.video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video.setMinimumSize(640, 400)
        self.video.setStyleSheet("background:#222; color:#aaa; border:1px solid #444;")

        self.lbl_status = QLabel("Sẵn sàng.")
        self.lbl_status.setStyleSheet("color:#555;")

    def _resolve_source(self):
        s = self.in_source.text().strip()
        if s == "" :
            return 0
        return int(s) if s.isdigit() else s

    def start(self):
        m = db.get_active_meeting()
        if self.do_checkin and m is None:
            QMessageBox.warning(self, "Chưa có cuộc họp",
                                "Hãy tạo cuộc họp ở tab 'Cuộc họp' trước.")
            return
        meeting_id = m["meeting_id"] if m else 0
        # đảm bảo có dữ liệu khuôn mặt
        try:
            if fe.get_collection().count() == 0:
                QMessageBox.warning(self, "Chưa có dữ liệu khuôn mặt",
                                    "Hãy đăng ký nhân viên (tab Nhân viên) trước.")
                return
        except Exception as e:
            QMessageBox.critical(self, "Lỗi cơ sở dữ liệu khuôn mặt", str(e))
            return
        source = self._resolve_source()
        self.lbl_status.setText("Đang khởi động (lần đầu có thể tải model)...")
        self.worker = CameraWorker(source, meeting_id,
                                   do_checkin=self.do_checkin,
                                   interval=config.CAMERA_PROCESS_INTERVAL)
        self.worker.frame_ready.connect(self.on_frame)
        self.worker.face_recognized.connect(self.on_face)
        self.worker.status.connect(self.lbl_status.setText)
        self.worker.error.connect(self._on_worker_error)
        self.worker.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

    def _on_worker_error(self, msg):
        """Nhận lỗi từ worker (vd tải model thất bại) và hiện thông báo."""
        QMessageBox.critical(self, "Lỗi", msg)
        self.stop()

    def stop(self):
        if self.worker:
            self.worker.stop()
            if not self.worker.wait(5000):   # chờ tối đa 5s (model có thể đang tải)
                self.worker.terminate()      # cưỡng chế nếu vẫn kẹt
                self.worker.wait()
            self.worker = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.video.setText("Đã dừng.")

    def on_frame(self, qimg):
        pix = QPixmap.fromImage(qimg).scaled(
            self.video.width(), self.video.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.video.setPixmap(pix)

    def on_face(self, data):
        """Lớp con override để xử lý người nhận diện được."""
        pass

    def closeEvent(self, e):
        self.stop()
        super().closeEvent(e)


# ===================================================================
# Tab 3 — Điểm danh (check-in tự động)
# ===================================================================
class CheckinTab(BaseVideoTab):
    do_checkin = True

    def __init__(self, get_report_cb=None):
        super().__init__()
        self.get_report_cb = get_report_cb

        self.main_layout.addWidget(self.video, 1)
        self.main_layout.addWidget(self.lbl_status)

        # Bảng log check-in
        self.log = QTableWidget(0, 5)
        self.log.setHorizontalHeaderLabels(
            ["Mã NV", "Họ tên", "Đơn vị", "Thời gian", "Trạng thái"])
        self.log.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.log.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.main_layout.addWidget(QLabel("Nhật ký check-in:"))
        self.main_layout.addWidget(self.log)

    def on_face(self, d):
        action_text = {"checked_in": "✓ Check-in mới",
                       "already": "• Đã check-in",
                       "not_invited": "⚠ Ngoài DS triệu tập",
                       "no_profile": "? Chưa có hồ sơ",
                       "spoof_suspect": "⚠ Nghi ảnh giả",
                       "spoof_spoof": "⛔ Phát hiện ảnh giả",
                       "recognized": "nhận diện"}.get(d["action"], d["action"])
        i = 0
        self.log.insertRow(i)
        vals = [d["employee_id"], d["full_name"], d["department"],
                d["time"], action_text]
        for c, v in enumerate(vals):
            item = QTableWidgetItem(v)
            if d["action"] == "checked_in":
                item.setBackground(Qt.GlobalColor.green)
            elif d["action"] == "not_invited":
                item.setBackground(Qt.GlobalColor.yellow)
            elif d["action"] == "spoof_suspect":
                item.setBackground(Qt.GlobalColor.yellow)
            elif d["action"] == "spoof_spoof":
                item.setBackground(Qt.GlobalColor.red)
            self.log.setItem(i, c, item)


# ===================================================================
# Tab 4 — Demo Realtime (list người nhận diện)
# ===================================================================
class DemoTab(BaseVideoTab):
    do_checkin = False   # demo: chỉ nhận diện, không bắt buộc check-in

    def __init__(self):
        super().__init__()

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget(); lv = QVBoxLayout(left)
        lv.addWidget(self.video, 1)
        lv.addWidget(self.lbl_status)
        splitter.addWidget(left)

        right = QWidget(); rv = QVBoxLayout(right)
        rv.addWidget(QLabel("Người nhận diện được (realtime):"))
        self.list = QTableWidget(0, 4)
        self.list.setHorizontalHeaderLabels(["ID", "Họ tên", "Đơn vị công tác", "Time"])
        self.list.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        btn_clear = QPushButton("Xóa danh sách")
        btn_clear.clicked.connect(self.clear_list)
        rv.addWidget(self.list, 1)
        rv.addWidget(btn_clear)
        splitter.addWidget(right)
        splitter.setSizes([640, 480])

        self.main_layout.addWidget(splitter, 1)
        # đã có sẵn các nút start/stop ở trên; thêm ghi chú
        note = QLabel("Demo nhận diện realtime — mỗi người hiển thị 1 dòng (làm mới sau 5s).")
        note.setStyleSheet("color:#777;")
        self.main_layout.addWidget(note)
        self._seen = set()

    def on_face(self, d):
        # Mỗi người 1 dòng; nếu đã có thì cập nhật thời gian
        is_outsider = d.get("action") == "not_invited"
        is_spoof = d.get("action", "").startswith("spoof_")
        if d["employee_id"] in self._seen:
            for r in range(self.list.rowCount()):
                if self.list.item(r, 0).text() == d["employee_id"]:
                    self.list.item(r, 3).setText(d["time"])
                    return
        self._seen.add(d["employee_id"])
        i = self.list.rowCount()
        self.list.insertRow(i)
        suffix = ""
        if is_outsider:
            suffix = " ⚠ ngoài DS"
        elif d.get("action") == "spoof_suspect":
            suffix = " ⚠ nghi ảnh giả"
        elif d.get("action") == "spoof_spoof":
            suffix = " ⛔ ảnh giả"
        name = d["full_name"] + suffix
        vals = [d["employee_id"], name, d["department"], d["time"]]
        for c, v in enumerate(vals):
            item = QTableWidgetItem(v)
            if is_spoof:
                item.setBackground(Qt.GlobalColor.red if d["action"] == "spoof_spoof"
                                   else Qt.GlobalColor.yellow)
            elif is_outsider:
                item.setBackground(Qt.GlobalColor.yellow)
            self.list.setItem(i, c, item)

    def clear_list(self):
        """Xóa bảng + reset tập đã thấy để người cũ có thể hiện lại sau khi xóa."""
        self.list.setRowCount(0)
        self._seen.clear()

    def stop(self):
        super().stop()
        self._seen.clear()


# ===================================================================
# Tab 5 — Báo cáo
# ===================================================================
class ReportTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        self.lbl_summary = QLabel("—")
        self.lbl_summary.setStyleSheet("font-weight:bold; padding:6px;")

        h = QHBoxLayout()
        btn_refresh = QPushButton("Tải lại báo cáo")
        btn_refresh.clicked.connect(self.refresh)
        btn_export = QPushButton("Xuất CSV người vắng")
        btn_export.clicked.connect(self.export_csv)
        h.addWidget(btn_refresh); h.addWidget(btn_export); h.addStretch()

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Đã check-in
        w1 = QWidget(); v1 = QVBoxLayout(w1)
        v1.addWidget(QLabel("✓ Đã check-in:"))
        self.tbl_present = QTableWidget(0, 4)
        self.tbl_present.setHorizontalHeaderLabels(
            ["Mã NV", "Họ tên", "Đơn vị", "Thời gian"])
        self.tbl_present.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        v1.addWidget(self.tbl_present)
        splitter.addWidget(w1)

        # Chưa check-in
        w2 = QWidget(); v2 = QVBoxLayout(w2)
        v2.addWidget(QLabel("✗ Chưa check-in:"))
        self.tbl_absent = QTableWidget(0, 4)
        self.tbl_absent.setHorizontalHeaderLabels(
            ["Mã NV", "Họ tên", "Đơn vị", "Chức vụ"])
        self.tbl_absent.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        v2.addWidget(self.tbl_absent)
        splitter.addWidget(w2)

        layout.addWidget(self.lbl_summary)
        layout.addLayout(h)
        layout.addWidget(splitter, 1)

        # --- Nhật ký nghi giả mạo ---
        self.lbl_spoof = QLabel("⚠ Nhật ký nghi giả mạo (anti-spoofing):")
        self.lbl_spoof.setStyleSheet("font-weight:bold; color:#b30000;")
        self.tbl_spoof = QTableWidget(0, 7)
        self.tbl_spoof.setHorizontalHeaderLabels(
            ["Mã NV", "Họ tên", "Mức độ", "Điểm", "Model", "Chế độ", "Thời gian"])
        self.tbl_spoof.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.tbl_spoof.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_spoof.setMaximumHeight(180)
        layout.addWidget(self.lbl_spoof)
        layout.addWidget(self.tbl_spoof)
        self.refresh()

    def refresh(self):
        db.init_db()
        m = db.get_active_meeting()
        present = report_mod.get_present()
        absent = report_mod.get_absent()
        n_invited = len(db.get_invitees(m["meeting_id"])) if m else 0

        title = f"#{m['meeting_id']} {m['title']}" if m else "(chưa có cuộc họp)"
        self.lbl_summary.setText(
            f"Cuộc họp {title}  |  Triệu tập: {n_invited}  |  "
            f"Đã check-in: {len(present)}  |  Vắng: {len(absent)}")

        self._fill(self.tbl_present, present,
                   ["employee_id", "full_name", "department", "checkin_time"])
        self._fill(self.tbl_absent, absent,
                   ["employee_id", "full_name", "department", "position"])

        # nhật ký giả mạo của cuộc họp hiện tại
        mid = m["meeting_id"] if m else None
        spoofs = db.get_spoof_log(mid)
        self.lbl_spoof.setText(
            f"⚠ Nhật ký nghi giả mạo (anti-spoofing): {len(spoofs)} bản ghi")
        self.tbl_spoof.setRowCount(0)
        for s in spoofs:
            i = self.tbl_spoof.rowCount()
            self.tbl_spoof.insertRow(i)
            level_txt = {"suspect": "Nghi ngờ", "spoof": "Giả mạo"}.get(
                s["level"], s["level"])
            vals = [s["employee_id"] or "", s["full_name"] or "", level_txt,
                    str(s["score"]),
                    "" if s["model_score"] is None else str(s["model_score"]),
                    s["mode"] or "", s["created_at"]]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setBackground(Qt.GlobalColor.red if s["level"] == "spoof"
                                   else Qt.GlobalColor.yellow)
                self.tbl_spoof.setItem(i, c, item)

    @staticmethod
    def _fill(table, rows, keys):
        table.setRowCount(0)
        for r in rows:
            i = table.rowCount()
            table.insertRow(i)
            for c, k in enumerate(keys):
                table.setItem(i, c, QTableWidgetItem(str(r[k] or "")))

    def export_csv(self):
        path = report_mod.export_absent_csv()
        QMessageBox.information(self, "Đã xuất", f"File CSV:\n{path}")


# ===================================================================
# Cửa sổ chính
# ===================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hệ thống điểm danh khuôn mặt — PyQt6")
        self.resize(1100, 760)

        db.init_db()
        tabs = QTabWidget()

        self.emp_tab = EmployeeTab()
        self.meeting_tab = MeetingTab()
        self.checkin_tab = CheckinTab()
        self.demo_tab = DemoTab()
        self.report_tab = ReportTab()

        tabs.addTab(self.emp_tab, "1. Nhân viên")
        tabs.addTab(self.meeting_tab, "2. Cuộc họp")
        tabs.addTab(self.checkin_tab, "3. Điểm danh (Camera)")
        tabs.addTab(self.demo_tab, "4. Demo Realtime")
        tabs.addTab(self.report_tab, "5. Báo cáo")

        # cập nhật chéo khi đổi cuộc họp / chuyển tab
        self.meeting_tab.meeting_changed.connect(self.report_tab.refresh)
        tabs.currentChanged.connect(self._on_tab_change)
        self.tabs = tabs
        self.setCentralWidget(tabs)

    def _on_tab_change(self, idx):
        w = self.tabs.widget(idx)
        if hasattr(w, "refresh"):
            w.refresh()

    def closeEvent(self, e):
        # dừng mọi worker camera đang chạy
        self.checkin_tab.stop()
        self.demo_tab.stop()
        # dừng worker đăng ký hàng loạt nếu đang chạy
        w = getattr(self.emp_tab, "_enroll_worker", None)
        if w is not None:
            w.cancel()
            w.wait(5000)
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
