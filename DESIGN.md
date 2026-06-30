# TÀI LIỆU THIẾT KẾ CHI TIẾT
## Hệ thống điểm danh cuộc họp bằng nhận diện khuôn mặt

> Tài liệu phục vụ **đào tạo nội bộ và chuyển giao công nghệ**. Đọc tài liệu này
> xong, kỹ sư tiếp nhận phải có khả năng: vận hành, hiệu chỉnh tham số, sửa lỗi,
> và mở rộng hệ thống mà không cần người viết gốc hỗ trợ.

---

## Mục lục

1. [Tổng quan & phạm vi](#1-tổng-quan--phạm-vi)
2. [Yêu cầu hệ thống](#2-yêu-cầu-hệ-thống)
3. [Kiến trúc tổng thể](#3-kiến-trúc-tổng-thể)
4. [Công nghệ nền tảng & lý do lựa chọn](#4-công-nghệ-nền-tảng--lý-do-lựa-chọn)
5. [Mô hình dữ liệu (SQLite + ChromaDB)](#5-mô-hình-dữ-liệu)
6. [Luồng xử lý nghiệp vụ](#6-luồng-xử-lý-nghiệp-vụ)
7. [Chi tiết từng module](#7-chi-tiết-từng-module)
8. [Thuật toán nhận diện (lõi)](#8-thuật-toán-nhận-diện-lõi)
9. [Chống giả mạo (Anti-Spoofing)](#9-chống-giả-mạo-anti-spoofing)
10. [Mô hình đa luồng của GUI](#10-mô-hình-đa-luồng-của-gui)
11. [Bảng tham số cấu hình (config.py)](#11-bảng-tham-số-cấu-hình)
12. [Bất biến & quy tắc xuyên suốt](#12-bất-biến--quy-tắc-xuyên-suốt)
13. [Cài đặt, triển khai & vận hành](#13-cài-đặt-triển-khai--vận-hành)
14. [Hiệu chỉnh độ chính xác](#14-hiệu-chỉnh-độ-chính-xác)
15. [Xử lý sự cố thường gặp](#15-xử-lý-sự-cố-thường-gặp)
16. [Hướng mở rộng](#16-hướng-mở-rộng)
17. [Bảo mật & quyền riêng tư](#17-bảo-mật--quyền-riêng-tư)
18. [Thuật ngữ](#18-thuật-ngữ)

---

## 1. Tổng quan & phạm vi

### 1.1. Bài toán
Tự động điểm danh người tham dự cuộc họp/sự kiện bằng camera, thay cho việc ký tên
hay quẹt thẻ thủ công.

### 1.2. Luồng nghiệp vụ chính
```
Camera IP / Webcam
      │  (luồng video)
      ▼
Phát hiện NHIỀU khuôn mặt trong mỗi khung hình
      │
      ▼
Với mỗi khuôn mặt: trích đặc trưng → so khớp → xác định "là ai"
      │
      ▼
Kiểm tra chống giả mạo (ảnh in / màn hình)  →  nếu giả: chặn + ghi log
      │  (nếu thật)
      ▼
Check-in tự động (chỉ người trong diện triệu tập, mỗi người 1 lần)
      │
      ▼
Báo cáo: ai đã có mặt, ai vắng → xuất CSV
```

### 1.3. Tính năng chính
- Phát hiện và nhận diện **đồng thời nhiều người** trong một khung hình (phù hợp phòng họp đông).
- **Check-in tự động, chống trùng** — một người xuất hiện ở nhiều frame/nhiều camera chỉ tính một lần.
- **Danh sách triệu tập theo từng cuộc họp** — báo cáo "vắng" chỉ tính người được mời.
- **Chống giả mạo (liveness)** — chặn điểm danh hộ bằng ảnh in hoặc màn hình điện thoại.
- Hai cách dùng: **GUI PyQt6 (5 tab)** cho người vận hành, **CLI** cho tự động hóa/kiểm thử.
- Hỗ trợ **CPU lẫn GPU**; hiển thị nhãn **tiếng Việt có dấu** trên video.

### 1.4. Ngoài phạm vi (hiện tại)
- Không có xác thực người dùng/phân quyền trên GUI (ai mở app cũng thao tác được).
- Không có API mạng/đồng bộ nhiều máy chủ — đây là ứng dụng **một máy** (single-node).
- Trọng số MiniFASNet anti-spoof **không kèm sẵn**; cần tải và tích hợp thêm (xem §9).
- Không có bộ test tự động, linter hay bước build.

---

## 2. Yêu cầu hệ thống

| Hạng mục | Tối thiểu | Khuyến nghị |
|---|---|---|
| Hệ điều hành | Windows 10/11, Linux, macOS | Windows 11 |
| Python | 3.9+ | 3.10 – 3.11 |
| RAM | 8 GB | 16 GB |
| CPU | 4 nhân | 8 nhân trở lên (chạy CPU) |
| GPU (tùy chọn) | — | NVIDIA CUDA (tăng tốc mạnh) |
| Ổ đĩa | ~1 GB (model ~300MB + dữ liệu) | SSD |
| Mạng | Cần Internet **lần đầu** để tải model | — |
| Camera | Webcam USB hoặc IP camera hỗ trợ RTSP | IP camera 1080p |

Thư viện (xem [requirements.txt](requirements.txt)):
`insightface`, `chromadb`, `onnxruntime`, `opencv-python`, `numpy`, `PyQt6`.
Anti-spoofing bằng model thật cần thêm `torch` (tùy chọn).

---

## 3. Kiến trúc tổng thể

### 3.1. Sơ đồ thành phần
```
┌────────────────────────────────────────────────────────────────┐
│                       LỚP GIAO DIỆN                            │
│  gui.py (PyQt6, 5 tab)              main.py (CLI, 6 lệnh con)  │
│  EmployeeTab MeetingTab CheckinTab  init enroll meeting        │
│  DemoTab     ReportTab              camera photo report        │
└───────────────┬──────────────────────────────┬────────────────┘
                │                               │
        gui_worker.py (QThread)                 │
        CameraWorker / EnrollWorker             │
                │                               │
                ▼                               ▼
┌────────────────────────────────────────────────────────────────┐
│                       LỚP NGHIỆP VỤ                            │
│  recognize.py  ── assess_face() (LÕI dùng chung CLI + GUI)     │
│  enroll.py     ── enroll_all()                                 │
│  report.py     ── get_absent/get_present/export_csv            │
│  antispoof.py  ── AntiSpoofEngine (model + đa frame)           │
└───────────────┬──────────────────────────────┬────────────────┘
                │                               │
                ▼                               ▼
┌────────────────────────────────────────────────────────────────┐
│                       LỚP LÕI & DỮ LIỆU                        │
│  face_engine.py  ── InsightFace (singleton) + ChromaDB        │
│      get_app()  get_collection()  identify()  draw_annotation │
│  database.py     ── SQLite (schema + thao tác)                 │
│  config.py       ── TẤT CẢ tham số tập trung tại đây           │
└───────────┬───────────────────────────────────┬───────────────┘
            ▼                                     ▼
   ChromaDB (data/chroma)                SQLite (data/hr.db)
   embedding khuôn mặt 512-d            quan hệ: NV, họp, check-in
```

### 3.2. Nguyên tắc thiết kế cốt lõi
1. **Tách lõi khỏi giao diện.** Toàn bộ logic nhận diện một khuôn mặt nằm trong
   `recognize.assess_face()`; cả CLI và GUI đều gọi hàm này. Sửa logic nhận diện
   → sửa một chỗ duy nhất.
2. **Cấu hình tập trung.** Mọi ngưỡng, đường dẫn, tham số nằm trong `config.py`.
   **Không bao giờ** hardcode rải rác trong code khác.
3. **Hai kho lưu trữ tách theo mục đích.** ChromaDB cho *vector đặc trưng*, SQLite
   cho *dữ liệu quan hệ*. (Xem §5.)
4. **Model là singleton toàn tiến trình.** Model nặng, chỉ nạp một lần, nạp trong
   luồng nền để không treo giao diện.
5. **Fail mềm (fail-soft).** Thiếu model anti-spoof, thiếu font tiếng Việt, lỗi vẽ
   nhãn... đều không làm sập chương trình mà tự suy giảm chức năng một cách an toàn.

---

## 4. Công nghệ nền tảng & lý do lựa chọn

| Thành phần | Vai trò | Vì sao chọn |
|---|---|---|
| **InsightFace** `buffalo_l` | Phát hiện mặt (SCRFD) + sinh embedding 512-d (ArcFace r50) | Độ chính xác cao, chạy được CPU/GPU qua ONNX, miễn phí, phát hiện nhiều mặt/frame |
| **ChromaDB** | Lưu & truy vấn embedding theo cosine (HNSW) | Truy vấn xấp xỉ nhanh, mở rộng tới hàng chục nghìn vector, lưu cục bộ không cần server |
| **SQLite** | Dữ liệu quan hệ (NV, họp, check-in, log) | Nhúng sẵn trong Python, không cần cài server, đủ cho quy mô một máy |
| **PyQt6** | Giao diện đồ họa | Bộ widget mạnh, hỗ trợ QThread cho xử lý nền |
| **OpenCV** | Đọc camera/ảnh, vẽ khung | Chuẩn công nghiệp cho thị giác máy tính |
| **Pillow** | Vẽ chữ Unicode (tiếng Việt) lên frame | `cv2.putText` **không** vẽ được dấu tiếng Việt |
| **MiniFASNet** (tùy chọn) | Chống giả mạo thụ động real/fake | Mô hình nhẹ, suy luận nhanh, chuyên cho liveness |

**Vì sao embedding L2-normalized quan trọng:** InsightFace trả về
`normed_embedding` (đã chuẩn hóa độ dài = 1). Nhờ đó cosine similarity tính trực
tiếp từ khoảng cách ChromaDB: `similarity = 1 - distance`. Đây là nền tảng của
mọi phép so khớp trong hệ thống.

---

## 5. Mô hình dữ liệu

Hệ thống dùng **hai kho lưu trữ tách biệt theo mục đích**, định nghĩa đường dẫn
trong [config.py](config.py):

### 5.1. ChromaDB — vector đặc trưng khuôn mặt
- Đường dẫn: `data/chroma`, collection tên `faces`, không gian **cosine** (HNSW).
- Mỗi bản ghi:
  - `id` = `"{employee_id}#{idx}"` (vd `NV001#0`, `NV001#1`) — mỗi ảnh đăng ký một vector.
  - `embedding` = vector 512 chiều (float).
  - `metadata` = `{"employee_id": "NV001"}` — để truy ngược ra người.
- Một nhân viên có **nhiều** vector (1–3 ảnh) → tăng độ bền với góc nghiêng/ánh sáng.
- Quản lý qua [face_engine.py](face_engine.py): `add_face`, `delete_employee_faces`,
  `identify`.

### 5.2. SQLite — dữ liệu quan hệ
File `data/hr.db`. Schema tạo trong [database.py](database.py:55) (`_create_schema`).
6 bảng:

#### `employees` — hồ sơ nhân viên
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `employee_id` | TEXT PK | Mã NV, vd `NV001`. **Là khóa liên kết** với tên thư mục ảnh và metadata ChromaDB |
| `full_name` | TEXT NOT NULL | Họ tên |
| `department`, `position`, `email`, `phone` | TEXT | Thông tin bổ sung |
| `created_at` | TEXT | ISO timestamp |

#### `meetings` — cuộc họp
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `meeting_id` | INTEGER PK AUTO | |
| `title` | TEXT | Tên cuộc họp |
| `started_at` | TEXT | Thời điểm bắt đầu |
| `is_active` | INTEGER | `1` = đang diễn ra. **Chỉ một** cuộc họp active tại một thời điểm |

#### `meeting_invitees` — danh sách triệu tập (N–N)
Khóa chính ghép `(meeting_id, employee_id)`. Quyết định ai là "được mời" →
nền tảng cho khái niệm "vắng".

#### `check_in` — điểm danh cuộc họp HIỆN TẠI
| Cột | Ghi chú |
|---|---|
| `(meeting_id, employee_id)` | **UNIQUE** — cùng `INSERT OR IGNORE` để chống trùng theo từng cuộc họp |
| `full_name`, `department`, `position` | Sao chép tại thời điểm check-in (snapshot) |
| `checkin_time` | Thời điểm |

> Bảng này **bị reset** mỗi khi tạo cuộc họp mới (dữ liệu cũ chuyển sang `check_in_history`).

#### `check_in_history` — lưu trữ check-in các cuộc họp đã qua
Cấu trúc tương tự `check_in`, không có ràng buộc UNIQUE (chỉ để lưu trữ).

#### `spoof_log` — nhật ký nghi giả mạo
Ghi mỗi lần phát hiện `suspect`/`spoof`: `level`, `score`, `model_score`,
`multiframe_static`, `mode`, `capture_path` (ảnh bằng chứng), `created_at`.

### 5.3. Sơ đồ quan hệ
```
employees ──< meeting_invitees >── meetings
    │                                  │
    │                                  ├──< check_in        (active, UNIQUE/họp)
    │                                  ├──< check_in_history (lưu trữ)
    └──────────────────────────────────┴──< spoof_log
```

### 5.4. Vì sao tách hai kho?
- **Bản chất dữ liệu khác nhau:** vector cần tìm-kiếm-tương-tự (ANN), dữ liệu
  quan hệ cần JOIN/ràng buộc/giao dịch. Mỗi công cụ làm tốt một việc.
- **Vòng đời khác nhau:** đăng ký lại một người chỉ động vào ChromaDB
  (`delete_employee_faces` + `add_face`), không ảnh hưởng lịch sử SQLite.

---

## 6. Luồng xử lý nghiệp vụ

### 6.1. Đăng ký nhân viên (enroll)
```
images/employees.csv + images/NV001/*.jpg
        │
        ▼  enroll.enroll_all()  ([enroll.py](enroll.py:47))
1. Đọc CSV → upsert vào employees (SQLite)
2. delete_employee_faces(NV001)            # xóa embedding cũ (replace sạch)
3. Mỗi ảnh: detect_faces() → chọn mặt LỚN NHẤT → add_face("NV001#i", emb)
        │
        ▼
   ChromaDB có embedding, SQLite có hồ sơ
```
Quy ước thư mục: **tên thư mục con = `employee_id` = khóa CSV**.

### 6.2. Tạo cuộc họp (stateful, độc quyền)
`database.create_meeting()` ([database.py](database.py:138)) thực hiện **5 bước
nguyên tử** trong một giao dịch:
```
1. Chuyển toàn bộ check_in hiện tại → check_in_history
2. Xóa sạch bảng check_in
3. UPDATE meetings SET is_active = 0  (đóng cuộc họp cũ)
4. INSERT cuộc họp mới (is_active = 1)
5. Ghi meeting_invitees (tất cả NV, hoặc nhóm được chọn)
```
→ Đảm bảo **luôn chỉ một** cuộc họp active; mọi thành phần tìm "cuộc họp hiện
tại" qua `get_active_meeting()`.

### 6.3. Nhận diện & check-in (lõi)
Một frame đi qua các bước (chi tiết thuật toán ở §8):
```
detect_faces(frame)                  # lọc mặt mờ/nhỏ
   └─ mỗi mặt → assess_face():
        identify(embedding)          # so khớp top-2 + ngưỡng + margin
        nếu matched:
           lấy hồ sơ NV (có cache RAM)
           antispoof.assess()        # kiểm tra liveness
           nếu real & do_checkin:
              insert_check_in()       # gating triệu tập + chống trùng
           nếu giả: ghi spoof_log (+ ảnh bằng chứng ở GUI)
```

### 6.4. Báo cáo
`report.get_absent()` ([report.py](report.py:15)): trong số **người được triệu
tập** của cuộc họp active, ai **chưa** có trong `check_in` → là người vắng →
in ra + xuất CSV (`utf-8-sig` để Excel đọc đúng tiếng Việt).

---

## 7. Chi tiết từng module

### 7.1. [config.py](config.py) — Cấu hình tập trung
Toàn bộ tham số. Tự tạo các thư mục cần thiết khi import. Các nhóm: đường dẫn,
model, ngưỡng nhận diện, anti-spoof, camera/vòng lặp, font. **Đây là file đầu
tiên cần xem khi hiệu chỉnh hệ thống.** (Bảng đầy đủ ở §11.)

### 7.2. [face_engine.py](face_engine.py) — Lõi nhận diện
- `get_app()` / `get_collection()`: **singleton, khóa double-checked** để hai
  luồng (vd hai tab camera) không nạp model song song.
- `detect_faces(img)`: phát hiện + **lọc chất lượng** (`MIN_DET_SCORE`,
  `MIN_FACE_PIXELS`).
- `identify(emb)`: **hàm so khớp duy nhất** của hệ thống (xem §8).
- `add_face` / `delete_employee_faces`: ghi/xóa embedding.
- `draw_annotation()`: vẽ khung + nhãn. Dùng **Pillow** để hiển thị tiếng Việt
  có dấu; tự fallback `cv2.putText` (mất dấu) nếu thiếu font. Xử lý cẩn thận
  trường hợp bbox sát mép trên frame (tránh crash).

### 7.3. [database.py](database.py) — Tầng dữ liệu SQLite
- `conn_ctx()`: context manager **tự commit/rollback/close** — luôn dùng pattern
  `with conn_ctx() as conn:` để tránh rò rỉ kết nối.
- `init_db()`: tạo schema, idempotent (chỉ chạy thật một lần/tiến trình).
- `create_meeting()`, `insert_check_in()`, `insert_spoof_log()`, `upsert_employee()`...
- **Mọi check-in phải đi qua `insert_check_in()`** — nơi duy nhất thực thi gating
  triệu tập và chống trùng.

### 7.4. [enroll.py](enroll.py) — Đăng ký hàng loạt
- `enroll_all()` duyệt `images/`, upsert NV, sinh embedding cho **mặt lớn nhất**
  mỗi ảnh.
- Hỗ trợ `progress_cb` để báo tiến độ và **hủy giữa chừng** (GUI dùng để cập nhật
  thanh tiến trình).

### 7.5. [recognize.py](recognize.py) — Lõi nghiệp vụ dùng chung
- `assess_face()`: **LÕI xử lý một khuôn mặt**, dùng chung CLI + GUI. Trả về dict
  `{bbox, status, employee_id, similarity, emp, spoof, action}`. **Không** vẽ,
  **không** emit, **không** lưu file — caller tự làm phần riêng.
- `process_frame()`: đường CLI (`photo`/`camera`) — gọi `assess_face` cho mọi mặt,
  ghi spoof_log, in kết quả.
- `run_camera()`: đọc RTSP, xử lý mỗi `interval` giây.
- `employee_info()`: lấy hồ sơ NV **có cache RAM** → tránh truy vấn DB lặp (N+1).

### 7.6. [antispoof.py](antispoof.py) — Chống giả mạo
Ba lớp: `_MiniFASNet` (model, tải mềm), `MultiFrameTracker` (đa frame),
`AntiSpoofEngine` (tổng hợp). Chi tiết ở §9.

### 7.7. [report.py](report.py) — Báo cáo
`get_present()`, `get_absent()`, `print_report()`, `export_absent_csv()`.

### 7.8. [gui.py](gui.py) — Giao diện PyQt6 (5 tab)
| Tab | Lớp | Chức năng |
|---|---|---|
| 1. Nhân viên | `EmployeeTab` | Thêm/sửa hồ sơ; đăng ký ảnh (1 người hoặc hàng loạt) |
| 2. Cuộc họp | `MeetingTab` | Tạo họp; chọn diện triệu tập (tất cả / nhóm, có lọc & chọn theo phòng ban) |
| 3. Điểm danh | `CheckinTab(BaseVideoTab)` | Camera → nhận diện → **check-in tự động** |
| 4. Demo | `DemoTab(BaseVideoTab)` | Camera + danh sách realtime (ID·Tên·Đơn vị·Time), **không** check-in |
| 5. Báo cáo | `ReportTab` | Bảng đã/chưa check-in, nhật ký giả mạo, xuất CSV |

`CheckinTab` và `DemoTab` cùng kế thừa `BaseVideoTab`; khác biệt duy nhất là
`do_checkin = True/False`.

### 7.9. [gui_worker.py](gui_worker.py) — Luồng nền
- `CameraWorker(QThread)`: đọc frame, chạy AI mỗi `interval` giây nhưng **vẽ &
  hiển thị mọi frame** (video mượt). Giao tiếp với GUI **chỉ qua signal**.
- `EnrollWorker(QThread)`: đăng ký hàng loạt trong nền + báo tiến độ.

### 7.10. [main.py](main.py) — CLI
6 lệnh con: `init`, `enroll`, `meeting`, `camera`, `photo`, `report`.

---

## 8. Thuật toán nhận diện (lõi)

Hàm `identify()` trong [face_engine.py](face_engine.py:80) — **trái tim độ chính
xác** của hệ thống. Triết lý: **thà bỏ sót còn hơn nhận nhầm** (ưu tiên precision).

```
def identify(embedding):
    1. Nếu DB rỗng → status = 'empty_db'
    2. Truy vấn TOP-2 vector gần nhất trong ChromaDB
    3. sim1 = 1 - distance[0]   (người giống nhất)

    4. NGƯỠNG TUYỆT ĐỐI:
       nếu sim1 < SIM_THRESHOLD (0.50) → 'unknown'   (không ai đủ giống)

    5. KIỂM TRA MARGIN (chống nhận nhầm hai người giống nhau):
       nếu người hạng 2 KHÁC người hạng 1
       và (sim1 - sim2) < MARGIN_THRESHOLD (0.10)
       → 'uncertain'  (hai người quá sát → không chắc → bỏ qua)

    6. Ngược lại → 'matched', trả về employee_id
```

### Bốn trạng thái trả về
| status | Ý nghĩa | Hành động |
|---|---|---|
| `matched` | Xác định chắc chắn là ai | Tiếp tục anti-spoof + check-in |
| `unknown` | Không ai đủ giống (sim thấp) | Bỏ qua (khung đỏ "unknown") |
| `uncertain` | Hai người quá giống, không chắc | Bỏ qua (tránh nhận nhầm) |
| `empty_db` | Chưa đăng ký ai | Bỏ qua |

### Vì sao cần *cả* ngưỡng tuyệt đối *và* margin?
- **Ngưỡng tuyệt đối** loại người lạ (không có trong DB) — sim với mọi người đều thấp.
- **Margin** loại trường hợp nguy hiểm hơn: người lạ **tình cờ** giống một NV
  (sim1 cao) nhưng cũng giống NV khác gần bằng (sim2 sát sim1) → hệ thống không
  dám khẳng định → bỏ qua. Đây là lá chắn chống nhận nhầm hai người giống nhau
  (anh em, sinh đôi...).

### Bộ lọc đầu vào (trước khi identify)
`detect_faces()` đã loại:
- Mặt có `det_score < MIN_DET_SCORE` (0.60) — mờ, nghiêng, chất lượng kém.
- Mặt có cạnh bbox `< MIN_FACE_PIXELS` (40px) — quá nhỏ/xa, dễ sai.

---

## 9. Chống giả mạo (Anti-Spoofing)

Mục tiêu: chặn điểm danh hộ bằng **ảnh in** hoặc **ảnh/video trên màn hình**.
Kết hợp 2 tín hiệu (phương án A + C):

### 9.1. Hai tín hiệu
- **A — MiniFASNet** (Silent-Face-Anti-Spoofing): model thụ động phân loại
  thật/giả từng khuôn mặt, trả điểm "thật" 0..1. **Quyết định chính.**
- **C — Phân tích đa frame** (`MultiFrameTracker`): theo dõi vi biến thiên
  embedding của một người qua nhiều frame. Mặt thật luôn dao động nhẹ (chớp mắt,
  lắc đầu); ảnh in/màn hình đứng im bất thường → tăng nghi ngờ. **Chỉ củng cố**
  cho model, không tự quyết.

### 9.2. Ba mức quyết định (ngưỡng trong config)
```
score ≥ REAL (0.70)           → 'real'    → CHO check-in
SPOOF (0.40) ≤ score < REAL   → 'suspect' → KHÔNG check-in, ghi log (vàng)
score < SPOOF (0.40)          → 'spoof'   → KHÔNG check-in, ghi log (đỏ)
```
Khi đa frame nghi tĩnh (đủ mẫu + biến thiên < `MULTIFRAME_MIN_VARIATION`),
trừ `MULTIFRAME_PENALTY` (0.25) vào score model.

### 9.3. Thiết kế FAIL-MỀM (rất quan trọng)
`AntiSpoofEngine.mode` tự suy giảm theo điều kiện:
```
model+multiframe   ← có .pth MiniFASNet + torch
      │ (thiếu model/torch)
      ▼
multiframe_only    ← chỉ còn phân tích đa frame
      │ (ANTISPOOF_ENABLED = False)
      ▼
disabled           ← bỏ qua hoàn toàn, mọi mặt coi là 'real'
```

**Quy tắc fail-open khi không có model:** ở chế độ `multiframe_only`, đa frame
**chỉ là tín hiệu yếu để GHI LOG cảnh báo**, KHÔNG tự quyết "giả mạo" để chặn
check-in. Lý do: tránh **chặn nhầm người thật ngồi yên**. Muốn chống giả mạo
mạnh thì **bắt buộc** tích hợp model thật (§9.4).

### 9.4. Tích hợp model MiniFASNet thật
File [antispoof_models/model_loader.py](antispoof_models/model_loader.py) hiện là
**stub** (raise `NotImplementedError` → engine tự rơi về `multiframe_only`). Để
bật model thật:
1. Tải repo [Silent-Face-Anti-Spoofing](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing).
2. Đặt các file `.pth` (vd `2.7_80x80_MiniFASNetV2.pth`) vào `antispoof_models/`.
3. Copy thư mục `src/` của repo vào project, hoàn thiện `load_minifasnet()` để trả
   về `callable(face_crop_bgr) -> prob_real (0..1)`.

### 9.5. Lưu ý vận hành
- Phân tích đa frame **chỉ hiệu quả với luồng camera**, không áp dụng cho một ảnh
  tĩnh đơn lẻ (`photo`).
- GUI lưu **ảnh bằng chứng** mỗi lần nghi giả mạo vào `reports/spoof_captures/`.

---

## 10. Mô hình đa luồng của GUI

GUI **không bao giờ** chạm trực tiếp camera/model. Mọi xử lý nặng nằm trong
`CameraWorker(QThread)`, giao tiếp với UI **chỉ qua signal**:

```
┌──────────────┐  start()   ┌─────────────────────────────┐
│  GUI thread  │ ─────────► │  CameraWorker (QThread)     │
│  (PyQt6)     │            │  - đọc frame (OpenCV)       │
│              │ ◄───────── │  - AI mỗi `interval` giây   │
│  cập nhật    │  signals   │  - vẽ MỌI frame             │
│  QLabel/Table│            │  - check-in / ghi log       │
└──────────────┘            └─────────────────────────────┘
   signals:
     frame_ready(QImage)     → hiển thị video
     face_recognized(dict)   → thêm dòng vào bảng log
     status(str)             → cập nhật trạng thái
     error(str)              → hộp thoại lỗi (vd tải model thất bại)
```

### Điểm thiết kế quan trọng
- **Tách tần suất AI và tần suất hiển thị:** chạy nhận diện mỗi `interval` giây
  (tiết kiệm CPU), nhưng vẽ kết quả đã cache lên **mọi** frame → video mượt.
- **Làm nóng model trong thread**, không phải GUI thread → giao diện không đơ lúc
  khởi động.
- **Throttle theo người** (`FACE_EMIT_THROTTLE_SEC` = 5s): một người không spam
  signal liên tục lên UI.
- **Bọc try/except** quanh vẽ nhãn để một lỗi vẽ (bbox lệch mép) không làm thoát
  luồng/sập app.
- **Dừng an toàn:** `stop()` chờ tối đa 5s; nếu kẹt (model đang tải) thì
  `terminate()`. `closeEvent` dừng mọi worker trước khi đóng.

---

## 11. Bảng tham số cấu hình

Toàn bộ trong [config.py](config.py). Các tham số quan trọng nhất:

### Model
| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `INSIGHTFACE_MODEL` | `buffalo_l` | Bộ model (SCRFD + ArcFace r50) |
| `DET_SIZE` | `(640, 640)` | Lớn → bắt mặt nhỏ/xa hơn nhưng nặng hơn. `(1024,1024)` phòng lớn, `(320,320)` mặt gần |
| `PROVIDERS` | `["CPUExecutionProvider"]` | Đổi sang `["CUDAExecutionProvider","CPUExecutionProvider"]` để chạy GPU |

### Ngưỡng nhận diện (ưu tiên chính xác)
| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `SIM_THRESHOLD` | `0.50` | Cosine tối thiểu để nhận là đúng người. **Tăng** → chặt hơn, ít nhận nhầm, dễ bỏ sót |
| `MARGIN_THRESHOLD` | `0.10` | Khoảng cách tối thiểu hạng 1 vs hạng 2. **Tăng** → thận trọng hơn |
| `MIN_DET_SCORE` | `0.60` | Bỏ mặt mờ/nghiêng dưới ngưỡng |
| `MIN_FACE_PIXELS` | `40` | Bỏ mặt nhỏ hơn (px) |

### Anti-spoofing
| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `ANTISPOOF_ENABLED` | `True` | Bật/tắt toàn bộ |
| `ANTISPOOF_REAL_THRESHOLD` | `0.70` | ≥ → thật |
| `ANTISPOOF_SPOOF_THRESHOLD` | `0.40` | < → giả rõ |
| `MULTIFRAME_WINDOW` | `5` | Số frame gần nhất đánh giá |
| `MULTIFRAME_MIN_VARIATION` | `0.005` | Dưới ngưỡng → nghi tĩnh. Đặt **rất thấp** để tránh nghi oan |
| `MULTIFRAME_PENALTY` | `0.25` | Trừ vào score khi nghi tĩnh |

### Camera / vòng lặp
| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `CAMERA_PROCESS_INTERVAL` | `1.0` | Giãn cách giữa 2 lần chạy AI (giây) |
| `FACE_EMIT_THROTTLE_SEC` | `5.0` | Giãn cách phát signal cùng một người |
| `CAMERA_FAIL_LIMIT` | `50` | Số lần đọc frame lỗi liên tiếp trước khi báo mất kết nối |

### Font (tiếng Việt)
`FONT_CANDIDATES` liệt kê font ưu tiên (arial, segoeui, tahoma, DejaVuSans...);
lấy font đầu tiên tồn tại. Thiếu font → fallback `cv2.putText` (mất dấu).

---

## 12. Bất biến & quy tắc xuyên suốt

Đây là các **quy tắc bất biến** — vi phạm sẽ gây lỗi nghiệp vụ tinh vi:

1. **Cuộc họp là stateful và độc quyền.** Luôn chỉ một cuộc họp `is_active=1`.
   Tạo họp mới = archive + reset check-in. Mọi nơi tìm cuộc họp qua
   `get_active_meeting()`.
2. **Mọi check-in qua `insert_check_in()`.** Đây là nơi duy nhất thực thi gating
   triệu tập + chống trùng. Trả về `checked_in | already | not_invited | no_profile`.
3. **Chống trùng bằng UNIQUE + INSERT OR IGNORE.** Một người ở nhiều frame/nhiều
   camera → check-in **đúng một lần**.
4. **Diện triệu tập định nghĩa "vắng".** Báo cáo chỉ tính người được mời. Người
   ngoài DS nhận diện được → **không** check-in, chỉ cảnh báo "ngoài DS".
5. **Logic nhận diện chỉ sửa trong `identify()`**, không sửa ở các caller.
6. **Anti-spoofing fail-mềm.** Suspect/spoof **không** check-in, chỉ ghi log.
   Thiếu model → tự về `multiframe_only`, không hard-fail.
7. **Cấu hình chỉ ở `config.py`.** Không hardcode ngưỡng/đường dẫn nơi khác.
8. **Khóa liên kết `employee_id`** xuyên suốt: tên thư mục ảnh = khóa CSV =
   metadata ChromaDB = PK SQLite.

---

## 13. Cài đặt, triển khai & vận hành

### 13.1. Cài đặt
```bash
pip install -r requirements.txt   # lần đầu tải model buffalo_l ~300MB (cần Internet)
```
Có GPU NVIDIA: cài `onnxruntime-gpu` và đổi `PROVIDERS` trong `config.py`.

### 13.2. Quy trình vận hành chuẩn (GUI — khuyến nghị)
```
python gui.py
```
1. **Tab Nhân viên** → nhập hồ sơ + đăng ký ảnh (hoặc đăng ký hàng loạt từ `images/`).
2. **Tab Cuộc họp** → tạo cuộc họp, chọn diện triệu tập.
3. **Tab Điểm danh** → nhập RTSP (hoặc `0` cho webcam) → *Bắt đầu* → check-in tự động.
4. **Tab Báo cáo** → xem ai vắng → xuất CSV.

### 13.3. Quy trình CLI (tự động hóa/kiểm thử)
```bash
python main.py init                          # tạo schema
python main.py enroll                        # đăng ký từ images/
python main.py meeting "Họp giao ban T6"     # tạo họp, triệu tập TẤT CẢ
python main.py meeting "Họp BP" --invite NV001,NV002   # chỉ nhóm
python main.py camera "rtsp://..." --show    # nhận diện từ camera
python main.py photo anh_hop.jpg             # test nhanh không cần camera
python main.py report                        # báo cáo + xuất CSV
```
> `python main.py photo <ảnh>` là cách **nhanh nhất** để kiểm thử đường nhận
> diện mà không cần camera.

### 13.4. Bố trí dữ liệu ảnh đăng ký
```
images/
  employees.csv        # employee_id,full_name,department,position,email,phone
  NV001/  1.jpg 2.jpg  # 1–3 ảnh rõ mặt; tên thư mục == employee_id == khóa CSV
  NV002/  a.png
```

### 13.5. Nhiều camera
Chạy nhiều tiến trình `camera`, mỗi cái một RTSP, cùng trỏ vào cuộc họp active.
Nhờ chống trùng ở DB, các camera **bổ sung góc nhìn** mà không tạo bản ghi lặp.

### 13.6. Sao lưu & khôi phục
Toàn bộ trạng thái nằm trong thư mục `data/` (`hr.db` + `chroma/`). Sao lưu cả
thư mục này là đủ. Lưu ý sao lưu khi **không** có tiến trình đang ghi.

---

## 14. Hiệu chỉnh độ chính xác

| Vấn đề | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| Nhận **nhầm** người này thành người khác | Ngưỡng quá lỏng | **Tăng** `SIM_THRESHOLD` (vd 0.55–0.60), tăng `MARGIN_THRESHOLD` |
| **Bỏ sót** (không nhận ra người thật) | Ngưỡng quá chặt / ảnh đăng ký kém | **Giảm** nhẹ `SIM_THRESHOLD`; đăng ký thêm 2–3 ảnh đa góc/ánh sáng |
| Không bắt được người **ngồi xa** | `DET_SIZE` nhỏ | Tăng `DET_SIZE` lên `(1024,1024)` (cần CPU mạnh/GPU) |
| Xử lý **chậm**, video giật | CPU yếu, det_size lớn | Giảm `DET_SIZE`, tăng `CAMERA_PROCESS_INTERVAL`, bật GPU |
| Nghi giả mạo **oan** người thật | Đa frame quá nhạy | Giảm `MULTIFRAME_MIN_VARIATION`, hoặc tích hợp model thật |
| Bỏ lọt ảnh giả | Chưa có model MiniFASNet | Tích hợp model thật (§9.4) — đa frame đơn lẻ không đủ |

**Nguyên tắc vàng:** chất lượng **ảnh đăng ký** quyết định nhiều hơn ngưỡng. Ưu
tiên 2–3 ảnh rõ mặt, đủ sáng, đa góc cho mỗi người trước khi chỉnh tham số.

---

## 15. Xử lý sự cố thường gặp

| Triệu chứng | Nguyên nhân | Khắc phục |
|---|---|---|
| Lần đầu chạy báo lỗi nạp model | Chưa tải `buffalo_l` (~300MB) | Đảm bảo có Internet lần đầu; chờ tải xong |
| `Không mở được nguồn camera` | RTSP sai / webcam bận / thiếu quyền | Kiểm tra URL `rtsp://user:pass@ip:554/...`; thử `0` cho webcam |
| Nhãn tiếng Việt **mất dấu** trên video | Thiếu font TrueType | Cài/khai báo font trong `FONT_CANDIDATES` |
| `[antispoof] Không thấy model .pth` | Chưa cài MiniFASNet | Bình thường — chạy `multiframe_only`; muốn mạnh thì tích hợp (§9.4) |
| Người thật **không** check-in được | Không thuộc diện triệu tập | Thêm vào `meeting_invitees` (tạo lại họp/chọn đúng nhóm) |
| Báo "ngoài DS" dù đã mời | Tạo họp **trước khi** đăng ký người đó | Tạo lại cuộc họp sau khi đã enroll đủ |
| Check-in **trùng/không trùng** bất thường | Hiểu sai trạng thái | Nhớ: `checked_in` (mới) vs `already` (đã có) đều là thành công |
| GUI đơ khi khởi động camera | Đang nạp model lần đầu | Chờ; model nạp trong thread, sẽ hiện "Đang chạy..." |
| Mất kết nối camera giữa chừng | Đọc frame lỗi > `CAMERA_FAIL_LIMIT` | Kiểm tra mạng/camera; worker tự dừng và báo lỗi |

---

## 16. Hướng mở rộng

Kiến trúc cho phép mở rộng mà **không đổi cấu trúc lõi**:

- **Quy mô >100 người:** ChromaDB HNSW xử lý tốt hàng chục nghìn vector. Tăng số
  ảnh/người để tăng độ chính xác; cân nhắc nâng `DET_SIZE` nếu người ngồi xa.
- **Tăng tốc:** bật GPU (`PROVIDERS`), hoặc giảm `DET_SIZE`/tăng `interval`.
- **Anti-spoof mạnh:** tích hợp MiniFASNet thật (§9.4).
- **Thêm tín hiệu nhận diện:** mọi thay đổi logic so khớp tập trung ở `identify()`.
- **Xuất báo cáo định dạng khác:** thêm hàm trong `report.py` (đã có sẵn export CSV).
- **API/đa máy:** hiện là single-node; muốn nhiều máy cần thay SQLite bằng DB
  client-server và đặt ChromaDB ở chế độ server.
- **Phân quyền GUI:** thêm lớp đăng nhập trước `MainWindow`.

---

## 17. Bảo mật & quyền riêng tư

Hệ thống xử lý **dữ liệu sinh trắc học** (khuôn mặt) — thuộc dữ liệu cá nhân nhạy
cảm. Khi chuyển giao và vận hành, cần lưu ý:

- **Lưu trữ cục bộ:** embedding (`data/chroma`) và hồ sơ (`data/hr.db`) nằm trên
  máy chạy. Bảo vệ quyền truy cập thư mục `data/` và `images/`.
- **Embedding không phục hồi được ảnh gốc** nhưng vẫn là định danh sinh trắc →
  đối xử như dữ liệu nhạy cảm.
- **Ảnh bằng chứng giả mạo** (`reports/spoof_captures/`) chứa ảnh mặt người → cần
  chính sách lưu giữ/xóa.
- **Đồng thuận:** đảm bảo người được đăng ký đồng ý thu thập khuôn mặt theo quy
  định pháp luật hiện hành.
- **RTSP có thể chứa mật khẩu camera** trong URL → không log/chia sẻ URL camera.
- Khuyến nghị bổ sung **phân quyền** trên GUI trước khi triển khai diện rộng.

---

## 18. Thuật ngữ

| Thuật ngữ | Giải thích |
|---|---|
| **Embedding** | Vector số (512-d) biểu diễn đặc trưng khuôn mặt; hai mặt giống nhau → vector gần nhau |
| **Cosine similarity** | Độ giống giữa hai vector (1 = trùng khớp, 0 = không liên quan); `= 1 - distance` |
| **L2-normalized** | Vector đã chuẩn hóa độ dài = 1 → cosine tính trực tiếp |
| **ArcFace** | Mô hình sinh embedding khuôn mặt (phần nhận diện của buffalo_l) |
| **SCRFD** | Mô hình phát hiện vị trí khuôn mặt (phần detect của buffalo_l) |
| **HNSW** | Cấu trúc đồ thị cho tìm-kiếm-tương-tự xấp xỉ nhanh (ChromaDB dùng) |
| **Margin** | Khoảng cách điểm giữa người giống nhất và người giống nhì → chống nhận nhầm |
| **Liveness / Anti-spoofing** | Phân biệt mặt thật với ảnh in/màn hình |
| **MiniFASNet** | Mạng nơ-ron nhẹ phân loại thật/giả khuôn mặt |
| **Singleton** | Mẫu thiết kế: chỉ tạo một thực thể duy nhất (model dùng chung) |
| **Fail-soft / fail-open** | Khi thiếu thành phần, hệ thống suy giảm an toàn thay vì sập |
| **Gating triệu tập** | Cơ chế chỉ cho check-in người thuộc diện được mời |
| **Throttle** | Giới hạn tần suất (vd không phát signal cùng một người liên tục) |

---

*Tài liệu thiết kế — Hệ thống điểm danh nhận diện khuôn mặt. Phục vụ đào tạo và
chuyển giao công nghệ. Mọi tham số tham chiếu tới [config.py](config.py); mọi quy
tắc nghiệp vụ tham chiếu tới mã nguồn được liên kết trong tài liệu.*
