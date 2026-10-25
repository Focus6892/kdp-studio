# kdp-studio — chạy thử trong 10 phút

## 1. Cài (Windows)

1. Cài Python 3.11 trở lên từ python.org, tick **Add python.exe to PATH**.
2. Giải nén gói, mở PowerShell trong thư mục vừa giải nén, chạy:

```powershell
Set-ExecutionPolicy -Scope Process Bypass; .\install.ps1
```

Thêm `-Local` nếu máy có GPU NVIDIA 4 GB trở lên và muốn vẽ ảnh miễn phí bằng model cục bộ (tải thêm ~4 GB). Cuối quá trình cài, `kdp doctor` in bảng kiểm tra: Python, gói, GPU, trình duyệt, key, license.

## 2. Mở giao diện

Bấm đúp **start.bat** (hoặc `python -m kdp_studio ui`). Trình duyệt mở http://127.0.0.1:8765.

## 3. Luồng làm một cuốn sách

1. **Cài đặt** → dán key (Cloudflare miễn phí là đủ để bắt đầu; có thể bỏ qua nếu dùng GPU hoặc bản vẽ vector) → **Kiểm tra**.
2. **Tạo sách** → tab *Sách tô màu* hoặc *Truyện chữ + eBook* → gõ thư mục hoặc chủ đề → **Gợi ý điền tất cả** → **Tạo** (truyện: trang sách có nút **Viết nháp các chương** để AI viết theo dàn ý, rồi Build ra PDF in + EPUB).
3. Trang sách → **Build**. Ô "Tiến trình tạo ruột" hiện số trang xong, số lần sinh lại, ảnh thu nhỏ; xong có `interior.pdf` và `cover_wrap.pdf`, preflight báo PASS.
4. **Hàng đợi** → tick sách → **Thêm vào hàng đợi** → **Chạy tựa kế tiếp còn quota**: một cửa sổ console mở Edge, tool điền từng tab KDP và dừng ở mỗi cổng cho bạn duyệt; bạn tự bấm Publish.

## 4. Những gì cần biết

- KDP cho tạo 2 tựa mỗi định dạng mỗi tuần (bản nháp cũng tính); thanh bên trái hiện số còn lại.
- Ảnh do AI vẽ phải khai báo ở tab Content của KDP; tool điền sẵn tên công cụ từ `provenance.ai_tools` trong `book.yaml`.
- Cloudflare miễn phí ≈ 55 ảnh FLUX mỗi ngày mỗi tài khoản; hết thì tool tự chuyển sang tài khoản/nền tảng kế tiếp trong chuỗi dự phòng (Cài đặt).
- License gắn với mã máy: trang **License** hiện mã máy để gửi cho người cấp key.
- Mọi lệnh có bản dòng lệnh: `python -m kdp_studio --help`.
