"""
face_engine.py — Lõi nhận diện khuôn mặt.

Bọc 2 thành phần:
  1. InsightFace (buffalo_l): phát hiện nhiều mặt trong 1 frame + sinh embedding 512-d.
  2. ChromaDB: lưu/truy vấn embedding theo cosine similarity.

Lưu ý về cosine:
  ChromaDB trả 'distance'. Với không gian cosine, similarity = 1 - distance.
  Embedding của InsightFace được chuẩn hóa L2 (normed_embedding) nên cosine dùng trực tiếp.
"""
import threading
import numpy as np
import chromadb
import config

# Tránh khởi tạo model nhiều lần (nặng) -> dùng singleton.
# Khoá để hai luồng (vd 2 tab camera) không nạp model song song.
_app = None
_collection = None
_app_lock = threading.Lock()
_collection_lock = threading.Lock()


def get_app():
    """Khởi tạo InsightFace FaceAnalysis (chỉ 1 lần, an toàn đa luồng)."""
    global _app
    if _app is None:
        with _app_lock:
            if _app is None:   # double-checked locking
                try:
                    from insightface.app import FaceAnalysis
                    app = FaceAnalysis(name=config.INSIGHTFACE_MODEL,
                                       providers=config.PROVIDERS)
                    app.prepare(ctx_id=0, det_size=config.DET_SIZE)
                    _app = app
                    print(f"[face_engine] Đã nạp model {config.INSIGHTFACE_MODEL}.")
                except Exception as e:
                    raise RuntimeError(
                        f"Không nạp được model nhận diện '{config.INSIGHTFACE_MODEL}'. "
                        f"Lần chạy đầu cần Internet để tải model (~300MB). "
                        f"Chi tiết: {e}") from e
    return _app


def get_collection():
    """Khởi tạo / lấy ChromaDB collection (cosine, an toàn đa luồng)."""
    global _collection
    if _collection is None:
        with _collection_lock:
            if _collection is None:   # double-checked locking
                client = chromadb.PersistentClient(path=config.CHROMA_PATH)
                _collection = client.get_or_create_collection(
                    name=config.CHROMA_COLLECTION,
                    metadata={"hnsw:space": "cosine"},
                )
    return _collection


def detect_faces(image_bgr):
    """
    Phát hiện tất cả khuôn mặt trong 1 ảnh (numpy BGR như cv2 đọc).
    Trả về list các face object của InsightFace (đã có .normed_embedding, .bbox, .det_score).
    Đã lọc bỏ mặt chất lượng thấp theo config.
    """
    app = get_app()
    faces = app.get(image_bgr)

    good = []
    for f in faces:
        if f.det_score < config.MIN_DET_SCORE:
            continue
        x1, y1, x2, y2 = f.bbox
        if min(x2 - x1, y2 - y1) < config.MIN_FACE_PIXELS:
            continue
        good.append(f)
    return good


def identify(embedding):
    """
    Tra cứu 1 embedding trong ChromaDB, áp dụng ngưỡng + margin (ưu tiên chính xác).

    Trả về dict:
      {'employee_id': str|None, 'similarity': float, 'status': str}
    status: 'matched' | 'unknown' | 'uncertain' | 'empty_db'
    """
    col = get_collection()
    count = col.count()
    if count == 0:
        return {"employee_id": None, "similarity": 0.0, "status": "empty_db"}

    # Lấy top-2 để kiểm tra margin giữa hạng 1 và hạng 2.
    res = col.query(
        query_embeddings=[embedding.tolist()],
        n_results=min(2, count),
    )
    metadatas = res["metadatas"][0]
    distances = res["distances"][0]

    sim1 = 1.0 - distances[0]
    emp1 = metadatas[0]["employee_id"]

    # Ngưỡng tuyệt đối
    if sim1 < config.SIM_THRESHOLD:
        return {"employee_id": None, "similarity": sim1, "status": "unknown"}

    # Kiểm tra margin nếu người hạng 2 là người KHÁC
    if len(distances) > 1:
        sim2 = 1.0 - distances[1]
        emp2 = metadatas[1]["employee_id"]
        if emp2 != emp1 and (sim1 - sim2) < config.MARGIN_THRESHOLD:
            return {"employee_id": None, "similarity": sim1, "status": "uncertain"}

    return {"employee_id": emp1, "similarity": sim1, "status": "matched"}


def add_face(face_id, employee_id, embedding):
    """Thêm 1 embedding vào ChromaDB. face_id là id duy nhất, vd 'NV001#0'."""
    col = get_collection()
    col.add(
        ids=[face_id],
        embeddings=[embedding.tolist()],
        metadatas=[{"employee_id": employee_id}],
    )


def delete_employee_faces(employee_id):
    """Xóa toàn bộ embedding của 1 nhân viên (khi cần đăng ký lại)."""
    col = get_collection()
    col.delete(where={"employee_id": employee_id})


def draw_annotation(image_bgr, bbox, label, matched=True):
    """Vẽ khung + nhãn lên frame (dùng chung cho các tab video trong GUI)."""
    import cv2
    x1, y1, x2, y2 = [int(v) for v in bbox]
    color = (0, 200, 0) if matched else (0, 0, 220)
    cv2.rectangle(image_bgr, (x1, y1), (x2, y2), color, 2)
    # nền chữ
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    cv2.rectangle(image_bgr, (x1, y1 - th - 8), (x1 + tw + 6, y1), color, -1)
    cv2.putText(image_bgr, label, (x1 + 3, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    return image_bgr
