"""
antispoof.py — Chống giả mạo khuôn mặt (anti-spoofing / liveness).

Kết hợp 2 tín hiệu (theo phương án đã chốt A + C):
  A. MiniFASNet (Silent-Face-Anti-Spoofing, Minivision): model thụ động real/fake.
  C. Phân tích đa frame: vi chuyển động của khuôn mặt qua nhiều frame.

THIẾT KẾ FAIL-MỀM:
  - Nếu KHÔNG có model MiniFASNet (chưa tải, thiếu thư viện torch...),
    engine vẫn chạy nhưng chỉ dùng phần C, và báo rõ qua thuộc tính `.mode`.
  - Nếu cả hai đều tắt -> mọi khuôn mặt được coi là 'real' (bỏ qua anti-spoof).

KẾT QUẢ trả về cho mỗi khuôn mặt (assess):
  {
    'level': 'real' | 'suspect' | 'spoof',
    'score': float,            # điểm 'thật' tổng hợp 0..1
    'model_score': float|None, # điểm từ MiniFASNet (None nếu không có model)
    'multiframe_static': bool, # True nếu đa frame nghi tĩnh
    'mode': 'model+multiframe' | 'multiframe_only' | 'disabled'
  }

GIẢI THÍCH NGƯỠNG (config):
  score >= REAL  -> real
  SPOOF<=score<REAL -> suspect
  score < SPOOF  -> spoof
"""
import os
import glob
import numpy as np

import config


# ===================================================================
# Phần A: MiniFASNet wrapper (tải mềm)
# ===================================================================
class _MiniFASNet:
    """
    Bọc model Silent-Face-Anti-Spoofing.
    Tải các .pth trong config.ANTISPOOF_MODEL_DIR. Nếu không có -> available=False.

    Lưu ý: package gốc 'Silent-Face-Anti-Spoofing' không có trên PyPI dưới dạng
    import chuẩn; thực tế người dùng thường copy thư mục 'src' của repo vào project.
    Để mã không phụ thuộc cứng, ta nạp model qua torch nếu khả dụng, và bắt mọi lỗi.
    """
    def __init__(self):
        self.available = False
        self.models = []
        self._torch = None
        self._init_try()

    def _init_try(self):
        if not config.ANTISPOOF_ENABLED:
            return
        model_files = glob.glob(os.path.join(config.ANTISPOOF_MODEL_DIR, "*.pth"))
        if not model_files:
            print("[antispoof] Không thấy model .pth -> dùng chế độ multiframe_only.")
            return
        try:
            import torch  # noqa
            self._torch = torch
            # Việc nạp kiến trúc MiniFASNet cần code model của repo Minivision.
            # Ta thử import; nếu không có, fail mềm.
            from antispoof_models.model_loader import load_minifasnet  # type: ignore
            for mf in model_files:
                self.models.append(load_minifasnet(mf, torch))
            self.available = len(self.models) > 0
            if self.available:
                print(f"[antispoof] Đã nạp {len(self.models)} model MiniFASNet.")
        except Exception as e:
            print(f"[antispoof] Không nạp được MiniFASNet ({e}). "
                  f"-> dùng multiframe_only.")
            self.available = False

    def predict_real_score(self, face_crop_bgr):
        """
        Trả về điểm 'thật' 0..1 từ ensemble các model.
        face_crop_bgr: vùng khuôn mặt đã cắt (numpy BGR).
        """
        if not self.available:
            return None
        try:
            import numpy as np
            scores = []
            for m in self.models:
                # mỗi loader trả callable(crop)->prob_real
                scores.append(float(m(face_crop_bgr)))
            return float(np.mean(scores)) if scores else None
        except Exception as e:
            print(f"[antispoof] Lỗi suy luận MiniFASNet: {e}")
            return None


# ===================================================================
# Phần C: Tracker đa frame
# ===================================================================
class MultiFrameTracker:
    """
    Theo dõi vi chuyển động của từng người qua nhiều frame.

    Cơ chế: với mỗi employee_id, lưu lịch sử embedding gần nhất.
    Mặt thật có vi biến thiên (chớp mắt, lắc nhẹ) -> embedding dao động nhẹ.
    Ảnh in/màn hình đứng im -> embedding gần như không đổi.

    is_static(emp_id, embedding) trả về (đủ_mẫu, nghi_tĩnh, độ_biến_thiên).
    """
    def __init__(self):
        self.history = {}  # emp_id -> list[np.ndarray]

    def update(self, emp_id, embedding):
        buf = self.history.setdefault(emp_id, [])
        buf.append(np.asarray(embedding, dtype=np.float32))
        if len(buf) > config.MULTIFRAME_WINDOW:
            buf.pop(0)

    def assess(self, emp_id):
        buf = self.history.get(emp_id, [])
        if len(buf) < config.MULTIFRAME_MIN_SAMPLES:
            return (False, False, 0.0)  # chưa đủ mẫu
        arr = np.stack(buf)
        # độ biến thiên = trung bình khoảng cách giữa các frame liên tiếp
        diffs = np.linalg.norm(np.diff(arr, axis=0), axis=1)
        variation = float(np.mean(diffs))
        static = variation < config.MULTIFRAME_MIN_VARIATION
        return (True, static, variation)

    def reset(self, emp_id=None):
        if emp_id is None:
            self.history.clear()
        else:
            self.history.pop(emp_id, None)


# ===================================================================
# Engine tổng hợp
# ===================================================================
class AntiSpoofEngine:
    def __init__(self):
        self.enabled = config.ANTISPOOF_ENABLED
        self.model = _MiniFASNet() if self.enabled else None
        self.tracker = MultiFrameTracker()

    @property
    def mode(self):
        if not self.enabled:
            return "disabled"
        if self.model and self.model.available:
            return "model+multiframe"
        return "multiframe_only"

    def assess(self, face_crop_bgr, emp_id, embedding):
        """
        Đánh giá 1 khuôn mặt. Cập nhật tracker đa frame và trả về dict kết quả.
        """
        if not self.enabled:
            return {"level": "real", "score": 1.0, "model_score": None,
                    "multiframe_static": False, "mode": "disabled"}

        # --- Phần A: model ---
        model_score = None
        if self.model and self.model.available and face_crop_bgr is not None:
            model_score = self.model.predict_real_score(face_crop_bgr)

        # --- Phần C: đa frame ---
        enough, static = False, False
        if config.MULTIFRAME_ENABLED and embedding is not None:
            self.tracker.update(emp_id, embedding)
            enough, static, _var = self.tracker.assess(emp_id)

        # --- Tổng hợp điểm ---
        if model_score is not None:
            # Có model thật: model quyết định, đa frame chỉ CỦNG CỐ nghi ngờ.
            score = model_score
            if config.MULTIFRAME_ENABLED and enough and static:
                score -= config.MULTIFRAME_PENALTY
            score = max(0.0, min(1.0, score))
            if score >= config.ANTISPOOF_REAL_THRESHOLD:
                level = "real"
            elif score >= config.ANTISPOOF_SPOOF_THRESHOLD:
                level = "suspect"
            else:
                level = "spoof"
        else:
            # FAIL-OPEN: KHÔNG có model -> đa frame chỉ là tín hiệu YẾU.
            # Không tự quyết "giả mạo" để chặn check-in (tránh chặn nhầm người
            # thật ngồi yên). Luôn coi là 'real' cho mục đích check-in; điểm chỉ
            # mang tính tham khảo/ghi log. Việc ghi log cảnh báo khi nghi tĩnh do
            # caller quyết định dựa trên cờ 'multiframe_static'.
            score = (config.ANTISPOOF_FALLBACK_STATIC if (enough and static)
                     else config.ANTISPOOF_FALLBACK_REAL)
            level = "real"

        return {"level": level, "score": round(score, 3),
                "model_score": None if model_score is None else round(model_score, 3),
                "multiframe_static": bool(enough and static), "mode": self.mode}

    def reset(self, emp_id=None):
        self.tracker.reset(emp_id)


def crop_face(image_bgr, bbox, margin=0.15):
    """Cắt vùng khuôn mặt theo bbox, có nới biên. Trả về numpy BGR hoặc None."""
    h, w = image_bgr.shape[:2]
    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    x1 = int(max(0, x1 - margin * bw)); y1 = int(max(0, y1 - margin * bh))
    x2 = int(min(w, x2 + margin * bw)); y2 = int(min(h, y2 + margin * bh))
    if x2 <= x1 or y2 <= y1:
        return None
    return image_bgr[y1:y2, x1:x2].copy()
