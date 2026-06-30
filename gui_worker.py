"""
gui_worker.py — Luồng nền (QThread) đọc camera + nhận diện, gửi kết quả về GUI.

Tách khỏi giao diện để GUI không bị treo khi xử lý video/AI.
Phát 2 tín hiệu:
  - frame_ready(QImage)              : khung hình đã vẽ annotation, để hiển thị
  - face_recognized(dict)            : 1 người vừa nhận diện được (cho list realtime)
  - status(str)                      : thông báo trạng thái
"""
import time
import os
import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage

import config
import database as db
import face_engine as fe
import antispoof as asp
import recognize as rec


class EnrollWorker(QThread):
    """
    Luồng nền chạy đăng ký hàng loạt (enroll.enroll_all) để KHÔNG treo GUI và
    báo tiến độ. Phát tín hiệu:
      - progress(done, total, message): tiến độ theo số ảnh đã xử lý
      - finished_ok(dict)             : tổng kết khi xong (hoặc hủy)
      - error(str)                    : lỗi nghiêm trọng (vd tải model thất bại)
    """
    progress    = pyqtSignal(int, int, str)
    finished_ok = pyqtSignal(dict)
    error       = pyqtSignal(str)

    def __init__(self, images_dir=None, replace=True):
        super().__init__()
        self.images_dir = images_dir
        self.replace = replace
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            import enroll
            def cb(done, total, msg):
                self.progress.emit(done, total, msg)
                return not self._cancel   # False -> enroll_all dừng giữa chừng
            summary = enroll.enroll_all(self.images_dir, self.replace,
                                        progress_cb=cb)
            self.finished_ok.emit(summary or {})
        except Exception as e:
            self.error.emit(str(e))


def bgr_to_qimage(frame_bgr):
    """Chuyển frame OpenCV (BGR) -> QImage (RGB) để hiển thị trong QLabel."""
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    return QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()


class CameraWorker(QThread):
    frame_ready     = pyqtSignal(QImage)
    face_recognized = pyqtSignal(dict)   # {employee_id, full_name, department, position, time, action, similarity}
    status          = pyqtSignal(str)
    error           = pyqtSignal(str)    # lỗi nghiêm trọng (vd tải model thất bại)

    def __init__(self, source, meeting_id, do_checkin=True, interval=None):
        """
        source: RTSP url (str) hoặc index webcam (int 0).
        do_checkin: True -> ghi check-in vào DB; False -> chỉ nhận diện (demo).
        interval: giãn cách giữa 2 lần CHẠY NHẬN DIỆN (giây). Video vẫn mượt giữa các lần.
                  None -> dùng config.CAMERA_PROCESS_INTERVAL.
        """
        super().__init__()
        self.source = source
        self.meeting_id = meeting_id
        self.do_checkin = do_checkin
        self.interval = (config.CAMERA_PROCESS_INTERVAL if interval is None
                         else interval)
        self._running = False
        # tránh phát trùng 1 người liên tục trong demo (id -> last emit time)
        self._last_emit = {}
        # cache thông tin nhân viên trong RAM, tránh query DB mỗi frame (N+1)
        self._emp_cache = {}
        # engine chống giả mạo (tự fail mềm nếu thiếu model)
        self.antispoof = asp.AntiSpoofEngine()

    def stop(self):
        self._running = False

    def run(self):
        cap = cv2.VideoCapture(self.source)
        if not cap.isOpened():
            self.error.emit(f"Không mở được nguồn camera: {self.source}\n"
                            f"Kiểm tra lại địa chỉ RTSP / quyền webcam.")
            return

        # Làm nóng model trong thread (tránh chặn GUI; bắt lỗi tải model).
        try:
            self.status.emit("Đang nạp model nhận diện...")
            fe.get_app()
        except Exception as e:
            cap.release()
            self.error.emit(str(e))
            return

        self._running = True
        self.status.emit("Đang chạy...")
        last_proc = 0.0
        cached = []          # kết quả nhận diện gần nhất để vẽ liên tục
        fail_count = 0       # đếm số lần đọc frame thất bại liên tiếp

        while self._running:
            ok, frame = cap.read()
            if not ok:
                fail_count += 1
                if fail_count >= config.CAMERA_FAIL_LIMIT:   # ~ mất kết nối kéo dài
                    self.error.emit("Mất kết nối camera (đọc frame thất bại "
                                    "nhiều lần). Đã dừng.")
                    break
                self.status.emit("Mất frame, thử lại...")
                time.sleep(0.3)
                continue
            fail_count = 0

            now = time.time()
            # Chỉ chạy AI mỗi `interval` giây (tiết kiệm CPU), nhưng vẫn vẽ + hiển thị mọi frame.
            if now - last_proc >= self.interval:
                last_proc = now
                try:
                    cached = self._process(frame, now)
                except Exception as e:
                    self.status.emit(f"Lỗi xử lý frame: {e}")
                    cached = []

            # Vẽ kết quả đã cache lên frame hiện tại. Bọc try/except để một lỗi
            # vẽ (vd: bbox lệch mép frame) không làm thoát luồng -> dừng chương trình.
            for c in cached:
                try:
                    fe.draw_annotation(frame, c["bbox"], c["label"], c["matched"])
                except Exception as e:
                    self.status.emit(f"Lỗi vẽ nhãn: {e}")

            self.frame_ready.emit(bgr_to_qimage(frame))
            time.sleep(config.FRAME_SLEEP_SEC)

        cap.release()
        self.antispoof.reset()
        self.status.emit("Đã dừng.")

    def _process(self, frame, now):
        """Chạy nhận diện 1 frame, xử lý anti-spoof + check-in/emit. Trả về list để vẽ.

        Lõi nhận diện dùng chung với CLI qua recognize.assess_face; phần GUI-riêng
        (vẽ, emit signal, lưu ảnh bằng chứng) xử lý tại đây.
        """
        faces = fe.detect_faces(frame)
        drawn = []
        for f in faces:
            a = rec.assess_face(f, frame, self.meeting_id, self.antispoof,
                                do_checkin=self.do_checkin, emp_cache=self._emp_cache)
            if a["status"] != "matched":
                drawn.append({"bbox": a["bbox"], "label": a["status"],
                              "matched": False})
                continue

            emp_id = a["employee_id"]
            emp = a["emp"]
            action = a["action"]
            entry = {"bbox": a["bbox"], "label": f"{emp_id} {emp['full_name']}",
                     "matched": True}

            if action.startswith("spoof_"):
                # Nghi giả mạo -> KHÔNG check-in, ghi log + chụp ảnh bằng chứng.
                sp = a["spoof"]
                entry["matched"] = False
                tag = "NGHI GIẢ" if sp["level"] == "suspect" else "GIẢ MẠO"
                entry["label"] = f"{emp_id} [!] {tag}"
                entry["spoof_level"] = sp["level"]
                drawn.append(entry)

                cap_path = self._save_capture(frame, a["bbox"], emp_id, now)
                db.insert_spoof_log(
                    self.meeting_id, emp_id, emp["full_name"], sp["level"],
                    sp["score"], sp["model_score"],
                    sp["multiframe_static"], sp["mode"], cap_path)

                self._maybe_emit(now, {
                    "employee_id": emp_id, "full_name": emp["full_name"],
                    "department": emp["department"] or "",
                    "position": emp["position"] or "",
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "action": action,                       # spoof_suspect / spoof_spoof
                    "similarity": a["similarity"],
                    "spoof_score": sp["score"],
                })
                continue

            # ---- Là người thật -> check-in / nhận diện ----
            drawn.append(entry)
            if action == "not_invited":
                entry["matched"] = False
                entry["label"] = f"{emp_id} (ngoài DS)"

            self._maybe_emit(now, {
                "employee_id": emp_id,
                "full_name":   emp["full_name"],
                "department":  emp["department"] or "",
                "position":    emp["position"] or "",
                "time":        time.strftime("%Y-%m-%d %H:%M:%S"),
                "action":      action,
                "similarity":  a["similarity"],
            })
        return drawn

    def _maybe_emit(self, now, payload):
        """Phát tín hiệu face_recognized nhưng giãn cách theo người để tránh spam UI."""
        emp_id = payload["employee_id"]
        if now - self._last_emit.get(emp_id, 0) >= config.FACE_EMIT_THROTTLE_SEC:
            self._last_emit[emp_id] = now
            self._prune_last_emit(now)
            self.face_recognized.emit(payload)

    def _prune_last_emit(self, now):
        """Dọn entry quá cũ để _last_emit không phình vô hạn khi chạy lâu."""
        if len(self._last_emit) > 256:
            ttl = config.FACE_EMIT_THROTTLE_SEC * 20
            self._last_emit = {k: t for k, t in self._last_emit.items()
                               if now - t < ttl}

    def _save_capture(self, frame, bbox, emp_id, now):
        """Lưu ảnh bằng chứng nghi giả mạo, trả về đường dẫn."""
        try:
            crop = asp.crop_face(frame, bbox, margin=0.3)
            if crop is None:
                return None
            ts = time.strftime(config.CSV_TIMESTAMP_FORMAT)
            fname = f"{emp_id}_{ts}_{int(now*1000)%1000}.jpg"
            path = os.path.join(config.SPOOF_CAPTURE_DIR, fname)
            cv2.imwrite(path, crop)
            return path
        except Exception:
            return None

    def _employee_info(self, emp_id):
        """Lấy thông tin nhân viên, có cache RAM (dùng chung helper với CLI)."""
        return rec.employee_info(emp_id, self._emp_cache)
