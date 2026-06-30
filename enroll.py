"""
enroll.py — Đăng ký nhân viên vào hệ thống (tạo dữ liệu ban đầu).

CÁCH TỔ CHỨC ẢNH:
  images/
    NV001/  a.jpg  b.jpg          (1-3 ảnh mỗi cán bộ)
    NV002/  x.png
    ...
  Tên thư mục = employee_id.

THÔNG TIN NHÂN VIÊN: file images/employees.csv
  employee_id,full_name,department,position,email,phone
  NV001,Nguyen Van A,Phong Ky Thuat,Truong phong,a@cty.vn,0900000001

Quy trình mỗi cán bộ:
  - đọc thông tin -> ghi vào SQLite (employees)
  - với mỗi ảnh: detect mặt rõ nhất -> sinh embedding -> lưu ChromaDB
"""
import os
import csv
import cv2

import config
import database as db
import face_engine as fe


def _largest_face(faces):
    """Chọn khuôn mặt lớn nhất trong ảnh (giả định ảnh đăng ký 1 người/ảnh)."""
    if not faces:
        return None
    return max(faces, key=lambda f: (f.bbox[2]-f.bbox[0])*(f.bbox[3]-f.bbox[1]))


def load_employee_info(csv_path):
    """Đọc file CSV thông tin nhân viên -> dict[employee_id] = {...}."""
    info = {}
    if not os.path.exists(csv_path):
        print(f"[enroll] CHÚ Ý: không thấy {csv_path}, chỉ enroll ảnh không có hồ sơ.")
        return info
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            info[row["employee_id"].strip()] = row
    return info


def enroll_all(images_dir=None, replace=True, progress_cb=None):
    """
    Duyệt toàn bộ thư mục ảnh và đăng ký.
    replace=True: xóa embedding cũ của mỗi người trước khi thêm (đăng ký lại sạch).

    progress_cb(done, total, message) -> bool|None:
        Gọi sau mỗi ảnh để báo tiến độ (done/total ảnh, kèm mô tả). Nếu callback
        trả về False -> hủy đăng ký giữa chừng. None/khác -> tiếp tục.

    Trả về dict tổng kết: {'employees', 'faces', 'skipped', 'cancelled'}.
    """
    images_dir = images_dir or config.IMAGES_DIR
    db.init_db()

    info = load_employee_info(os.path.join(images_dir, "employees.csv"))

    # Danh sách thư mục nhân viên + tổng số ảnh (để báo tiến độ).
    emp_dirs = [d for d in sorted(os.listdir(images_dir))
                if os.path.isdir(os.path.join(images_dir, d))]
    total_imgs = sum(len(os.listdir(os.path.join(images_dir, d))) for d in emp_dirs)

    def _report(done, msg):
        """Trả về True nếu nên tiếp tục, False nếu bị yêu cầu hủy."""
        if progress_cb is None:
            return True
        return progress_cb(done, total_imgs, msg) is not False

    total_emp, total_faces, skipped, done = 0, 0, 0, 0
    cancelled = False
    _report(0, "Bắt đầu...")

    for emp_id in emp_dirs:
        if cancelled:
            break
        emp_dir = os.path.join(images_dir, emp_id)

        # 1) Ghi thông tin nhân viên vào SQLite
        meta = info.get(emp_id, {})
        db.upsert_employee(
            employee_id = emp_id,
            full_name   = meta.get("full_name", emp_id),
            department  = meta.get("department"),
            position    = meta.get("position"),
            email       = meta.get("email"),
            phone       = meta.get("phone"),
        )

        # 2) Xử lý ảnh
        if replace:
            fe.delete_employee_faces(emp_id)

        idx = 0
        for fname in sorted(os.listdir(emp_dir)):
            done += 1
            if not _report(done, f"{emp_id}: {fname}"):
                cancelled = True
                break
            fpath = os.path.join(emp_dir, fname)
            img = cv2.imread(fpath)
            if img is None:
                continue
            faces = fe.detect_faces(img)
            face = _largest_face(faces)
            if face is None:
                print(f"  [!] {emp_id}/{fname}: không phát hiện khuôn mặt rõ -> bỏ.")
                skipped += 1
                continue
            fe.add_face(f"{emp_id}#{idx}", emp_id, face.normed_embedding)
            idx += 1
            total_faces += 1

        if idx > 0:
            total_emp += 1
            print(f"  [+] {emp_id} ({meta.get('full_name', emp_id)}): {idx} ảnh.")
        else:
            print(f"  [-] {emp_id}: KHÔNG có ảnh hợp lệ.")

    _report(done, "Đã hủy." if cancelled else "Hoàn tất.")
    print(f"\n[enroll] {'ĐÃ HỦY. ' if cancelled else 'Hoàn tất: '}"
          f"{total_emp} cán bộ, {total_faces} embedding, {skipped} ảnh bị bỏ.")
    return {"employees": total_emp, "faces": total_faces,
            "skipped": skipped, "cancelled": cancelled}


if __name__ == "__main__":
    enroll_all()
