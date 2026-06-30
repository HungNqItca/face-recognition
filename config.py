"""
config.py — Cấu hình chung cho toàn hệ thống nhận diện khuôn mặt.
Sửa các tham số ở đây, không hardcode rải rác trong code.
"""
import os

# ---- Đường dẫn ----
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(BASE_DIR, "data")
IMAGES_DIR  = os.path.join(BASE_DIR, "images")   # ảnh đăng ký nhân viên
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

SQLITE_PATH = os.path.join(DATA_DIR, "hr.db")
CHROMA_PATH = os.path.join(DATA_DIR, "chroma")
CHROMA_COLLECTION = "faces"

# ---- Model nhận diện ----
# buffalo_l: SCRFD detector + ArcFace r50, embedding 512 chiều, độ chính xác cao.
INSIGHTFACE_MODEL = "buffalo_l"
EMBEDDING_DIM = 512
# det_size lớn -> phát hiện được mặt nhỏ/xa hơn (phòng họp 100 người ngồi xa),
# NHƯNG nặng hơn nhiều trên CPU. Gợi ý:
#   (1024,1024): chính xác cao, phòng lớn — cần CPU mạnh hoặc GPU.
#   (640,640)  : cân bằng, khuyến nghị cho laptop CPU.
#   (320,320)  : nhanh, chỉ hợp mặt gần camera.
DET_SIZE = (640, 640)
# Dùng GPU nếu có: đổi thành ['CUDAExecutionProvider','CPUExecutionProvider']
PROVIDERS = ["CPUExecutionProvider"]

# ---- Ngưỡng nhận diện (ƯU TIÊN CHÍNH XÁC) ----
# Cosine similarity tối thiểu để chấp nhận là "đúng người".
SIM_THRESHOLD = 0.50
# Khoảng cách tối thiểu giữa người hạng 1 và hạng 2.
# Nếu hai người quá sát nhau -> không chắc chắn -> bỏ qua (tránh nhận nhầm).
MARGIN_THRESHOLD = 0.10
# Bỏ qua khuôn mặt có điểm detector thấp (mờ, nghiêng, chất lượng kém).
MIN_DET_SCORE = 0.60
# Bỏ qua khuôn mặt quá nhỏ (cạnh bbox < ngưỡng px) -> dễ nhận sai.
MIN_FACE_PIXELS = 40

# ---- Chống giả mạo (Anti-Spoofing / Liveness) ----
# Bật/tắt toàn bộ tính năng. Tắt -> hệ thống chạy như không có anti-spoof.
ANTISPOOF_ENABLED = True

# Thư mục chứa model MiniFASNet (.pth) của Silent-Face-Anti-Spoofing.
# Tải về từ: https://github.com/minivision-ai/Silent-Face-Anti-Spoofing
#   -> đặt các file .pth vào thư mục này.
ANTISPOOF_MODEL_DIR = os.path.join(BASE_DIR, "antispoof_models")

# 3 mức quyết định dựa trên điểm "thật" (real score, 0..1):
#   score >= REAL  -> thật, cho check-in
#   SPOOF <= score < REAL -> nghi ngờ (vàng), không check-in, ghi log
#   score < SPOOF  -> giả mạo rõ (đỏ), không check-in, ghi log
ANTISPOOF_REAL_THRESHOLD  = 0.70
ANTISPOOF_SPOOF_THRESHOLD = 0.40

# ---- Phân tích đa frame (heuristic C) ----
# Theo dõi vi chuyển động của khuôn mặt qua nhiều frame.
# Ảnh in / màn hình thường đứng im bất thường -> tăng nghi ngờ.
MULTIFRAME_ENABLED = True
MULTIFRAME_WINDOW = 5          # số frame gần nhất để đánh giá 1 người
# Độ biến thiên embedding tối thiểu giữa các frame để coi là "có sức sống".
# Dưới ngưỡng này trong cả cửa sổ -> nghi tĩnh (ảnh in đứng im trước camera).
# LƯU Ý: đặt RẤT THẤP để chỉ bắt trường hợp gần như đứng im tuyệt đối,
# tránh nghi oan người thật ngồi yên. Phần đa frame chỉ để CỦNG CỐ cho model,
# không tự quyết định. Hiệu chỉnh theo camera thực tế của bạn.
MULTIFRAME_MIN_VARIATION = 0.005
# Chỉ áp dụng phạt đa frame khi đã thu thập đủ số frame tối thiểu.
MULTIFRAME_MIN_SAMPLES = 4
# Mức phạt trừ vào real score khi nghi tĩnh (đa frame).
MULTIFRAME_PENALTY = 0.25

# Điểm fallback khi KHÔNG có model MiniFASNet (chế độ multiframe_only).
# LƯU Ý: ở chế độ fail-open (mặc định), đa frame CHỈ là tín hiệu yếu để ghi log
# cảnh báo, KHÔNG tự quyết "giả mạo" để chặn check-in (tránh chặn nhầm người thật
# ngồi yên). Các điểm này chỉ mang tính tham khảo/ghi log.
ANTISPOOF_FALLBACK_REAL   = 0.75   # khi đa frame thấy có chuyển động
ANTISPOOF_FALLBACK_STATIC = 0.30   # khi đa frame nghi tĩnh

# Lưu ảnh bằng chứng khi nghi giả mạo
SPOOF_CAPTURE_DIR = os.path.join(BASE_DIR, "reports", "spoof_captures")

# ---- Tham số camera / vòng lặp xử lý ----
# Giãn cách giữa 2 lần CHẠY NHẬN DIỆN trong GUI (giây). Video vẫn vẽ mọi frame.
CAMERA_PROCESS_INTERVAL = 1.0
# Nghỉ ngắn giữa các frame hiển thị để nhường CPU (giây).
FRAME_SLEEP_SEC = 0.01
# Giãn cách tối thiểu giữa 2 lần phát tín hiệu cùng 1 người (giây) -> tránh spam UI.
FACE_EMIT_THROTTLE_SEC = 5.0
# Số lần đọc frame thất bại liên tiếp trước khi báo mất kết nối và dừng.
CAMERA_FAIL_LIMIT = 50

# ---- Định dạng ----
# Hậu tố thời gian cho tên file CSV / ảnh bằng chứng.
CSV_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"

# ---- Font vẽ nhãn lên video (HỖ TRỢ TIẾNG VIỆT) ----
# cv2.putText KHÔNG vẽ được dấu tiếng Việt -> dùng Pillow với 1 font TrueType.
# Liệt kê vài font phổ biến có dấu; lấy font đầu tiên tồn tại trên máy.
# Có thể thay bằng đường dẫn tới font tuỳ ý (vd font công ty).
FONT_CANDIDATES = [
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arial.ttf"),
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "segoeui.ttf"),
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "tahoma.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",   # Linux fallback
    "/Library/Fonts/Arial.ttf",                            # macOS fallback
]
FONT_PATH = next((p for p in FONT_CANDIDATES if os.path.exists(p)), None)
# Cỡ chữ nhãn (pixel). To hơn -> dễ đọc trên video độ phân giải cao.
FONT_SIZE = 20

# ---- Tự tạo thư mục cần thiết ----
for _d in (DATA_DIR, IMAGES_DIR, REPORTS_DIR, CHROMA_PATH,
           ANTISPOOF_MODEL_DIR, SPOOF_CAPTURE_DIR):
    os.makedirs(_d, exist_ok=True)
