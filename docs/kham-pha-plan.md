# Phương án mục "Khám phá" — tự động tìm ngách KDP hằng ngày

Mục tiêu: mỗi sáng tool tự chạy, đưa ra một bảng ngách sách (coloring book, truyện, sách hoạt động…) đang có cơ hội trên Amazon KDP, chấm điểm theo nhiều tiêu chí, so với hôm qua và tuần trước, và kèm **ý tưởng đầu sách sẵn sàng bấm "Tạo sách"** (tiêu đề, phụ đề, chủ đề từng trang, từ khoá, giá đề xuất, lý do). Người dùng chỉ việc duyệt, chọn ý tưởng, build và đưa vào hàng đợi đăng.

Phương án tận dụng phần đã có: `kdp niche` (mở rộng từ khoá, nguồn dữ liệu fixture/csv/apify/creators, chấm điểm 0–100, SQLite lưu lịch sử, concept cards), `kdp watch` (theo dõi đối thủ), bộ **Gợi ý** của trang Tạo sách (thư viện 20 ngách, Claude/Cloudflare), hàng đợi đăng sách.

## 1. Trải nghiệm trong giao diện

Trang **Khám phá** (menu trên cùng, cạnh Tạo sách):

1. **Bảng ngách hôm nay**: mỗi dòng một ngách (từ khoá), điểm tổng, 6 điểm thành phần, nhãn (Tốt / Cân nhắc / Tránh), mũi tên xu hướng so với lần chạy trước, số sách quan sát, cờ cảnh báo (thương hiệu, top 3 độc chiếm, giá thấp, nhạy cảm). Lọc theo loại sách, điểm tối thiểu, chỉ ngách mới.
2. **Thẻ ý tưởng** dưới mỗi ngách tốt: 2–3 ý tưởng đầu sách, mỗi thẻ có tiêu đề, phụ đề, nhóm độc giả, 30 chủ đề trang (hoặc dàn ý truyện), 7 từ khoá, giá đề xuất, lý do ngắn, mức độ khó làm bằng tool. Nút **Tạo sách từ ý tưởng này** mở form Tạo sách đã điền sẵn; nút **Bỏ qua**, **Theo dõi ngách** (đưa vào `kdp watch`).
3. **Lịch sử**: các lần chạy trước, ngách đã tạo sách (liên kết tới sách), ngách đã bỏ qua (không gợi ý lại trong 30 ngày).
4. **Tóm tắt trên trang chủ**: "Khám phá hôm nay: 3 ngách tốt, 1 ngách mới nổi" với liên kết.
5. **Thông báo** (tuỳ chọn): Telegram hoặc email mỗi sáng với 5 dòng tóm tắt.

## 2. Pipeline chạy hằng ngày (`kdp discover run`)

```
hạt giống  ->  mở rộng từ khoá  ->  thu thập dữ liệu thị trường  ->  chấm điểm 6 tiêu chí  ->  xếp hạng + xu hướng  ->  sinh ý tưởng  ->  lưu + báo cáo + thông báo
```

**Hạt giống**: danh sách chủ đề gốc do bạn đặt trong `discover.yaml` (ví dụ: coloring book for adults, kids activity book, cozy mystery…) cộng các chủ đề theo mùa lấy từ lịch (xem tiêu chí seasonality) và các ngách "mới nổi" phát hiện từ autocomplete hôm trước.

**Mở rộng từ khoá** (đã có, `niche expand`): template theo loại sách, gợi ý tìm kiếm Amazon (endpoint công khai, không cần key, có sẵn trong `niche/autocomplete.py`), Claude hoặc model văn bản Cloudflare nếu có key. Giới hạn ~40 từ khoá mỗi lần để nguồn dữ liệu không tốn.

**Thu thập dữ liệu thị trường** (điểm cần bạn chốt, có thể bật nhiều nguồn cùng lúc):

| Nguồn | Dữ liệu | Chi phí | Trạng thái trong tool | Nhận xét |
|---|---|---|---|---|
| Amazon autocomplete | thứ hạng và số lượng gợi ý tìm kiếm cho từ khoá (tín hiệu nhu cầu, phát hiện ngách mới nổi) | miễn phí, không key | đã có | không cho BSR/giá; đủ để xếp hạng "nhu cầu tương đối" và phát hiện từ khoá mới |
| Apify actor `kdp-book-niche-analyzer` | top sách theo từ khoá: BSR, giá, số rating, ngày phát hành, nhà xuất bản | ~1 USD / 1.000 bản ghi; 10 ngách × 20 sách/ngày ≈ 0,2 USD/ngày | đã có, chưa thử với key thật | đủ cho đầy đủ 6 tiêu chí; cần `APIFY_TOKEN` |
| Amazon Creators API | top sách theo từ khoá: giá, BSR, ngày phát hành | miễn phí | đã có, chưa thử | cần tài khoản Associates đạt 10 đơn/30 ngày; không có số rating |
| CSV từ KDSpy / BookBeam / Publisher Rocket | export của tool bạn đã trả tiền | theo tool | đã có | nhập tay, không tự động hằng ngày |
| Trình duyệt bán tự động (Edge profile đã đăng nhập, như publish run) | trang kết quả tìm kiếm Amazon, 10–20 truy vấn/ngày | miễn phí | chưa có | điều khoản Amazon cấm thu thập tự động; chỉ nên làm với tần suất rất thấp và bạn chấp nhận rủi ro; không khuyến nghị làm mặc định |
| Google Trends | xu hướng tìm kiếm theo thời gian | miễn phí, không chính thức (pytrends) | chưa có | tốt cho seasonality; dễ bị chặn tạm, cần bộ nhớ đệm |

Khuyến nghị mặc định: **autocomplete (miễn phí) cho mọi từ khoá + Apify cho 10 từ khoá tốt nhất mỗi ngày** (≈ 6 USD/tháng). Khi bạn có tài khoản Associates thì đổi Apify sang Creators API (miễn phí).

**Chấm điểm 6 tiêu chí** (giữ 3 tiêu chí đã có, thêm 3):

| Tiêu chí | Trọng số | Cách tính | Nguồn |
|---|---|---|---|
| Nhu cầu | 30 | median BSR top 10 (thang log) + thứ hạng/số gợi ý autocomplete | Apify/Creators + autocomplete |
| Dễ cạnh tranh | 25 | median số rating, tỉ lệ sách > 1.000 rating, tỉ lệ nhà xuất bản độc lập, tỉ lệ sách ra trong 12 tháng | Apify/Creators |
| Tiền | 15 | median giá, tỉ lệ sách ≥ 9,99 USD, số trang ước tính → royalty ước tính mỗi bản | Apify/Creators |
| Mùa vụ | 10 | lịch sự kiện (Christmas, Halloween, Mother's Day, back-to-school, Valentine…) và khoảng dẫn trước 8–10 tuần; Google Trends nếu bật | lịch nội bộ + Trends |
| Làm được bằng tool | 10 | ngách khớp pipeline hiện có (tô màu bold & easy: điểm cao; truyện chữ: trung bình; cần ảnh thật/giấy phép/kiến thức chuyên môn: thấp); nguồn ảnh miễn phí có đủ không | quy tắc |
| Rủi ro | 10 (trừ điểm) | thương hiệu/IP trong tiêu đề, nội dung nhạy cảm/y tế/pháp lý, trùng ngách với sách của mình đã đăng, ngách bị AI-spam (nhiều sách mới cùng kiểu trong 90 ngày) | từ dữ liệu + danh sách thương hiệu |

Điểm tổng 0–100 chỉ để **so sánh** giữa các ngách; kèm **độ tin cậy** (số sách quan sát được, có BSR/rating hay không). Nhãn: Tốt (≥ 65 và tin cậy ≥ 0,6), Cân nhắc, Tránh (rủi ro cao hoặc nhu cầu yếu).

**Xu hướng**: so với lần chạy gần nhất và trung bình 7 ngày (đã có bảng trong SQLite); đánh dấu "mới nổi" khi từ khoá lần đầu xuất hiện trong autocomplete hoặc điểm nhu cầu tăng ≥ 15.

**Sinh ý tưởng**: với 3–5 ngách tốt nhất, tạo 2–3 thẻ ý tưởng mỗi ngách: Claude (nếu có key) → model văn bản Cloudflare → template + thư viện 20 ngách của bộ Gợi ý. Mỗi thẻ đi kèm `book.yaml` nháp trong `books/ideas/<slug>/` (chưa build) để nút "Tạo sách từ ý tưởng" chỉ việc sao chép sang `books/`.

**Lưu và báo cáo**: `niches/niche_scout.sqlite` (đã có) thêm bảng `ideas` và `decisions` (đã xem / đã tạo sách / bỏ qua đến ngày…); báo cáo Markdown + CSV mỗi ngày trong `niches/YYYY-MM-DD/`; trang Khám phá đọc thẳng từ SQLite.

## 3. Lịch chạy

- **Khi `kdp ui` đang bật**: lịch trong server (thread) chạy lúc giờ bạn đặt, mặc định 06:30; trang Khám phá hiện "lần chạy gần nhất" và nút **Chạy ngay**.
- **Khi không mở giao diện**: `kdp discover schedule --time 06:30` đăng ký Windows Task Scheduler (`schtasks`) chạy `kdp discover run`; `--remove` để gỡ. Log vào `niches/discover.log`.
- Chạy thất bại (hết quota, mất mạng) thì ghi lý do và thử lại sau 1 giờ, tối đa 3 lần.

## 4. Từ ngách đến sách

1. Bấm **Tạo sách từ ý tưởng** → form Tạo sách điền sẵn (thư mục, tiêu đề, phụ đề, theme, đối tượng, từ khoá, chủ đề từng trang, giá); bạn sửa nếu muốn, bấm Gợi ý để hoàn thiện, rồi Tạo.
2. Build (Cloudflare FLUX, GPU cục bộ hoặc chuỗi dự phòng) → QA → bìa poster.
3. Đưa vào **Hàng đợi** → `kdp publish run` với cổng duyệt như hiện nay; tool ghi lại ngách gốc của mỗi sách để sau này so doanh số với điểm dự đoán.
4. `kdp watch` tự thêm 5 đối thủ đầu của ngách đã tạo sách để theo dõi giá/BSR hằng tuần.

## 5. Các bước triển khai

| Bước | Nội dung | Ước tính |
|---|---|---|
| 1 | `kdp discover run` dùng autocomplete + fixture/CSV; 6 tiêu chí; bảng xu hướng; thẻ ý tưởng template/Claude; trang Khám phá; lịch trong server UI; nút Tạo sách từ ý tưởng | 1–2 ngày làm |
| 2 | Bật Apify hoặc Creators API với key của bạn, chạy thử 7 ngày, chỉnh trọng số theo kết quả thật; Windows Task Scheduler; thông báo Telegram | 1 ngày |
| 3 | Lịch mùa vụ đầy đủ, Google Trends có bộ đệm, tự theo dõi đối thủ của ngách đã tạo sách, so doanh số thật với điểm dự đoán | 1–2 ngày |

## 6. Chi phí và rủi ro

- Apify ≈ 0,2 USD/ngày với 10 ngách × 20 sách; Claude cho ý tưởng ≈ vài cent/ngày; Cloudflare miễn phí trong hạn mức.
- Amazon không có API công khai cho KDP; mọi nguồn ngoài Creators API đều là bên thứ ba hoặc tín hiệu gián tiếp. Thu thập tự động trực tiếp từ amazon.com vi phạm điều khoản sử dụng của Amazon, nên tool không làm mặc định.
- Ước tính BSR → doanh số chỉ là tương đối; dùng để so sánh ngách với nhau, không phải dự báo doanh thu.
- Ý tưởng do AI sinh cần kiểm tra thương hiệu/IP trước khi làm (tool gắn cờ nhưng không thay thế việc tra cứu).

## 7. Cần bạn chốt

1. Nguồn dữ liệu thị trường: Apify (trả phí nhỏ), Creators API (cần Associates), chỉ autocomplete + CSV (miễn phí nhưng thiếu BSR/giá), hay kết hợp.
2. Giờ chạy hằng ngày và kênh thông báo (chỉ giao diện, Telegram, email).
3. Số ngách lấy dữ liệu mỗi ngày (mặc định 10) và danh sách chủ đề hạt giống ban đầu.
