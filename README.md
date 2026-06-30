# Hệ thống điểm danh bằng nhận diện khuôn mặt

Camera IP → laptop → nhận diện nhiều khuôn mặt/khung hình → check-in tự động → báo cáo người vắng.

## Kiến trúc

| Thành phần | Vai trò |
|---|---|
| **InsightFace** (`buffalo_l`) | Phát hiện nhiều mặt trong 1 frame (SCRFD) + sinh embedding 512-d (ArcFace) |
| **ChromaDB** | Lưu & truy vấn embedding theo cosine similarity (mở rộng tới hàng chục nghìn người nhờ HNSW) |
| **SQLite** | Hồ sơ nhân viên + cuộc họp + check-in + lịch sử |
| **PyQt6** | Giao diện đồ họa 5 tab; camera chạy trong `QThread` để không treo GUI |

### Ngưỡng (ưu tiên độ chính xác)
- `SIM_THRESHOLD = 0.50` — similarity tối thiểu để nhận là đúng người.
- `MARGIN_THRESHOLD = 0.10` — nếu người hạng 1 và hạng 2 quá sát → bỏ qua, tránh nhận nhầm.
- Lọc mặt mờ/nhỏ qua `MIN_DET_SCORE`, `MIN_FACE_PIXELS`.

Chỉnh tất cả trong `config.py`.

## Cài đặt
```bash
pip install -r requirements.txt
```
Lần chạy đầu, InsightFace tự tải model (~300MB) — cần Internet.
Có GPU: sửa `PROVIDERS` trong `config.py` thành `["CUDAExecutionProvider","CPUExecutionProvider"]`.

## Chuẩn bị dữ liệu nhân viên
```
images/
  employees.csv          # employee_id,full_name,department,position,email,phone
  NV001/  1.jpg  2.jpg    # 1–3 ảnh rõ mặt mỗi người
  NV002/  a.png
  ...
```
Tên thư mục con = `employee_id` (khớp cột trong CSV).

## Quy trình sử dụng

### Cách A — Giao diện đồ họa (PyQt6, khuyến nghị)
```bash
python gui.py
```
Cửa sổ có 5 tab:
1. **Nhân viên** — thêm/sửa hồ sơ; đăng ký khuôn mặt (chọn 1–3 ảnh cho 1 người, hoặc đăng ký hàng loạt từ `images/`).
2. **Cuộc họp** — tạo cuộc họp mới (reset check-in, lưu lịch sử họp cũ); **chọn thành phần triệu tập**: mời tất cả, hoặc tick chọn một nhóm (có ô lọc theo tên/mã/phòng ban và nút chọn theo phòng ban); xem lịch sử cuộc họp kèm số người triệu tập.
3. **Điểm danh (Camera)** — nhập RTSP (hoặc `0` cho webcam) → *Bắt đầu* → video hiện khung + tên, tự động check-in; nhật ký bên dưới.
4. **Demo Realtime** — video bên trái, **danh sách người nhận diện** bên phải gồm **ID · Họ tên · Đơn vị công tác · Time** (mỗi người 1 dòng, cập nhật thời gian khi xuất hiện lại).
5. **Báo cáo** — bảng đã / chưa check-in, nút xuất CSV người vắng.

> Nguồn camera: nhập `rtsp://user:pass@ip:554/stream1`, hoặc gõ `0` để dùng webcam laptop test nhanh.

### Cách B — Dòng lệnh (CLI)
```bash
python main.py init                       # 1. tạo database
python main.py enroll                     # 2. đăng ký nhân viên (sinh embedding)
python main.py meeting "Hop giao ban T6"              # tạo cuộc họp (triệu tập TẤT CẢ)
python main.py meeting "Hop bo phan" --invite NV001,NV002,NV003   # chỉ triệu tập nhóm
python main.py camera "rtsp://..." --show # 4. nhận diện
python main.py report                     # 5. báo cáo + xuất CSV người vắng
```
Test nhanh không cần camera:
```bash
python main.py photo anh_ban_hop.jpg
```

## Chống giả mạo (Anti-Spoofing / Liveness)
Ngăn dùng **ảnh in, ảnh/video trên màn hình** để điểm danh hộ. Kết hợp 2 tín hiệu:
- **MiniFASNet** (Silent-Face-Anti-Spoofing): model thụ động phân loại thật/giả từng khuôn mặt.
- **Phân tích đa frame**: theo dõi vi chuyển động qua nhiều frame; ảnh tĩnh đứng im bất thường → tăng nghi ngờ (củng cố cho model).

**3 mức quyết định** (ngưỡng trong `config.py`):
- `score ≥ REAL` (0.70) → thật, cho check-in.
- `SPOOF ≤ score < REAL` → nghi ngờ (vàng): **không check-in**, ghi log.
- `score < SPOOF` (0.40) → giả mạo rõ (đỏ): **không check-in**, ghi log.

Mọi lần nghi giả mạo được ghi vào bảng `spoof_log` (kèm ảnh bằng chứng trong `reports/spoof_captures/`) và hiển thị ở tab Báo cáo.

### Bật/tắt và cài model
- Bật/tắt: `ANTISPOOF_ENABLED = True/False` trong `config.py`. Tắt → hệ thống chạy như cũ.
- **Fail mềm**: nếu chưa cài model MiniFASNet, hệ thống tự chạy chế độ `multiframe_only` (chỉ đa frame) — vẫn hoạt động nhưng chỉ bắt được ảnh đứng im rõ ràng. Để chống giả mạo mạnh, cài model thật:
  1. Tải repo [Silent-Face-Anti-Spoofing](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing).
  2. Đặt file `.pth` vào `antispoof_models/`.
  3. Hoàn thiện `antispoof_models/model_loader.py` theo hướng dẫn trong file.

> Lưu ý: chế độ đa frame cần nhiều frame liên tiếp nên **chỉ hiệu quả với camera**, không áp dụng được cho 1 ảnh tĩnh đơn lẻ (`photo`). Với ảnh tĩnh, chỉ phần MiniFASNet có tác dụng.

## Thành phần triệu tập (mỗi cuộc họp)
Mỗi cuộc họp có một **danh sách triệu tập** riêng (bảng `meeting_invitees`):
- Tạo họp có thể mời **tất cả** nhân viên hoặc chỉ **một nhóm**.
- Báo cáo "vắng" chỉ tính trong số người được triệu tập (không tính nhân viên khác).
- Nếu camera nhận diện được người **không thuộc diện triệu tập**: hệ thống **không check-in**, chỉ hiện cảnh báo "⚠ ngoài DS" (khung vàng) trên video và trong danh sách.

## Cơ chế chống trùng check-in
- Cột `employee_id` trong `check_in` là **UNIQUE**.
- Trước khi insert kiểm tra `is_checked_in`; insert dùng `INSERT OR IGNORE`.
→ Một người xuất hiện ở nhiều frame chỉ check-in **1 lần**.

## Nhiều camera
Chạy nhiều tiến trình `camera`, mỗi cái một RTSP, cùng trỏ vào 1 cuộc họp. Vì DB chống trùng, các camera bổ sung góc nhìn cho nhau mà không tạo bản ghi lặp.

## Mở rộng tới >100 người
Kiến trúc không đổi. Khi số lượng lớn:
- Tăng nhiều ảnh/người để tăng độ chính xác.
- Cân nhắc nâng `det_size` nếu người ngồi xa camera.
- ChromaDB HNSW xử lý tốt hàng chục nghìn vector.
