# Nghiên cứu quy trình KDP (Amazon) & thiết kế bộ công cụ xuất bản

*Cập nhật: 23/10/2026. Phạm vi: sách truyện chữ (eBook + paperback) và sách tô màu (paperback). Thị trường chính: amazon.com.*

---

## 0. Tóm tắt điều hành

1. **Giới hạn số lượng thay đổi toàn bộ bài toán.** KDP hiện cho phép tạo tối đa **2 tựa mới / định dạng / tuần** và nộp duyệt **2 tựa mới / định dạng / tuần** (eBook, paperback, hardcover tính riêng; reset Chủ nhật 00:00 UTC). Một tài khoản chỉ ra được ~100 paperback/năm. Bộ công cụ phải tối ưu **chất lượng từng tựa**, không phải số lượng.
2. **Chỉ được 1 tài khoản / người** (Điều khoản 4.2), không cho bên thứ ba dùng tài khoản (4.3), không thao túng hệ thống (5.8f). Vi phạm → chấm dứt, giữ royalty 3 tháng hoặc **mất toàn bộ royalty chưa trả** (5.4.8). Không có API xuất bản chính thức.
3. **Nội dung AI phải khai báo** (text, ảnh, dịch – khai riêng cho từng định dạng). Chỉnh sửa nhiều vẫn tính là AI-generated. Khai báo không hiện ra với người đọc, nhưng bị phát hiện khai sai → gỡ sách / khóa tài khoản. Enforcement tăng mạnh 2025–2026.
4. **Sách tô màu không phải low-content** theo định nghĩa KDP → được dùng Series, Expanded Distribution, Look Inside, không bị hàng chờ duyệt 3–4 tuần. Nhưng bị áp quy tắc chất lượng: cấm nội dung "tái sử dụng, lặp lại quá mức trong hoặc giữa các sách" và "không khác biệt đáng kể với sách khác".
5. **Khuyến nghị tự động hóa upload ở mức "bán tự động có người giám sát"**: công cụ điền toàn bộ form từ `book.yaml`, dừng cho người duyệt và bấm Publish; không bao giờ tự vượt CAPTCHA/OTP, không chạy headless không người. Phần đem lại lợi nhuận thật là 4 module đầu (ngách, metadata, bìa, nội dung), không phải nút upload.

---

## 1. Quy trình KDP hiện hành

### 1.1 Các bước xuất bản (theo trang "Create a Book" của KDP)

1. Bookshelf → **Create** → chọn định dạng (Kindle eBook / Paperback / Hardcover).
2. **Book details**: ngôn ngữ, tiêu đề + phụ đề, series, edition, tác giả/cộng tác viên, mô tả (HTML giới hạn), quyền xuất bản, đối tượng chính (sexually explicit? reading age), **khai báo AI**, 7 keywords, 3 categories, low-content checkbox, pre-order.
3. **Content**: ISBN (KDP free / tự có / không), upload manuscript, chọn print options (ink/paper, trim, bleed, finish), upload bìa, **Launch Previewer** (bắt buộc duyệt xong preview mới sang bước sau).
4. **Rights & Pricing**: lãnh thổ, KDP Select (eBook), giá từng marketplace, Expanded Distribution (paperback).
5. Order proof (tùy chọn) → **Publish**.

### 1.2 Giới hạn & chính sách bắt buộc

| Hạng mục | Quy định hiện hành | Nguồn |
|---|---|---|
| Tạo tựa mới | 2 tựa / định dạng / tuần (gồm cả draft) | KDP Help "Create a Book" |
| Nộp duyệt tựa mới | 2 tựa / định dạng / tuần; cập nhật sách cũ không tính | KDP Help "Create a Book" |
| Reset | Chủ nhật 00:00 UTC | KDP Help |
| Số tài khoản | "You may maintain only one account at a time" (4.2) | KDP Terms, cập nhật 21/10/2026 |
| Bên thứ ba | "You may not permit any third party to use the Program through your account" (4.3) | KDP Terms |
| Thao túng | "you will not attempt to manipulate, abuse, defraud, exploit or otherwise misuse the KDP service" (5.8f) | KDP Terms |
| Chấm dứt | Amazon có quyền chấm dứt khi "có lo ngại về tài khoản"; giữ royalty 3 tháng; vi phạm cam kết → mất royalty chưa trả (5.4.8) | KDP Terms |
| Tiêu đề + phụ đề | < 200 ký tự; cấm "bestselling", "free", lặp từ khóa chung ("notebook", "gifts", "books"), nhắc tác giả/sách khác, HTML | KDP Metadata Guidelines |
| Mô tả | Được dùng HTML; cấm URL/email/SĐT, review/trích dẫn, giá/khuyến mãi, thông tin thời vụ, nhồi keyword | KDP Metadata Guidelines |
| Keywords | 7 ô; khuyến nghị cụm 2–3 từ; cấm tên tác giả khác, "bestselling", "free", nội dung không liên quan | KDP Metadata Guidelines |
| Categories | Tối đa 3; chọn sai để thao túng → vi phạm | KDP Metadata Guidelines |
| Reading age | Tùy chọn, nhưng thiếu → không đủ điều kiện vào Children's categories & không xuất hiện trong tìm kiếm theo tuổi | KDP Help |
| Series | Low-content & public domain không được tạo series | KDP Metadata Guidelines |

### 1.3 Nội dung AI — khai báo (Content Guidelines)

- **AI-generated**: nội dung "created by an AI-based tool", vẫn là AI-generated "even if you applied substantial edits afterwards". **Phải khai báo** khi xuất bản mới hoặc khi sửa & tái xuất bản.
- **AI-assisted**: bạn tự tạo nội dung, dùng AI để "edit, refine, error-check, or otherwise improve"; brainstorm với AI cũng là assisted. **Không cần khai báo.**
- Form khai báo: câu hỏi Yes/No → 3 dropdown riêng (Text / Images / Translations), mỗi mục có phạm vi (một phần / toàn bộ) và mức chỉnh sửa (ít / nhiều). Khai riêng cho **từng định dạng**.
- Không có nhãn AI công khai trên trang sản phẩm (tính đến 10/2026). Theo các nguồn bên thứ ba, sách có ảnh AI bị review thủ công lâu hơn (3–7 ngày làm việc) và Amazon đang quét ngược catalog cũ.
- **Hệ quả cho bộ công cụ**: mọi asset phải có **provenance** (ai/công cụ nào tạo, có qua AI không) để tự sinh câu trả lời khai báo chính xác. Với mô hình của bạn: truyện chữ do LLM viết → *Text: AI-generated*; trang tô màu do model ảnh sinh → *Images: AI-generated*; bìa có art AI → *Images: AI-generated* (kể cả khi chữ do người đặt).

### 1.4 Quy tắc chất lượng ảnh hưởng trực tiếp đến mô hình "sản xuất theo chủ đề"

Trích Guide to Kindle Content Quality, mục "Disappointing content" (áp dụng cả print qua Content Guidelines):

- "Content that is **not significantly different** from content in another book available in the Kindle Store"
- "Content that is **excessively reused, recycled, or repeated** within or across books"
- "Content that is **too short**"
- "Content that is poorly translated"
- "Content that is rebranded or re-released with significant changes to the metadata"
- Zero-tolerance với sách "meant to advertise, promote, mislead, or that doesn't accurately represent the contents".

→ Bộ công cụ cần **kiểm tra trùng lặp xuyên sách** (perceptual hash ảnh, n-gram text) trước khi cho xuất bản, và tránh "đổi bìa + đổi tên" cùng một ruột.

### 1.5 Thời gian duyệt & hiển thị (KDP Timelines)

| Việc | Thời gian |
|---|---|
| Duyệt sách mới / cập nhật | ~3 ngày làm việc (tài khoản chưa có sách: đến 6 ngày) |
| Low-content | 3–4 tuần (coloring book **không** thuộc nhóm này) |
| Trang sản phẩm print | 72h trên .com; 5 ngày marketplace khác |
| Look Inside (print) | 9–10 ngày làm việc |
| Link eBook ↔ print | 48h–1 tuần |
| Sửa title/author print | chỉ trong 72h đầu sau xuất bản |
| Sales rank | cập nhật hàng giờ, hiện sau 24–48h kể từ sale đầu |

---

## 2. Thông số kỹ thuật

### 2.1 Sách truyện chữ

**Kindle eBook**
- File: **EPUB** (khuyến nghị), DOCX, KPF (Kindle Create). MOBI không còn được nhận.
- Bìa eBook: JPEG/TIFF, **2560 × 1600 px** (tỷ lệ ≥ 1.6:1), tối thiểu 1000 × 625, tối đa 10.000 px cạnh, RGB, < 50 MB. Nền trắng → thêm viền xám 3–4 px.
- Royalty: 70% khi giá $2.99–$9.99 (trừ phí delivery theo MB), 35% ngoài khoảng đó.
- KDP Select / Kindle Unlimited: độc quyền eBook 90 ngày, trả theo KENP ≈ **$0.0048/trang** (4–5/2026, số bên thứ ba). Sách 300 trang đọc hết ≈ $1.45.
- Short Reads: nghiên cứu K-lytics (14.000 sách) cho thấy 65–100 trang bán tốt nhất; giá/trang cao gấp 3.6 lần sách thường.

**Paperback (truyện chữ)**
- Trim phổ biến: 5×8, 5.25×8, 5.5×8.5, **6×9** (regular). Trang: 24–828 (white), 24–776 (cream).
- Lề trong (gutter) theo số trang: 24–150: 0.375" · 151–300: 0.5" · 301–500: 0.625" · 501–700: 0.75" · 701–828: 0.875". Lề ngoài ≥ 0.25" (không bleed) / ≥ 0.375" (có bleed).
- Font nhúng, ≥ 7 pt. PDF ≤ 650 MB. Không spread/2-up.

### 2.2 Sách tô màu (paperback)

- **Không phải low-content** ("This does not typically include activity books, such as puzzle books or coloring books") → không tick ô Low-content, được dùng KDP free ISBN, Series, Expanded Distribution, Look Inside.
- Trim phổ biến: **8.5 × 11** (large), 8.5 × 8.5 (large), 8 × 10 (regular theo ngưỡng: large = rộng > 6.12" hoặc cao > 9" → 8×10 là large). Trang 24–590 với 8.5×11 (white B&W).
- Ảnh **≥ 300 DPI**, khuyến nghị ≤ 600 DPI. Nét vẽ ≥ 0.75 pt (0.3 mm). Nền xám nếu có ≥ 10%.
- Full bleed: ảnh tràn thêm 0.125" ở trên/dưới/ngoài; trang PDF = trim + 0.25" cao + 0.125" rộng (8.5×11 → **8.625 × 11.25"** = 2588 × 3375 px @300DPI).
- Thực hành: in **một mặt** (mặt sau trống hoặc trang "test your colors") để chống thấm bút dạ; giấy trắng; grayscale hoặc 1-bit để tránh in xám lem.
- Giấy: Black ink/white là lựa chọn kinh tế; Premium color chỉ khi cần bìa trong màu (giá/trang gấp 5 lần).

### 2.3 Bìa paperback (một file PDF wrap)

- Rộng = 0.125 + lưng-sau + **spine** + mặt-trước + 0.125; Cao = 0.125 + trim-cao + 0.125.
- Spine = số trang × hệ số: white **0.002252"**, cream 0.0025", standard color 0.002252", premium color 0.002347".
- Chữ trên gáy: chỉ khi ≥ **79 trang**; cách mép gáy ≥ 0.0625" mỗi bên.
- Ảnh 300 DPI, **CMYK**, flatten, nhúng font, không color profile, không spot color, không crop mark, không mã hóa. Khuyến nghị ≤ 40 MB.
- Chữ cách trim ≥ 0.125"; viền trang trí cách trim ≥ 0.25". Vùng barcode KDP tự đặt: hộp trắng **2" × 1.2"** góc dưới phải mặt sau.
- Hardcover: case laminate, 5 trim (5.5×8.5, 6×9, 6.14×9.21, 7×10, 8.25×11), 75–550 trang, không standard color; wrap thêm 0.51" mỗi mép; dùng calculator của KDP.

### 2.4 Chi phí in & royalty (amazon.com, USD)

Công thức: `printing = fixed + pages × per_page`; `royalty = rate × list_price − printing`; rate = **60%** khi giá ≥ $9.99, **50%** khi < $9.99 (từ 10/6/2025). Giá sàn = printing / rate.

| Loại | Trim | Trang | Fixed | Per page |
|---|---|---|---|---|
| B&W | Regular | 24–110 | $2.30 | – |
| B&W | Regular | 110–828 | $1.00 | $0.012 |
| B&W | Large | 24–110 | $2.84 | – |
| B&W | Large | 110–828 | $1.00 | $0.017 |
| Standard color | Regular / Large | 72–600 | $1.00 | $0.0255 / $0.0402 |
| Premium color | Regular | 24–40 / 42–828 | $3.60 / $1.00 | – / $0.065 |
| Premium color | Large | 24–40 / 42–828 | $4.20 / $1.00 | – / $0.08 |

**Ví dụ**

| Sách | Printing | Giá bìa | Rate | Royalty/cuốn |
|---|---|---|---|---|
| Tô màu 8.5×11, 64 trang B&W | $2.84 | $7.99 | 50% | **$1.16** |
| Tô màu 8.5×11, 64 trang B&W | $2.84 | $9.99 | 60% | **$3.15** |
| Tô màu 8.5×11, 64 trang B&W | $2.84 | $12.99 | 60% | $4.95 |
| Truyện 6×9, 300 trang B&W | $4.60 | $12.99 | 60% | $3.19 |
| Truyện 6×9, 300 trang B&W | $4.60 | $14.99 | 60% | $4.39 |
| eBook truyện | – | $3.99 | 70% | ≈ $2.73 (trừ delivery) |

→ Ngưỡng **$9.99** là điểm gãy quan trọng với coloring book: tăng từ $7.99 lên $9.99 gấp gần 3 lần royalty.

---

## 3. Thị trường & nghiên cứu ngách

### 3.1 Nguồn dữ liệu cho tool nghiên cứu ngách / đối thủ

| Nguồn | Dữ liệu | Chi phí | Tính hợp lệ | Đánh giá |
|---|---|---|---|---|
| **Amazon Creators API** (thay PA-API 5, đã deprecate 4–5/2026) | SearchItems/GetItems: title, price, rating count, **WebsiteSalesRank (BSR)**, SalesRank theo browse node, pub date, pages, ảnh | Miễn phí; cần tài khoản Associates được duyệt + **≥10 qualifying sales / 30 ngày**; 1 TPS, 8.640 req/ngày ban đầu | Chính thức | Nên là xương sống; rào cản là duy trì 10 sale affiliate/tháng |
| **Keepa API** | Lịch sử BSR/giá/review theo ngày, Product Finder lọc theo category/BSR/ngày ra mắt | ~€49+/tháng, tính theo token/phút | Vendor dữ liệu hợp pháp phổ biến | Tốt cho tracking đối thủ & trend lịch sử |
| **Apify "KDP Book Niche Analyzer"** | Scrape top 16+ kết quả/keyword: BSR, rating, giá, tuổi sách, organic rank, autocomplete, opportunity score | ~$1 / 1.000 bản ghi | Scraping qua bên thứ ba | Nhanh để MVP; rủi ro ToS do vendor gánh |
| Chrome extensions (KDSpy, BookBeam, Publyze, Easy Keywords) | BSR, est. sales, niche score ngay trên trang Amazon | $47 one-time → $30/tháng | Thủ công, có người | Dùng kiểm chứng chéo |
| Publisher Rocket | Keyword, category, competition, est. search volume | one-time ~$199 | Mô hình độc quyền | Tốt cho categories |
| Helium 10 / AMZScout | Suite cho seller vật lý | $99+/tháng | – | Thừa cho KDP |
| Amazon autocomplete endpoint | Gợi ý từ khóa | Miễn phí | Không chính thức | Dùng mở rộng seed keyword |
| Google Trends (pytrends), Pinterest Trends, Etsy | Tín hiệu mùa vụ, chủ đề | Miễn phí | Không chính thức | Lọc theo mùa (Halloween, Christmas…) |
| **Tự scrape amazon.com** | Mọi thứ, gồm review text | Proxy | **Vi phạm Conditions of Use** (cấm data mining/robots) | Không khuyến nghị gắn với IP/identity tài khoản KDP |

Lưu ý: ước tính sales từ BSR giữa các tool lệch rất lớn (cùng BSR 8.723: tool A → 122/ngày, tool B → 18/ngày). Dùng BSR để **so sánh tương đối**, không coi là số bán tuyệt đối.

### 3.2 Phương pháp chấm điểm ngách (đề xuất)

Với mỗi keyword, lấy top 16–48 kết quả organic:

- **Demand** (0–40): median BSR top 10 (BSR < 50k Books → mạnh; > 500k → yếu); số kết quả ước lượng; search-volume proxy.
- **Competition ease** (0–40): median rating count; % sách > 1.000 rating; % "Independently published"; % sách xuất bản < 365 ngày (indie vào được gần đây = cửa mở).
- **Monetization** (0–20): median giá (≥ $9.99 với coloring), tỷ lệ Kindle Unlimited, có hardcover không.
- **Red flags**: top 3 chiếm > 45% click share (ASINSIGHT: "black girl coloring book for adults" top-3 = 46.7%); thương hiệu lớn (Crayola, Dover) thống trị; chủ đề có IP (Disney, Pokémon…).
- **LLM layer**: gom keyword thành cụm ngách, đọc title/subtitle/mô tả top 20 để tìm **khoảng trống** (chưa có bản large-print, chưa có bản song ngữ, chưa có bản "bold & easy" cho người cao tuổi/trẻ 3–5, chưa có series…) và đề xuất 10 concept kèm lý do.

### 3.3 Tín hiệu thị trường 2026 (nguồn bên thứ ba, cần kiểm chứng)

- Catalog coloring book trên Amazon > **100.000 tựa**; top ASIN adult coloring ước 30–40k bản/tháng; "coloring book" ~124k lượt tìm/tuần (1/2026).
- Dụng cụ (bút, màu) bán kèm mạnh → cơ hội bundle/cross-sell trong mô tả & A+ Content.
- Ngách con còn chuyển động: "bold & easy" (người lớn tuổi, lo âu), mindfulness/affirmation, theo nghề nghiệp/sở thích rất hẹp, lễ hội theo mùa, song ngữ Anh–Việt cho trẻ em gốc Việt (ngách nhỏ, ít cạnh tranh).
- Truyện chữ: KU ưu tiên fiction đọc nhanh; chiến lược phổ biến: cuốn 1 của series vào KU, giá $0.99–2.99; short reads 65–100 trang.
- Amazon Ads: CPC tăng 15–25% so với 2024; bắt đầu $5–10/ngày auto-targeting; ACOS < 30% được coi là tốt (royalty cố định nên ngưỡng thấp hơn hàng vật lý).

---

## 4. Tự động upload — đánh giá thẳng thắn

**Sự thật kỹ thuật**: KDP không có API xuất bản. Mọi "auto upload" trên thị trường (KDP Uploader Plus, Nonsense Engine KDP Publisher…) đều là **Chrome extension / browser automation điền form** trên dashboard, closed-source, chạy trong trình duyệt đã đăng nhập của người dùng.

**Rủi ro pháp lý & tài khoản**

- Terms 4.3 cấm bên thứ ba dùng tài khoản; 5.8(f) cấm manipulate/exploit/misuse. Script điền form do chính bạn vận hành không hẳn là "bên thứ ba", nhưng bot chạy headless không giám sát, đăng nhập tự động, hoặc vượt CAPTCHA/OTP là vùng xám rất rủi ro.
- Hậu quả khi bị chấm dứt: mất royalty chưa trả (5.4.8), không được mở tài khoản mới (4.2). Report 8/2026: tài khoản 14 năm bị đóng, kháng cáo rơi vào vòng lặp AI support.
- **Lợi ích rất nhỏ**: với trần 2 tựa/định dạng/tuần, mỗi tuần chỉ phải điền ~2–6 form. Công việc thủ công ~15 phút/sách. Rủi ro/lợi ích không cân xứng với full-auto.

**Khuyến nghị: "Assisted Publisher" (bán tự động có người bấm nút)**

- Playwright với **persistent profile**: người dùng tự đăng nhập một lần (và tự xử lý OTP/CAPTCHA). Tool chỉ chạy khi có người ngồi trước máy.
- Đọc `book.yaml` → điền Book Details, upload manuscript/cover, chọn print options, điền giá → **dừng** ở Previewer và ở nút Publish để người duyệt.
- Hàng đợi theo tuần: scheduler tự đếm quota 2/định dạng, không bao giờ vượt.
- Sau publish: theo dõi trạng thái "In review → Live", kiểm tra ASIN, categories, link eBook↔print, A+ Content.
- Tuyệt đối không: nhiều tài khoản, chia sẻ tài khoản, bypass CAPTCHA, chạy headless qua đêm, dùng proxy giả vị trí.

---

## 5. Kiến trúc bộ công cụ đề xuất ("kdp-studio")

```
seed topics ─► [1] niche-scout ─► niche_scores.db ─► [2] competitor-watch ─► differentiation brief
                                                               │
                                              book.yaml (single source of truth)
                                                               │
             ┌──────────────────┬──────────────────────────────┼──────────────────────┐
             ▼                  ▼                              ▼                      ▼
     [3] metadata-writer   [4] cover-forge                [5] interior-forge     provenance log
     title/sub/desc/kw     art (AI) + typography (code)   story: md→EPUB+PDF    (AI-generated?)
     categories/age        wrap PDF CMYK 300DPI           coloring: gen→clean→  → AI disclosure
     A+ copy               eBook JPEG 2560×1600           dedupe→layout PDF        answers
             └──────────────────┴──────────────┬───────────────┴──────────────────────┘
                                               ▼
                                     [6] preflight (KDP rules as code)
                                               ▼
                                 [7] assisted-publisher (Playwright, human-in-loop)
                                               ▼
                                 [8] post-publish monitor + Ads/KU tracking
```

Stack đề xuất: **Python 3.12** (pipeline, PDF, ảnh), **Playwright** (publisher), **Claude API** (text, chấm điểm, vision QA), model ảnh qua API (Ideogram v3 / GPT Image 1.5 / Flux 2 Pro / Nano Banana 2) hoặc **ComfyUI local** (Flux / SDXL + LoRA coloring-book) để giảm chi phí, **SQLite → Postgres**, dashboard **Streamlit** (MVP) → Next.js.

### 5.1 `niche-scout` — nghiên cứu ngách theo chủ đề

- Input: danh sách chủ đề (VN/EN) → LLM mở rộng thành 50–200 keyword → Amazon autocomplete → Google Trends (mùa vụ).
- Collect: Creators API `SearchItems` (SearchIndex=Books/KindleStore, Resources=BrowseNodeInfo, ItemInfo, Offers) hoặc Apify actor khi chưa có Associates.
- Score theo mục 3.2, lưu lịch sử hàng tuần → phát hiện ngách đang lên.
- Output: bảng ngách (score, demand, competition, giá, top phrases), **concept cards** (10 ý tưởng/ngách) do Claude đề xuất, kèm "điểm khác biệt bắt buộc" để qua rule "not significantly different".

### 5.2 `competitor-watch` — tự động theo dõi đối thủ

- Danh sách ASIN đối thủ/ngách → Creators API `GetItems` (10 ASIN/call) hàng ngày: BSR, giá, rating count, category ranks; hoặc Keepa cho lịch sử 1–3 năm.
- Phân tích bìa đối thủ bằng vision model: palette, bố cục, font style → tránh trùng, tìm "mã màu kệ hàng" của ngách.
- Review mining: gom review 1–3 sao (thủ công qua browser pane/extension hoặc Keepa nếu có) → LLM trích insight ("giấy mỏng", "hình quá chi tiết cho trẻ 4 tuổi", "thiếu trang trống") → feature list cho sách của mình.
- Output: **differentiation brief** (markdown) tự động ghép vào `book.yaml`.

### 5.3 `metadata-writer` — tiêu đề, mô tả, keywords, categories

- Prompt Claude với brief + rule KDP → sinh 5 bộ (title ≤ 200 ký tự, subtitle chứa cụm tìm kiếm tự nhiên, mô tả HTML `<b><i><br><ul><li><h4–h6>`, 7 keywords không trùng title, 3 categories từ danh mục KDP, reading age, series name).
- **Validator** cứng: regex cấm "bestselling|free|#1|notebook notebook…", URL/email, review, độ dài; kiểm tra keywords không lặp từ đã có trong title/categories (KDP khuyên).
- Chấm điểm bằng rubric (rõ ràng, đúng ngách, không misleading) → người chọn.
- Sinh luôn: A+ Content copy, blurb cho eBook, câu trả lời **AI disclosure** từ provenance log.

### 5.4 `cover-forge` — bìa màu

- Art sinh bằng AI **không chứa chữ** (prompt "no text"), chữ do code đặt (Pillow/Skia hoặc HTML→PDF qua Chromium) với font OFL (Google Fonts) → chữ luôn sắc nét, không lỗi chính tả AI, dễ A/B.
- Tính wrap từ `pages`, `trim`, `paper` theo công thức KDP; vẽ vùng barcode 2×1.2"; xuất **PDF CMYK 300 DPI** (Ghostscript/pikepdf), flatten, nhúng font; bìa eBook JPEG 2560×1600 RGB.
- QA: render thumbnail 100 px → vision check "đọc được tiêu đề?"; so khớp màu với ngách; checklist KDP (safe zone, spine text chỉ khi ≥ 79 trang).
- Model gợi ý: Ideogram v3 (bố cục/poster), GPT Image 1.5 (nghệ thuật), Flux 2 Pro (ảnh thực), Nano Banana 2 (rẻ, nhanh). Kiểm tra giấy phép thương mại từng nhà cung cấp.

### 5.5 `interior-forge` — nội dung

**Truyện chữ**
- Pipeline Claude: concept → bible (nhân vật, bối cảnh) → outline chương → draft từng chương với context bible → pass liên tục (continuity, giọng văn, readability theo tuổi) → pass biên tập → front/back matter (copyright, "also by", CTA review).
- Build: Markdown → **Pandoc** → EPUB3 (reflowable) + `epubcheck`; print PDF qua **Typst** hoặc WeasyPrint với lề theo bảng 2.1; chạy **Kindle Previewer CLI** để bắt lỗi convert.
- Kiểm tra: độ dài tối thiểu theo ngách (short read 65–100 trang; novel 250–350), trùng lặp n-gram với sách đã xuất bản của chính mình, ngôn ngữ nhạy cảm theo reading age.

**Sách tô màu**
- Prompt template theo chủ đề (style tokens: "black and white line art, coloring book page, thick clean outlines, no shading, no gray, white background, no text").
- Sinh ảnh (ComfyUI Flux/SDXL LoRA cho chi phí ~0; hoặc API $0.03–0.08/ảnh) → **clean-up**: grayscale → threshold 1-bit → remove specks → thicken lines ≥ 0.75 pt → close gaps → upscale Real-ESRGAN lên 2588×3375 px (8.5×11 + bleed).
- **QA vision** (Claude): "trang tô màu sạch? có chữ rác/vùng đen lớn/chi thừa/vi phạm IP?" → loại/regenerate.
- **Dedupe xuyên sách**: perceptual hash (pHash/dHash) so với toàn bộ thư viện ảnh đã xuất bản → chống rule "excessively reused across books".
- Layout: title page, copyright + "test your colors", "This book belongs to", N trang ảnh **in một mặt** (mặt sau trống hoặc pattern nhẹ), trang bonus/QR không được chứa URL trong mô tả (URL trong ruột sách thì được). Số trang chẵn, ≥ 24; chuẩn 60–100 trang.
- Xuất PDF (img2pdf/ReportLab) 300 DPI, không transparency, không metadata thừa.

### 5.6 `preflight` — luật KDP dưới dạng code

Kiểm tra tự động trước khi upload: kích thước trang vs trim+bleed; DPI mọi ảnh; font nhúng; không layer/transparency; số trang chẵn & trong khoảng cho phép; spine width khớp số trang cuối; cover canvas đúng công thức; file ≤ 650 MB (bìa ≤ 40 MB); metadata hợp lệ; disclosure đã sinh; dedupe pass; giá ≥ sàn và báo royalty ước tính ở 50%/60%.

### 5.7 `assisted-publisher` + `monitor`

Như mục 4. Thêm: lưu screenshot từng bước làm bằng chứng; log thời điểm nộp để tính quota tuần; sau khi Live → theo dõi BSR/giá/review của chính mình (Creators API) và chi phí Ads (export CSV từ Ads console).

### 5.8 `book.yaml` (nguồn sự thật duy nhất, ví dụ coloring book)

```yaml
id: cb-2026-0042
type: coloring            # coloring | story
niche: "bold and easy flowers for seniors"
format: paperback
trim: 8.5x11
paper: white_bw
bleed: true
pages: 64
price_usd: 9.99
title: "Bold & Easy Flowers"
subtitle: "Large Print Coloring Book for Adults and Seniors with 30 Simple Designs"
author: "Pen Name"
keywords: ["large print coloring book", "easy coloring book adults", ...]  # 7
categories: ["Crafts & Hobbies > Coloring Books for Grown-Ups", ...]      # ≤3
reading_age: null
provenance:
  interior_images: ai_generated     # → disclosure Images: yes, entire work
  cover_art: ai_generated
  text: human                       # chỉ có title/copyright
assets:
  interior_pdf: build/interior.pdf
  cover_pdf: build/cover_wrap.pdf
status: preflight_passed
```

---

## 6. Lộ trình triển khai (8 tuần, 1 dev)

| Giai đoạn | Tuần | Nội dung | Kết quả |
|---|---|---|---|
| 0 – Nền | 1–2 | `book.yaml` schema; `interior-forge` (coloring) + `cover-forge` + `preflight`; upload **thủ công** 2 cuốn | 2 cuốn Live, pipeline file chuẩn KDP đã được Amazon duyệt |
| 1 – Ngách & metadata | 3–4 | `niche-scout` (Apify hoặc Creators API) + `metadata-writer` + dashboard Streamlit | Bảng ngách có điểm; metadata validator |
| 2 – Truyện chữ & đối thủ | 5–6 | Pipeline truyện (Pandoc EPUB + Typst PDF + Kindle Previewer); `competitor-watch` | 1 short read + 1 novel Live; theo dõi 50 ASIN |
| 3 – Publisher | 7–8 | `assisted-publisher` Playwright human-in-loop; quota scheduler; monitor | Thời gian/sách từ 60' → 10' thao tác người |

Chi phí vận hành ước tính/tháng: Claude API $20–80; ảnh AI $5–30 (hoặc ~0 nếu ComfyUI local, cần GPU ≥ 12 GB); Keepa €49 (tùy chọn); Apify $5–20; Ads $150–300 cho test.

---

## 7. Rủi ro & checklist tuân thủ

**Rủi ro chính**
1. Khóa tài khoản do nội dung lặp/AI khai sai → mất toàn bộ royalty chưa trả. *Giảm thiểu*: provenance + dedupe + khai báo đúng; không "đổi bìa đổi tên".
2. Trần 2 tựa/tuần → doanh thu phụ thuộc chất lượng ngách. *Giảm thiểu*: ưu tiên series & backlist, hardcover/eBook của cùng ruột để tận dụng 3 định dạng.
3. Ảnh AI vi phạm IP (nhân vật nổi tiếng, style tác giả còn sống). *Giảm thiểu*: blacklist prompt; vision check IP.
4. Nguồn dữ liệu ngách phụ thuộc scraping. *Giảm thiểu*: xây Associates để đủ điều kiện Creators API (10 sale/30 ngày), dùng Keepa.
5. Thuế: tác giả cư trú Việt Nam không có hiệp định thuế với Mỹ → khấu trừ **30%** royalty tại nguồn (W-8BEN); nhận tiền qua Payoneer/Hyperwallet. *Cần xác minh với kế toán.*

**Checklist trước mỗi lần Publish**
- [ ] Title/subtitle < 200 ký tự, không từ cấm, đúng như trên bìa
- [ ] Mô tả không URL/review/giá; HTML hợp lệ
- [ ] 7 keywords 2–3 từ, không trùng title/category, không tên đối thủ
- [ ] 3 categories đúng ngách; reading age nếu vào Children's
- [ ] Low-content: **không tick** với coloring/activity; tick với journal/notebook
- [ ] AI disclosure khớp provenance cho từng định dạng
- [ ] Ruột: trang chẵn, ≥ 24, 300 DPI, bleed đúng, font nhúng, không transparency
- [ ] Bìa: wrap đúng công thức với số trang cuối, CMYK, spine text chỉ khi ≥ 79 trang, vùng barcode trống
- [ ] Dedupe pass (ảnh/text) với toàn bộ catalog của mình
- [ ] Giá ≥ sàn; coloring book ưu tiên ≥ $9.99 để ăn 60%
- [ ] Quota tuần còn (2/định dạng); người thật bấm Publish

---

## 8. Nguồn chính

**Chính thức (KDP / Amazon)**
- Create a Book (giới hạn 2 tựa/định dạng/tuần): https://kdp.amazon.com/en_US/help/topic/G202172740
- KDP Terms and Conditions (cập nhật 21/10/2026): https://kdp.amazon.com/terms-and-conditions
- Content Guidelines (AI-generated vs AI-assisted): https://kdp.amazon.com/help/topic/G200672390
- Guide to Kindle Content Quality (disappointing content): https://kdp.amazon.com/en_US/help/topic/G200952510
- Metadata Guidelines: https://kdp.amazon.com/en_US/help/topic/G201097560
- Low-Content Books: https://kdp.amazon.com/en_US/help/topic/GGE5T76TWKA85DJM
- Paperback Submission Guidelines (trim, lề, DPI): https://kdp.amazon.com/help/topic/G201834560
- Create a Paperback Cover (spine, bleed, CMYK): https://kdp.amazon.com/help/topic/G201953020
- Hardcover: https://kdp.amazon.com/help/topic/A2BXOVPUCZ09J8 · https://kdp.amazon.com/en_US/help/topic/GKZVNAAFYWVKZWL8
- Printing Cost: https://kdp.amazon.com/en_US/help/topic/G201834340
- eBook Cover: https://kdp.amazon.com/en_US/help/topic/G200645690
- Timelines: https://kdp.amazon.com/en_US/help/topic/G202173620
- Royalty 60%/50% (6/2025): https://kdp.amazon.com/en_US/help/topic/GXFPA52P6ZJD2U3N
- Creators API – BrowseNodeInfo/SalesRank: https://affiliate-program.amazon.com/creatorsapi/docs/en-us/api-reference/resources/browse-node-info
- Creators API – rates: https://affiliate-program.amazon.com/creatorsapi/docs/en-us/concepts/api-rates
- PA-API 5 deprecation: https://affiliate-program.amazon.com/creatorsapi/docs/en-us/paapiv5-deprecation

**Bên thứ ba (tham khảo, cần kiểm chứng)**
- Authors Guild – AI policy & daily cap 2023: https://authorsguild.org/news/amazon-adds-to-kdp-generative-ai-policy-caps-daily-self-publishing-uploads/
- AI disclosure 2026: https://www.ebookpbook.com/2026/05/27/declare-ai-use-kdp/ · https://scribecount.com/author-resource/protecting-books/kdp-ai-content-policy-the-compliance-guide · https://univers.studio/blog/kdp-ai-content-policy-2026/
- Account terminations 8/2026: https://carolynjewel.com/wordpress/2026/08/15/we-have-to-talk-about-amazon/ · https://www.writtenwordmedia.com/kdp-account-health/
- Niche tools: https://www.vappingo.com/word-blog/?p=12050 · https://self-publishingschool.com/best-amazon-keyword-tool-for-authors/
- Apify KDP Niche Analyzer: https://apify.com/getascraper/kdp-book-niche-analyzer
- Keepa API: https://keepa.com/api-docs/ · https://keepa.com/api-docs/plans-tokens.html
- BSR calculators lệch nhau: https://www.publisherchamp.com/amazon-kdp-sales-rank-calculator/ · https://kindlepreneur.com/amazon-kdp-sales-rank-calculator
- Coloring market (ASINSIGHT): https://www.asinsight.com/report/US/adult-coloring-books · https://www.asinsight.com/report/US/coloring-book
- KENP rate: https://profitable.app/kdp/stats/kenp-rate · https://www.automateed.com/kenp
- Short reads (K-lytics qua CreativIndie): https://www.creativindie.com/how-to-make-money-by-publishing-and-selling-short-stories-and-short-books-on-amazon/
- AI image models 2026: https://www.atlascloud.ai/blog/best-ai-image-generation-models-2026
- Coloring book với AI: https://bookcoverslab.com/blog/how-to-make-a-coloring-book-for-kdp-with-ai · https://tomsguide.com/how-to-make-a-coloring-book-with-midjourney
- KDP upload tools: https://chromewebstore.google.com/detail/kebppodgjfccpgkipbokpbcpgjbhcihf · https://github.com/pushkar-mishra/BookForge
- Amazon Ads: https://www.vappingo.com/word-blog/?p=11837 · https://titannetwork.com/amazon-ad-costs-guide/
- KDP formatting tools: https://kindlepreneur.com/book-formatting-software · https://scribecount.com/author-resource/writing-tools-for-authors/atticus-vs-vellum-vs-lacuna-vs-kindle-create
