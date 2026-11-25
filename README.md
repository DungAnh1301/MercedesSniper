# ⚡ Mercedes Sniper MaxSpeed (PC Studio)

Công cụ canh & tải video YouTube **Pure Push 0ms** kết nối trực tiếp hệ thống **Mercedes Tracker**, tích hợp **Tiến trình tải độc lập (120FPS GUI)** và **Chèn mẫu CapCut PC 1-Chạm**.

## 📥 Tải Xuống Bản Mới Nhất (.EXE Độc Lập)

👉 **[Tải ngay MercedesSniper_MaxSpeed.exe (Bản mới nhất)](https://github.com/DungAnh1301/MercedesSniper/releases/latest/download/MercedesSniper_MaxSpeed.exe)**

*(File `.exe` duy nhất đã đóng gói sẵn FFmpeg & bộ tải đa luồng, không cần cài đặt Python).*

---

## ✨ Tính năng nổi bật
- **Pure Push 0ms SSE**: Nhận tín hiệu video mới tức thời từ Server, tự động bóc tách luồng và tải đa luồng tốc độ tối đa.
- **Kiến trúc 2 Tiến trình Tách rời**: Giao diện PyQt6 hoàn toàn độc lập với tiến trình tải ngầm (`BELOW_NORMAL_PRIORITY`), mượt tuyệt đối không giật lag kể cả khi tải nhiều luồng 1080p/4K cùng lúc.
- **Đồng bộ Video từ Database Server**: Hiển thị đầy đủ danh sách video phát sinh trên Server trong lúc tắt máy để chủ động bấm tải hoặc bỏ qua.
- **Quét toàn bộ Kho Mẫu CapCut PC & Gắn mẫu riêng từng kênh**: Tự động nhận diện đường dẫn dự án CapCut (kể cả ổ đĩa tùy chỉnh trong `globalSetting`), hỗ trợ gắn `mau_1`, `mau_2`... riêng cho từng kênh hoặc mở `Project trắng`.
- **Tự động cập nhật qua GitHub Releases (`Auto-Update`)**: Tự kiểm tra bản mới ngầm khi mở tool, bấm 1 chạm để tự tải, xác thực `SHA-256` và nâng cấp không mất cấu hình.

---

## 🚀 Phát hành phiên bản mới lên GitHub Releases (Dành cho Admin)

Chạy trực tiếp file `.bat` hoặc lệnh Python để tự động tăng phiên bản, đóng gói `.exe`, kiểm thử `--self-test` và đẩy lên GitHub Releases (cả Website lẫn các máy đang mở Tool sẽ tự nhận diện bản mới ngay):

```powershell
python publish_release.py --tag v1.0.1 --notes "Nội dung nâng cấp phiên bản mới" --sync-desktop
```
Hoặc nháy đúp vào `publish_update_github.bat`.
