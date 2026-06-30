"""
main.py — Giao diện dòng lệnh điều khiển hệ thống điểm danh khuôn mặt.

Các lệnh:
  python main.py init                         # khởi tạo database
  python main.py enroll                       # đăng ký nhân viên từ thư mục images/
  python main.py meeting "Hop thang 6"        # tạo cuộc họp mới (reset check-in)
  python main.py camera rtsp://... [--show]   # chạy nhận diện từ camera IP
  python main.py photo path/to/frame.jpg      # nhận diện 1 ảnh tĩnh (test/ảnh chụp)
  python main.py report                        # in báo cáo + xuất CSV người vắng
"""
import sys
import argparse


def cmd_init(args):
    import database as db
    db.init_db()


def cmd_enroll(args):
    import enroll
    enroll.enroll_all()


def cmd_meeting(args):
    import database as db
    invitees = None
    if args.invite:
        invitees = [x.strip() for x in args.invite.split(",") if x.strip()]
    db.create_meeting(args.title, invitee_ids=invitees)


def cmd_camera(args):
    import database as db
    import recognize
    meeting = db.get_active_meeting()
    if meeting is None:
        print("Chưa có cuộc họp. Chạy: python main.py meeting \"Tên họp\"")
        return
    print(f"Cuộc họp hiện tại: #{meeting['meeting_id']} {meeting['title']}")
    recognize.run_camera(args.rtsp, meeting["meeting_id"],
                         interval=args.interval, show=args.show)


def cmd_photo(args):
    import cv2
    import database as db
    import recognize
    meeting = db.get_active_meeting()
    if meeting is None:
        print("Chưa có cuộc họp. Chạy: python main.py meeting \"Tên họp\"")
        return
    img = cv2.imread(args.path)
    if img is None:
        print(f"Không đọc được ảnh: {args.path}")
        return
    recognize.process_frame(img, meeting["meeting_id"])


def cmd_report(args):
    import report
    report.print_report()
    report.export_absent_csv()


def build_parser():
    p = argparse.ArgumentParser(description="Hệ thống điểm danh khuôn mặt")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)
    sub.add_parser("enroll").set_defaults(func=cmd_enroll)

    m = sub.add_parser("meeting")
    m.add_argument("title")
    m.add_argument("--invite", default=None,
                   help="Danh sách mã NV triệu tập, cách nhau dấu phẩy. "
                        "Bỏ trống = triệu tập tất cả. VD: --invite NV001,NV002")
    m.set_defaults(func=cmd_meeting)

    c = sub.add_parser("camera")
    c.add_argument("rtsp")
    c.add_argument("--interval", type=float, default=2.0)
    c.add_argument("--show", action="store_true")
    c.set_defaults(func=cmd_camera)

    ph = sub.add_parser("photo")
    ph.add_argument("path")
    ph.set_defaults(func=cmd_photo)

    sub.add_parser("report").set_defaults(func=cmd_report)
    return p


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
