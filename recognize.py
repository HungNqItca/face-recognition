"""
recognize.py — Nhận diện khuôn mặt trong frame và check-in.

Hai chế độ:
  - process_frame(img): xử lý 1 ảnh numpy (BGR), trả về kết quả từng mặt + check-in.
  - run_camera(rtsp_url): đọc camera IP qua RTSP, xử lý liên tục.

Đáp ứng yêu cầu:
  - Đếm số khuôn mặt trong khung hình.
  - Với mỗi mặt: xác định là ai; nếu chưa check-in thì insert, đã có thì bỏ qua.
"""
import time
import cv2

import config
import database as db
import face_engine as fe
import antispoof as asp

# Engine anti-spoof dùng chung cho CLI (tạo 1 lần).
_asp_engine = None
# Cache hồ sơ nhân viên ở RAM cho CLI -> tránh query DB mỗi mặt mỗi frame (N+1).
_emp_cache = {}


def _get_asp():
    global _asp_engine
    if _asp_engine is None:
        _asp_engine = asp.AntiSpoofEngine()
    return _asp_engine


def employee_info(emp_id, cache=None):
    """
    Lấy hồ sơ nhân viên (full_name/department/position) có cache RAM.
    cache=None -> dùng cache cấp module (_emp_cache); truyền dict riêng để worker
    GUI tự quản vòng đời cache của mình.
    """
    cache = _emp_cache if cache is None else cache
    if emp_id in cache:
        return cache[emp_id]
    with db.conn_ctx() as conn:
        row = conn.execute(
            "SELECT full_name, department, position FROM employees "
            "WHERE employee_id = ?", (emp_id,)).fetchone()
    info = dict(row) if row else {"full_name": emp_id, "department": "",
                                  "position": ""}
    cache[emp_id] = info
    return info


def assess_face(face, frame, meeting_id, antispoof_engine,
                do_checkin=True, emp_cache=None):
    """
    LÕI xử lý 1 khuôn mặt — DÙNG CHUNG cho CLI (process_frame) và GUI
    (CameraWorker._process): identify -> (nếu matched) lấy hồ sơ + anti-spoof ->
    quyết định action. KHÔNG vẽ, KHÔNG emit, KHÔNG lưu ảnh bằng chứng, KHÔNG ghi
    spoof_log (caller tự làm vì khác nhau giữa CLI và GUI).

    Trả về dict: {bbox, status, employee_id, similarity, emp, spoof, action}
      action khi matched + real : 'checked_in'|'already'|'not_invited'|'no_profile'
                                  (nếu do_checkin) hoặc 'recognized'
      action khi matched + giả  : 'spoof_suspect'|'spoof_spoof'
      action khác matched       : 'skip'
    """
    info = fe.identify(face.normed_embedding)
    out = {
        "bbox": [int(v) for v in face.bbox],
        "status": info["status"],
        "employee_id": info["employee_id"],
        "similarity": round(info["similarity"], 3),
        "emp": None,
        "spoof": None,
        "action": "skip",
    }
    if info["status"] != "matched":
        return out

    emp_id = info["employee_id"]
    out["emp"] = employee_info(emp_id, emp_cache)

    spoof = {"level": "real", "score": 1.0, "model_score": None,
             "multiframe_static": False, "mode": "disabled"}
    if antispoof_engine.enabled:
        crop = asp.crop_face(frame, out["bbox"])
        spoof = antispoof_engine.assess(crop, emp_id, face.normed_embedding)
    out["spoof"] = spoof

    if spoof["level"] != "real":
        out["action"] = "spoof_" + spoof["level"]
    elif do_checkin:
        out["action"] = db.insert_check_in(meeting_id, emp_id)
    else:
        out["action"] = "recognized"
    return out


def process_frame(image_bgr, meeting_id, verbose=True):
    """
    Xử lý 1 frame. Trả về dict thống kê:
      {
        'num_faces': int,                 # tổng số mặt phát hiện
        'results': [ {bbox, status, employee_id, full_name, similarity, action} ],
      }
    action: 'checked_in' (vừa insert) | 'already' (đã có) | 'skip' (unknown/uncertain)
    """
    faces = fe.detect_faces(image_bgr)
    eng = _get_asp()
    results = []

    for f in faces:
        a = assess_face(f, image_bgr, meeting_id, eng, do_checkin=True)
        item = {
            "bbox": a["bbox"],
            "status": a["status"],
            "similarity": a["similarity"],
            "employee_id": a["employee_id"],
            "full_name": a["emp"]["full_name"] if a["emp"] else None,
            "action": a["action"],
        }
        # Ghi log nghi giả mạo (CLI: không lưu ảnh bằng chứng)
        if a["action"].startswith("spoof_"):
            sp = a["spoof"]
            db.insert_spoof_log(
                meeting_id, a["employee_id"], item["full_name"], sp["level"],
                sp["score"], sp["model_score"], sp["multiframe_static"],
                sp["mode"], None)
        results.append(item)

    if verbose:
        print(f"[recognize] Khung hình có {len(faces)} khuôn mặt:")
        for r in results:
            if r["status"] == "matched":
                tag = {"checked_in": "✓ CHECK-IN", "already": "• đã có",
                       "not_invited": "⚠ NGOÀI DS", "no_profile": "? chưa có HS",
                       "spoof_suspect": "⚠ NGHI GIẢ", "spoof_spoof": "⛔ GIẢ MẠO"
                       }.get(r["action"], r["action"])
                print(f"   {tag:12} {r['employee_id']} {r['full_name']} "
                      f"(sim={r['similarity']})")
            else:
                print(f"   ? {r['status']:9} (sim={r['similarity']})")

    return {"num_faces": len(faces), "results": results}


def run_camera(rtsp_url, meeting_id, interval=2.0, show=False):
    """
    Đọc camera IP (RTSP) và xử lý mỗi `interval` giây.
    rtsp_url ví dụ: 'rtsp://user:pass@192.168.1.10:554/stream1'
    Dừng bằng Ctrl+C (hoặc phím 'q' nếu show=True).
    """
    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        print(f"[recognize] KHÔNG mở được camera: {rtsp_url}")
        return

    print(f"[recognize] Bắt đầu đọc camera, xử lý mỗi {interval}s. Ctrl+C để dừng.")
    last = 0.0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("[recognize] Mất frame, thử lại...")
                time.sleep(0.5)
                continue

            now = time.time()
            if now - last >= interval:
                last = now
                out = process_frame(frame, meeting_id)
                if show:
                    for r in out["results"]:
                        label = (r["full_name"] or r["status"])
                        fe.draw_annotation(frame, r["bbox"], label,
                                           matched=(r["status"] == "matched"))
            if show:
                cv2.imshow("Face Check-in", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        print("\n[recognize] Dừng theo yêu cầu.")
    finally:
        cap.release()
        if show:
            cv2.destroyAllWindows()
