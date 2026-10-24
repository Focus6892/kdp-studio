# Chạy thử `kdp publish run` trên tài khoản KDP thật

Kịch bản: `examples/lantern-lane` (paperback), đi hết ba tab Details → Content → Rights & Pricing,
kết thúc bằng **Save as Draft**. Không bấm Publish.

Đã kiểm tra trước khi chạy (2026-10-23): `build/interior.pdf` 28 trang và `build/cover_wrap.pdf` có sẵn,
`kdp preflight` PASS, quota tuần paperback còn 2/2.

## Bước 0 — đóng phiên probe

Phiên `kdp publish probe` và cửa sổ Edge của nó dùng chung profile `%LOCALAPPDATA%\kdp-studio\browser-profile`
với `publish run`; nếu còn mở, lệnh mới sẽ không mở được trình duyệt.

1. Trong cửa sổ Edge đang ở tab Rights & Pricing của bản nháp thử "aaaa…": bấm **Save as Draft** (hoặc bỏ qua, bản nháp đã có trên Bookshelf).
2. Trong PowerShell đang chạy probe: gõ `q` rồi Enter. Edge tự đóng.

## Bước 1 — chạy lệnh

```powershell
cd "D:\KDP amazon\kdp-studio"
python -m kdp_studio publish run examples/lantern-lane/book.yaml --format paperback
```

Tool in ra điều kiện (file build, preflight, quota), tạo thư mục
`publishing/runs/<thời gian>-st-lantern-lane-001-paperback/` với `checklist.md`, rồi mở Edge ở Bookshelf.
Nếu điều kiện hỏng, trình duyệt không mở và lệnh dừng với mã 1.

## Bước 2 — đăng nhập (nếu được hỏi)

Profile đã lưu phiên đăng nhập từ lần probe, thường không hỏi lại. Nếu KDP hiện trang đăng nhập hoặc OTP,
tool in `Amazon is asking you to sign in...` và chờ. Bạn tự đăng nhập trong Edge, xong quay lại PowerShell nhấn Enter.
CAPTCHA cũng vậy: tự giải, rồi Enter. Tool không bao giờ gõ mật khẩu hay OTP.

## Bước 3 — tab Details

Tool bấm **+ Create** → **Create paperback**, rồi điền: ngôn ngữ English, tiêu đề, phụ đề, tác giả June / Alder,
mô tả HTML (qua CKEditor), bản quyền "I own the copyright", nội dung người lớn = No, primary marketplace Amazon.com,
7 từ khoá, bỏ tick Low-content. Sau đó in:

```
--- Details: filled N field(s)
Categories must be picked in KDP's 'Choose categories' dialog: ...
Review the Details tab in the browser. [Enter] = click 'Save and Continue', q = stop:
```

Việc của bạn trước khi Enter:

- Bấm **Choose categories**, chọn 3 mục trong checklist (Short Stories; Women's Fiction > Friendship; Small Town & Rural) hoặc mục gần nhất KDP có.
- Nếu tool liệt kê `NOT filled (enter by hand)`, điền tay các ô đó.
- Cuộn xem một lượt, rồi nhấn Enter trong PowerShell. Tool bấm **Save and Continue** và ghi sự kiện `created` (quota paperback còn 1/2).

## Bước 4 — tab Content

Tool chọn **Get a free KDP ISBN** và bấm **Assign me a free KDP ISBN** (miễn phí, gắn với tựa này; bản nháp xoá đi thì số đó bỏ, không mất gì).
Nếu KDP hiện hộp xác nhận ISBN, bạn tự xác nhận. Tiếp theo tool chọn giấy cream, trim 5 x 8 in, No Bleed, Matte,
tải `interior.pdf` rồi `cover_wrap.pdf` qua hộp chọn file, và khai báo AI: Yes, mục Images (vì `provenance.cover_art: ai_generated` trong ví dụ).

Tool in `Wait for KDP to finish processing both uploads, open 'Launch Previewer' and approve it yourself...` và chờ. Việc của bạn:

- Đợi hai dòng "Manuscript uploaded successfully" và "Cover uploaded successfully" (vài phút).
- Kiểm tra lại các dropdown AI: Images phải là một mức "AI-generated"; Text và Translations là None.
- Bấm **Launch Previewer**, xem bìa và 28 trang, bấm **Approve**. Previewer đưa bạn về tab Content.
- Nhấn Enter trong PowerShell. Tool bấm **Save and Continue**.

## Bước 5 — tab Rights & Pricing

Tool chọn All territories, primary marketplace Amazon.com, giữ mọi cửa hàng Amazon ở trạng thái bật,
Expanded Distribution tắt, nhập 9.99 USD và nhấn Tab; ô giá nào KDP bỏ trống thì bấm "Base this price on Amazon.com". Rồi in:

```
This tool never clicks Publish. Review everything; if it is right, click 'Publish' yourself in the browser.
Then type: p = I clicked Publish, d = I saved it as a draft, q = stop:
```

Việc của bạn trong lần chạy thử này:

- Xem giá các thị trường, royalty KDP tính (giá in $2.30, royalty 60% ở $9.99).
- Bấm **Save as Draft** trong Edge. **Không bấm Publish Your Paperback Book.**
- Gõ `d` rồi Enter. Tool ghi `draft_saved`, trạng thái `draft`, đóng Edge.

## Bước 6 — kiểm tra kết quả

```powershell
python -m kdp_studio publish list
python -m kdp_studio publish quota
```

Thư mục run có `flow.json` (field nào tool điền, field nào bạn nhập tay, ghi chú), `screenshots/` (ảnh từng tab) và `checklist.md`.
Trên Bookshelf, tựa "The Lantern Lane Letters" ở trạng thái Draft; có thể xoá bản nháp thử "aaaa…".

## Lưu ý

- Khi tool đang gõ (có độ trễ cố ý), đừng bấm vào trình duyệt; chỉ thao tác khi PowerShell đang chờ bạn.
- `q` ở bất kỳ cổng nào dừng luồng (trạng thái `aborted`). Nếu đã qua Details, tựa vẫn nằm trên Bookshelf dạng draft.
- KDP đếm 2 tựa mới mỗi định dạng mỗi tuần; bản nháp "aaaa…" tạo tay hôm nay không có trong sổ của tool nhưng có thể được KDP tính.
- Chạy thật sau này chỉ khác ở cổng cuối: bạn bấm Publish rồi gõ `p`.

## Khi KDP báo "Title creation limit reached"

KDP đếm **mọi tựa bạn tạo** trong tuần, kể cả bản nháp chưa nộp: 2 tựa mỗi định dạng, reset Chủ nhật 00:00 UTC (07:00 giờ Việt Nam).
Bản nháp thử tạo tay không nằm trong sổ của tool, nên hãy ghi lại để `publish run` không mở trình duyệt vô ích:

```powershell
python -m kdp_studio publish quota --add-created paperback --note "ban nhap thu aaaa"
python -m kdp_studio publish quota --limit-reached paperback      # khi đã thấy hộp thoại của KDP
```

Tool tự nhận ra hộp thoại này sau "Save and Continue": kết thúc với trạng thái `blocked`, không ghi `created`, và khoá quota của định dạng đó đến khi reset.

## Chạy tiếp trên một bản nháp đã có (không tốn lượt tạo)

Giới hạn chỉ áp cho việc **tạo** tựa. Một bản nháp đã có thể được điền lại từ đầu bằng `--resume-url` với URL tab Details của nó
(mở bản nháp từ Bookshelf, URL có dạng `title-setup/paperback/<ID>/details`):

```powershell
python -m kdp_studio publish run examples/lantern-lane/book.yaml --format paperback --resume-url "https://kdp.amazon.com/en_US/title-setup/paperback/JNZ7EMV4MER/details"
```

Tool nhận ra đang ở tab Details, ghi đè toàn bộ field bằng dữ liệu trong `book.yaml` (tiêu đề, tác giả, mô tả, từ khoá, bỏ tick Low-content...),
rồi đi tiếp Content và Rights & Pricing như bình thường. Không ghi sự kiện `created`; khi bạn gõ `d` tool ghi `draft_saved`.

## Khi KDP không chuyển tab sau "Save and Continue"

Nút có thể bị mờ (ô AI tool chưa điền, chưa tick xác nhận, file còn "Processing") hoặc KDP hiện thông báo lỗi. Tool chờ 60 giây rồi hỏi
"The <tab> tab is not on screen yet..." tối đa 3 lần: bạn sửa, tự bấm Save and Continue, đợi tab hiện rồi nhấn Enter. Tool chỉ điền và
chụp ảnh khi tab thật sự đang hiển thị; nếu không bao giờ hiện, các field của tab đó được liệt kê để bạn nhập tay và lần chạy vẫn kết thúc
bình thường bằng `d` hoặc `p`.

Kết quả lần chạy thật đầu tiên (Lantern Lane, 2026-10-23/24, bản nháp JNZ7EMV4MER): tool điền 23 field, 4 field nhập tay
(language mặc định, giấy cream vì thẻ radio dạng card, territories và giá vì tab Pricing không tự hiện). Đã vá cả ba nguyên nhân.

