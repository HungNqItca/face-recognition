"""
model_loader.py — Nạp model MiniFASNet (Silent-Face-Anti-Spoofing).

ĐÂY LÀ FILE MẪU. Để dùng anti-spoofing bằng model thật, làm theo các bước:

1) Tải repo: https://github.com/minivision-ai/Silent-Face-Anti-Spoofing
2) Tải các file model .pth (vd: 2.7_80x80_MiniFASNetV2.pth,
   4_0_0_80x80_MiniFASNetV1SE.pth) và đặt vào thư mục antispoof_models/.
3) Copy thư mục 'src' của repo (chứa định nghĩa MiniFASNet, anti_spoof_predict.py)
   vào project, rồi sửa hàm load_minifasnet() bên dưới để khởi tạo đúng kiến trúc.

Nếu thư mục này KHÔNG có model_loader hợp lệ, hệ thống tự chuyển sang
chế độ 'multiframe_only' (chỉ phân tích đa frame) — vẫn chạy bình thường.

Hàm cần trả về: một callable nhận vào face_crop_bgr (numpy BGR) và trả về
xác suất 'thật' trong khoảng 0..1.
"""


def load_minifasnet(model_path, torch):
    """
    Trả về callable(face_crop_bgr) -> prob_real (float 0..1).

    Mẫu khung tích hợp (cần code model của repo Minivision):

        import cv2, numpy as np
        from src.anti_spoof_predict import AntiSpoofPredict
        from src.generate_patches import CropImage
        # ... khởi tạo model từ model_path, trả về hàm dự đoán ...

    Hiện tại raise để AntiSpoofEngine bắt và chuyển sang multiframe_only.
    """
    raise NotImplementedError(
        "Chưa tích hợp MiniFASNet. Xem hướng dẫn trong antispoof_models/model_loader.py")
