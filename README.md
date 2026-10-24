# kdp-studio

Bộ công cụ sản xuất sách cho Amazon KDP, bắt đầu từ sách tô màu: một file `book.yaml` làm nguồn sự thật duy nhất → ruột sách PDF, bìa wrap PDF (CMYK, 300 DPI), bìa eBook JPEG và báo cáo preflight kiểm tra theo đúng thông số KDP.

Trạng thái: **Giai đoạn 0** (interior-forge cho sách tô màu + cover-forge + preflight), **Giai đoạn 1** (niche-scout + metadata-writer), **Giai đoạn 2** (pipeline truyện chữ Markdown → EPUB + PDF in, draft bằng Claude, competitor-watch) và **Giai đoạn 3** (assisted-publisher bán tự động có người giám sát, hàng đợi theo quota tuần, monitor sau xuất bản) đã chạy được. Nghiên cứu thị trường, chính sách và kiến trúc đầy đủ nằm trong [docs/KDP-Toolkit-Research.md](docs/KDP-Toolkit-Research.md).

Luồng làm việc trọn vẹn cho một cuốn: `kdp niche run` (chọn ngách, nhận concept cards) → `kdp watch insights` (đọc review đối thủ thành differentiation brief) → viết `brief.yaml` → `kdp metadata generate` + `kdp metadata apply` → (truyện: `kdp story draft` hoặc tự viết Markdown) → `kdp build` (ruột, EPUB, bìa, preflight) → `kdp publish run` (điền form KDP trong trình duyệt của bạn, bạn bấm Publish) → `kdp publish mark ... --status live --asin` → `kdp monitor report` + `kdp watch snapshot`.

## Cài đặt

Yêu cầu Python 3.11+. Không cần GPU hay API key để chạy thử (provider `placeholder` vẽ line art thủ tục).

```bash
python -m venv .venv && . .venv/bin/activate      # Linux/macOS
python -m pip install -e ".[dev,ai,publish]"      # publish = Playwright cho kdp publish (dùng Edge/Chrome sẵn có)
python -m pytest
```

Trên Windows nếu `venv` lỗi `ensurepip` (bản Python từ Python Install Manager), cài thẳng vào user site:

```bash
python -m pip install --user -e ".[dev,ai,publish]"
```

Sau khi cài editable, `python -m kdp_studio …` chạy được từ bất kỳ thư mục nào; dữ liệu runtime (`publishing/`, `niches/`, `watch/`, `monitor/`) luôn được ghi vào thư mục dự án chứ không phải thư mục bạn đang đứng.

## Dùng nhanh

```bash
# Xem kế hoạch: số trang, kích thước bìa, chi phí in, royalty, câu trả lời khai báo AI, lỗi metadata
python -m kdp_studio validate examples/bold-easy-flowers/book.yaml

# Build ruột + bìa + preflight (ảnh placeholder, ~30 giây cho 30 trang tô màu)
python -m kdp_studio build examples/bold-easy-flowers/book.yaml

# Build thử nhanh với 8 trang tô màu
python -m kdp_studio build examples/bold-easy-flowers/book.yaml --images 8

# Chỉ chạy lại kiểm tra trên thư mục build/ hiện có
python -m kdp_studio preflight examples/bold-easy-flowers/book.yaml

# Tra cứu nhanh
python -m kdp_studio price --trim 8.5x11 --paper white_bw --pages 66 --price 9.99
python -m kdp_studio cover-size --trim 6x9 --paper cream_bw --pages 320
```

Kết quả nằm trong `build/` cạnh `book.yaml`:

| File | Nội dung |
|---|---|
| `interior.pdf` | Ruột sách đúng kích thước trim + bleed, font nhúng, trang chẵn, ≥ 24 trang |
| `cover_wrap.pdf` | Bìa wrap 1 trang: back + spine + front, ảnh CMYK JPEG 300 DPI, có hộp trắng 2"×1.2" cho barcode |
| `cover_ebook.jpg` | Bìa eBook 1600×2560 RGB |
| `cover_preview.jpg`, `cover_guides.png` | Xem nhanh; guides vẽ trim/safe/barcode (bật `cover.debug_guides`) |
| `preflight.md`, `preflight.json` | Kết quả kiểm tra: lỗi / cảnh báo / thông tin, kèm giá và khai báo AI |
| `interior_manifest.json` | Prompt, trang được nhận / bị loại và lý do, hash, bản đồ trang |
| `prompts.json`, `raw/`, `art/`, `pages/` | Trung gian: prompt, ảnh gốc, line art đã làm sạch, trang hoàn chỉnh |

## Nghiên cứu ngách — `kdp niche`

```bash
# Chấm điểm vài chủ đề bằng dữ liệu mẫu (offline), kèm concept cards cho 3 ngách tốt nhất
python -m kdp_studio niche run --topic "bold and easy flowers coloring book" --topic "cats coloring book for kids" --source fixture

# Mở rộng chủ đề thành 40 keyword (template + gợi ý tìm kiếm Amazon + Claude) rồi chấm điểm bằng Apify
python -m kdp_studio niche run --topic "bold and easy flowers" --expand --autocomplete --source apify --max-books 20

# Dùng file export của KDSpy / BookBeam / Publisher Rocket / Helium 10 (CSV hoặc JSON)
python -m kdp_studio niche run --source csv --csv exports/kdspy-flowers.csv --keyword "flowers coloring book"

# So sánh với lần chạy trước (xu hướng theo tuần) và xin thêm ý tưởng cho một keyword
python -m kdp_studio niche trends
python -m kdp_studio niche concepts --keyword "bold and easy flowers coloring book" --n 10
python -m kdp_studio niche expand --topic "flowers" --autocomplete
```

Kết quả trong `niches/`: `niche_report_latest.md` (bảng xếp hạng + chi tiết từng ngách + concept cards), `niches_<ts>.csv`, `run_<ts>.json`, và `niche_scout.sqlite` lưu mọi lần chạy để tính xu hướng.

| Nguồn `--source` | Dữ liệu | Cần gì | Ghi chú |
|---|---|---|---|
| `fixture` | Dữ liệu tổng hợp xác định | Không | Để chạy thử pipeline, test và demo |
| `csv` | Export từ extension/tool khác | File CSV/JSON | Tự nhận diện tên cột (ASIN, BSR, Ratings, Publication Date…) |
| `apify` | Actor `getascraper/kdp-book-niche-analyzer` (Kindle Store) | `APIFY_TOKEN`, ~$1/1.000 bản ghi | BSR là rank Kindle Store; có rating count |
| `creators` | Amazon Creators API (chính thức, Books) | Tài khoản Associates ≥ 10 sale/30 ngày, `CREATORS_CLIENT_ID/SECRET/PARTNER_TAG` | Không có rating count; 1 request/giây |

Chấm điểm (0–100, chỉ để **so sánh** các ngách với nhau): demand 0–40 từ median BSR của top 10 (thang log), competition ease 0–40 từ median số rating, tỉ lệ sách > 1000 rating, tỉ lệ nhà xuất bản độc lập và tỉ lệ sách ra trong 12 tháng, monetization 0–20 từ giá (ngưỡng $9.99). Kèm cờ cảnh báo: thương hiệu/IP trong tiêu đề, top 3 chiếm > 50% doanh số ước tính, không có người mới, giá ở bậc 50%. Ước tính BSR→doanh số chỉ là tương đối (các tool công khai lệch nhau tới 7 lần).

## Viết metadata — `kdp metadata`

```bash
# Sinh 5 bộ title/subtitle/mô tả HTML/7 keywords/3 categories từ brief, kiểm tra luật KDP, chấm rubric
python -m kdp_studio metadata generate --brief examples/bold-easy-flowers/brief.yaml

# Ghi bộ số 2 vào book.yaml (giữ nguyên chú thích nhờ ruamel.yaml; có file .bak)
python -m kdp_studio metadata apply --book examples/bold-easy-flowers/book.yaml --candidates examples/bold-easy-flowers/metadata/candidates.json --pick 2
```

`brief.yaml` ([ví dụ](examples/bold-easy-flowers/brief.yaml)) gồm: `niche_keyword`, `concept_title`, `angle`, `audience`, `differentiators`, `competitor_insights`, `must_include_terms`, `avoid_terms`, `series_name`, `reading_age`, `author`, `page_count`, `image_count`. Có Claude thì các ứng viên được sinh bằng structured output và tự sửa một lần nếu vi phạm luật; không có Claude thì dùng mẫu offline (vẫn qua được validator). Rubric: tuân thủ 40 điểm, keywords 15, title/subtitle 15, mô tả 15, categories 10, khớp brief 5. Kết quả: `metadata/candidates.md` để duyệt và `candidates.json` để apply.

## Truyện chữ — `kdp build` cho `type: story`, `kdp story`

```bash
# Build ví dụ: 6 chương Markdown -> interior.pdf (5x8, lề gương, chương mở trang lẻ) + .epub + bìa + preflight
python -m kdp_studio build examples/lantern-lane/book.yaml

# Kiểm tra lại EPUB (cấu trúc EPUB 3) và chạy Kindle Previewer nếu đã cài
python -m kdp_studio story check examples/lantern-lane/book.yaml

# Viết bản thảo bằng Claude: brief -> story bible -> outline -> từng chương (-> --polish biên tập lại)
python -m kdp_studio story draft --brief examples/lantern-lane/story_brief.yaml --out drafts/lantern-lane
```

Bản thảo là thư mục `manuscript/` với `chapters/*.md` (dòng `# Tiêu đề` đầu file là tên chương; `***` là ngắt cảnh; `--` thành gạch ngang dài; ngoặc kép thẳng thành ngoặc cong), tùy chọn `dedication.md`, `epigraph.md`, `about-author.md`, `also-by.md`, `review-cta.md`. Khối `interior` trong `book.yaml` ([ví dụ](examples/lantern-lane/book.yaml)) chọn font, cỡ chữ, lề, nhãn chương, front/back matter.

Những gì builder bảo đảm cho KDP: trang = trim (không bleed), gutter nâng tự động theo số trang (0.375"–0.875"), mọi font nhúng dạng TrueType subset (Helvetica mặc định của reportlab bị thay thế), chương bắt đầu trang lẻ với trang trống chèn tự động, running head và số trang không xuất hiện ở front matter/trang mở chương/trang trống, tổng số trang chẵn và ≥ 24 (chèn trang trống khi `pad_to_min_pages`). EPUB 3: `mimetype` đứng đầu không nén, OPF/nav/NCX, XHTML hợp lệ không entity, bìa `cover-image`; validator nội bộ kiểm tra đúng những lỗi KDP và epubcheck hay bắt. Không cần Pandoc, Typst hay Java.

## Theo dõi đối thủ — `kdp watch`

```bash
python -m kdp_studio watch add --asin B0XXXXXXXX --label "Competitor A" --niche "bold and easy flowers"
python -m kdp_studio watch add --asin B0YYYYYYYY --label "Our book" --ours
python -m kdp_studio watch snapshot --source creators     # hoặc apify | csv --csv export.csv | fixture
python -m kdp_studio watch report                         # BSR/giá/rating so với 7 và 30 ngày trước + cảnh báo
python -m kdp_studio watch insights --reviews reviews.txt # review (tự export) -> complaints/praise/requests -> differentiation brief
python -m kdp_studio watch covers covers/                 # palette (offline) + nhận xét style/thumbnail bằng Claude
```

Dữ liệu nằm trong `watch/` (watchlist.yaml, watch.sqlite, báo cáo). Cảnh báo mặc định: giảm giá ≥ 15%, BSR cải thiện ≥ 30% hoặc xấu đi ≥ 50% trong 7 ngày, tốc độ nhận rating ≥ 3/ngày. Module không scrape review Amazon; bạn tự export (copy từ trang sản phẩm hoặc extension) rồi đưa file text/JSON vào.

## Đưa sách lên KDP — `kdp publish` (bán tự động, có người giám sát)

KDP không có API, và điều khoản cấm bên thứ ba dùng tài khoản hay thao túng dịch vụ, nên module này cố tình **không** phải bot tự động. Những quy tắc được mã hóa cứng trong code:

- Trình duyệt luôn hiển thị (headless chỉ được chấp nhận với trang mock cục bộ khi chạy test); dùng Edge hoặc Chrome đã có trên máy với một profile riêng (`%LOCALAPPDATA%/kdp-studio/browser-profile`, không bao giờ commit).
- Tool không gõ mật khẩu, không nhập OTP, không đụng CAPTCHA: gặp trang đăng nhập hay thử thách là dừng chờ bạn.
- Mỗi tab KDP (Details → Content → Pricing) được điền từ `book.yaml` rồi **dừng** để bạn xem; chỉ khi bạn nhấn Enter tool mới bấm "Save and Continue". Previewer bạn tự mở và tự duyệt.
- Tool **không bao giờ bấm Publish**. Bạn bấm, rồi gõ `p` để ghi nhận.
- Trước khi mở trình duyệt: kiểm tra file build, preflight PASS, quota tuần (2 tựa/định dạng, reset Chủ nhật 00:00 UTC) và tựa chưa từng nộp. KDP đếm cả bản nháp (xác nhận trên tài khoản thật 2026-10-23: hộp thoại "Title creation limit reached" hiện ngay khi Save and Continue ở Details); tool nhận ra hộp thoại đó (trạng thái `blocked`), tựa tạo tay ghi bằng `publish quota --add-created`, và `--resume-url` cho phép điền tiếp một bản nháp đã có mà không tốn lượt tạo.
- Mỗi lần chạy lưu `publishing/runs/<ts>-<id>-<fmt>/` gồm checklist, ảnh chụp từng bước và `flow.json` (đã điền gì, còn gì phải nhập tay).

```bash
python -m kdp_studio publish checklist examples/bold-easy-flowers/book.yaml --format paperback   # tờ nhập tay đầy đủ, kể cả khi không dùng trình duyệt
python -m kdp_studio publish quota                                                               # còn bao nhiêu lượt tạo/nộp tuần này
python -m kdp_studio publish queue add examples/bold-easy-flowers/book.yaml --format paperback --priority 1
python -m kdp_studio publish next                                                                # chạy tựa kế tiếp còn quota
python -m kdp_studio publish run examples/bold-easy-flowers/book.yaml --format paperback         # chạy trực tiếp một cuốn
python -m kdp_studio publish mark examples/bold-easy-flowers/book.yaml --format paperback --status live --asin B0XXXXXXXX
python -m kdp_studio publish probe                                                               # mở KDP, xem selector nào còn khớp khi Amazon đổi giao diện
python -m kdp_studio publish probe --auto --url "https://kdp.amazon.com/en_US/print-setup/paperback/<ID>/content" --follow "Rights & Pricing"   # probe đúng một trang rồi thoát
python -m kdp_studio publish selectors --out kdp_selectors.yaml                                  # ghi selector mặc định ra để chỉnh, dùng với --selectors
python -m kdp_studio publish diagnose-cover --message "Your expected cover size is 12.313x9.250 but the submitted file size is 10.320x8.250" --pages 28 --book book.yaml   # giải mã lỗi bìa của Previewer ra trim/giấy/gáy
```

Bộ selector mặc định đã được đối chiếu với tài khoản KDP thật (paperback, 2026-10-23) trên cả ba tab: Details còn dùng id `data-print-book-*` và CKEditor cho mô tả; Content và Rights & Pricing là giao diện React mới — radio theo `name`/`value`, combobox ARIA cho Trim Size, AI và Primary marketplace, checkbox ARIA chỉ nhận diện bằng `aria-label` (cột Amazon / Expanded Distribution), ô giá `#price-input-<currency>` kèm nút "Base this price on Amazon.com" mà tool chỉ bấm cho ô KDP bỏ trống. Luồng eBook mới chạy trên mock. Amazon đổi DOM không báo trước: khi lệch, chạy `probe` (hoặc `probe --auto --follow`) rồi chỉnh file YAML. Field nào không điền được sẽ được liệt kê để bạn nhập tay; categories luôn chọn tay trong hộp thoại của KDP. Luồng điền được test trên bản mock của ba trang KDP (`tests/mock_kdp/`, dựng theo đúng cấu trúc đã probe).

## Sau xuất bản — `kdp monitor`

```bash
python -m kdp_studio monitor check                                          # trạng thái từng tựa so với mốc KDP (3 ngày duyệt, 72h sửa title)
python -m kdp_studio monitor ads --csv ads-export.csv --book examples/bold-easy-flowers/book.yaml   # ACOS so với break-even = royalty / giá bìa
python -m kdp_studio monitor sales --file kdp-royalties.csv --since 2026-10-01                     # báo cáo royalty KDP (CSV; XLSX cần openpyxl)
python -m kdp_studio monitor report --ads ads-export.csv --sales kdp-royalties.csv                 # gộp: tựa, quota, ASIN của mình (từ competitor-watch), ads, doanh thu
```

Khi `publish mark --status live --asin` được gọi, ASIN được thêm vào watchlist với `ours: true`, nên `kdp watch snapshot` theo dõi luôn sách của bạn và `monitor report` hiển thị BSR/giá/rating cùng cảnh báo.

## book.yaml

Xem [examples/bold-easy-flowers/book.yaml](examples/bold-easy-flowers/book.yaml) (tô màu) và [examples/lantern-lane/book.yaml](examples/lantern-lane/book.yaml) (truyện) có chú thích đầy đủ. Các khối chính:

- `metadata` — title, subtitle, author, `description_html`, 7 `keywords`, 3 `categories`, `reading_age`, `low_content` (phải `false` với sách tô màu).
- `print` — `trim` (16 cỡ KDP), `paper` (`white_bw`, `cream_bw`, `groundwood_bw`, `standard_color`, `premium_color`), `bleed`, `isbn`.
- `interior` (type `coloring`) — `theme`, `audience`, số `images`, in một mặt (`single_sided`), front/back matter, `source.provider` (`placeholder` | `folder` | `openai`), `cleanup`, `dedupe`, `qa`, `prompts_with_claude`.
- `interior` (type `story`) — `manuscript_dir`, `chapters_glob`, `body_font`, `font_size_pt`, `leading`, `margins`, `chapter_start_recto`, `running_heads`, `chapter_label`, front/back matter, `pad_to_min_pages`, `min_words`, `epub`, `kindle_previewer`.
- `cover` — `art.provider` (`placeholder` | `file` | `openai`), `palette`, font, `back_blurb`, `back_bullets`, `spine_text`, `barcode_box`.
- `pricing` — `list_price` trên amazon.com, `ebook_list_price`, `expanded_distribution` (paperback), `kdp_select` (eBook).
- `provenance` — ai/cái gì tạo text, ảnh ruột, ảnh bìa → tool tự suy ra câu trả lời cho mục **AI-Generated Content** của KDP.

## Luật KDP đã mã hóa

Nguồn là trang trợ giúp KDP (lấy ngày 23/10/2026, link trong docstring từng module).

| Hạng mục | Quy tắc | Nơi kiểm |
|---|---|---|
| Trang ruột | trim + 0.125" bleed ngoài, cao + 0.25"; 24 trang tối thiểu; chẵn; trong khoảng cho phép theo trim/giấy | `specs.py`, `preflight/pdf_checks.py` |
| Lề | gutter 0.375"–0.875" theo số trang; lề ngoài ≥ 0.25" (không bleed) / 0.375" (có bleed) | `interior/pagegeom.py` |
| Ảnh | ≥ 300 DPI, nét ≥ 0.75 pt (3 px), không transparency, grayscale cho sách mực đen | `interior/cleanup.py`, preflight |
| Font | mọi font phải nhúng; reportlab Helvetica mặc định bị thay bằng TTF nhúng | `interior/layout.py`, preflight |
| Bìa | rộng = 2×bleed + 2×trim + spine; spine = trang × 0.002252 (white) / 0.0025 (cream) / 0.002347 (premium color); chữ gáy chỉ khi ≥ 79 trang; CMYK; vùng barcode 2"×1.2" góc dưới phải mặt sau | `cover/geometry.py`, `cover/render.py` |
| Bìa eBook | 1600×2560, tỉ lệ ≥ 1.6:1, RGB, JPEG, < 50 MB | preflight |
| Metadata | title+subtitle < 200 ký tự; cấm "bestselling", "free", lặp từ chung; mô tả không URL/email/review/giá; ≤ 7 keyword 2–3 từ; ≤ 3 category; reading age khi vào Children's | `metadata_rules.py` |
| Giá | chi phí in theo bảng amazon.com; royalty 60% khi ≥ $9.99, 50% dưới đó; giá sàn; cảnh báo khi đang ở bậc 50% | `pricing.py` |
| Nội dung | khai báo AI theo provenance; phát hiện trang trùng/gần trùng trong sách và xuyên catalog | `schema.py`, `interior/dedupe.py` |
| Xuất bản | nhắc giới hạn 2 tựa mới / định dạng / tuần | preflight |

### Phát hiện trùng lặp

KDP gỡ sách có nội dung "excessively reused, recycled, or repeated within or across books". pHash đơn thuần không hợp với line art thưa nét (ảnh khác nhau có thể cách nhau 2 bit, ảnh dịch chuyển có thể cách 20+ bit), nên mỗi trang được mô tả bằng pHash + dHash trên bounding box của nét vẽ và bản đồ mật độ mực 32×32. Trùng khi **cả** khoảng cách pHash ≤ `max_distance` (mặc định 6) **và** tương quan mật độ ≥ `min_correlation` (0.985). Đo trên 40 trang placeholder cố tình giống nhau: báo trùng sai 0.8% cặp; bắt được 100% bản sao y nguyên / JPEG nén lại / dịch chuyển nhỏ, khoảng 60% bản sao co giãn. Thư viện hash lưu ở `library/image_hashes.json` (commit vào git để mang theo giữa các máy).

## Dùng AI thật

- **Prompt đa dạng theo chủ đề**: `interior.prompts_with_claude: true` + `ANTHROPIC_API_KEY` (hoặc `ant auth login`). Model mặc định `claude-opus-5-5`, structured output qua `client.messages.parse`.
- **Niche & metadata**: `kdp niche run` và `kdp metadata generate` tự dùng Claude khi có credential (mở rộng keyword, concept cards, sinh và sửa metadata); thêm `--no-claude` để chạy hoàn toàn offline.
- **QA thị giác từng trang**: `interior.qa.claude: true`. Mỗi trang được chấm: line art sạch, có chữ rác, mảng đen lớn, lỗi hình, rủi ro IP, phù hợp tuổi.
- **Sinh ảnh**: `interior.source.provider` và `cover.art.provider` nhận `openai` (gpt-image-1, `OPENAI_API_KEY`), `google` (Imagen 4 qua Gemini API, `GEMINI_API_KEY`) hoặc `stability` (Stable Image core/ultra/sd3, `STABILITY_API_KEY`). Key đặt trong file `.env` ở thư mục dự án (đã gitignore, xem `.env.example`) hoặc biến môi trường; `kdp keys` cho biết key nào đang có. Thử trước vài trang với `kdp image-test examples/bold-easy-flowers/book.yaml --n 3 --provider openai`: ảnh gốc và ảnh đã làm sạch nằm cạnh nhau trong `build/image-test/contact_sheet.png`, kèm QA và ước tính chi phí. Ba provider viết theo tài liệu công khai và chưa chạy với key thật trong repo này. Hoặc sinh ảnh bằng ComfyUI/Midjourney rồi dùng `provider: folder`.
- **Nguồn miễn phí**: `provider: spec` không cần model hay key: Claude (hoặc bạn) viết bản vẽ vector dạng JSON (đường tròn, cung, đường cong trơn, cánh hoa, lặp đối xứng) trong `drawings/`, tool tô nét dày thành trang tô màu sắc nét ở mọi DPI; xem `examples/bold-easy-flowers/drawings/` và `kdp draw-preview <thư mục>`. Hợp với mandala, hoa văn, hình khối to kiểu "bold & easy". `provider: pollinations` (FLUX, không key) chạy được nhưng ở mức ẩn danh cho ảnh nhỏ 630×940, có watermark và nhiều mảng đen, 3/3 trang thử bị QA loại (2026-10-24); `provider: cloudflare` (Workers AI, tài khoản Cloudflare miễn phí) chưa thử. Máy có GPU 4 GB có thể chạy Stable Diffusion 1.5 + LoRA coloring-book cục bộ qua `provider: folder` (chưa tích hợp trực tiếp).
- Mọi ảnh do model sinh ra là **AI-generated** theo định nghĩa KDP, kể cả khi đã chỉnh sửa nhiều → đặt `provenance` đúng.

## Giới hạn hiện tại

- Ruột truyện chưa có mục lục in (EPUB có nav TOC), chưa hyphenation, chưa hỗ trợ ảnh minh họa trong chương.
- Kindle Previewer chỉ chạy khi bạn cài sẵn; không có thì bước này báo info và bỏ qua.
- `kdp story draft` cần Claude; không có fallback offline cho việc viết truyện.
- Chưa render bìa hardcover (case laminate) — dùng KDP cover calculator.
- Chuyển RGB → CMYK bằng Pillow (không ICC profile); màu in có thể lệch nhẹ so với màn hình.
- Upscale bằng LANCZOS + re-threshold; chưa tích hợp Real-ESRGAN.
- Ước lượng DPI trong preflight giả định ảnh trải hết chiều rộng trang.
- `kdp publish run`: đã chạy trọn vẹn trên tài khoản thật cho cả paperback (2026-10-23/24) và eBook (2026-10-24), đều kết thúc Save as Draft. Selector của 6 tab (Details/Content/Pricing × 2 định dạng), trang /create và hộp thoại category đã đối chiếu với DOM thật; mỗi lần chạy ghi `run/dom/dom-<tab>.json` để chỉnh khi Amazon đổi giao diện. Ở cổng cuối: `s` = tool bấm Save as Draft, `f` = điền lại Pricing, `p` = bạn đã bấm Publish, `d` = bạn đã tự lưu nháp, `q` = dừng. Tool chủ ý không tự bấm Publish và không có chế độ chạy không người. Phần điền giá eBook và khối AI eBook mới được sửa sau lần chạy, chưa chạy lại để xác nhận.
- `monitor ads`/`monitor sales` đọc file export bạn tải về; không có API cho Ads/Reports của KDP.
- Nguồn `apify` và `creators` được viết theo tài liệu công khai nhưng chưa chạy với credential thật trong repo này; nguồn `csv` và `fixture` đã test. Chưa có Keepa và Google Trends.
- Danh sách categories là gợi ý thường gặp; luôn xác nhận lại trong màn hình chọn category của KDP.

## Lộ trình

1. **Giai đoạn 0 (xong)**: schema, interior-forge tô màu, cover-forge, preflight. Upload thủ công 2 cuốn để Amazon xác nhận file chuẩn.
2. **Giai đoạn 1 (xong)**: `niche-scout` (fixture / CSV / Apify / Creators API, chấm điểm, xu hướng, concept cards) + `metadata-writer` (brief → ứng viên → validator → rubric → apply).
3. **Giai đoạn 2 (xong)**: pipeline truyện chữ (Markdown → EPUB 3 + PDF in bằng Python thuần, Kindle Previewer tùy chọn, draft bằng Claude) + `competitor-watch` (snapshot ASIN, báo cáo xu hướng và cảnh báo, khai thác review, phân tích bìa).
4. **Giai đoạn 3 (xong)**: `assisted-publisher` (Playwright trên Edge/Chrome của bạn, human-in-the-loop, hàng đợi theo quota tuần, checklist, probe selector) + `monitor` (trạng thái tựa, ASIN của mình qua competitor-watch, Amazon Ads CSV, royalty KDP).
5. **Tiếp theo**: chạy `publish run` trọn vẹn trên tài khoản thật (selector đã chốt) và probe luồng eBook; dashboard web gộp các báo cáo; Keepa/Google Trends cho niche-scout; Real-ESRGAN và ICC CMYK cho sách tô màu.

## Cấu trúc

```
kdp_studio/
  schema.py          book.yaml (pydantic) + suy ra khai báo AI
  specs.py           thông số KDP: trim, trang, lề, spine, bìa eBook
  pricing.py         chi phí in, royalty, giá sàn
  metadata_rules.py  luật metadata KDP
  fonts.py           tìm TTF, fallback Vera (reportlab) cho mọi hệ điều hành
  llm.py             wrapper Anthropic SDK (structured output, fallback khi lỗi)
  interior/          pagegeom, prompts, generate (providers), cleanup, dedupe, qa, layout, pipeline
  cover/             geometry, text, render
  preflight/         pdf_checks (pypdf), run (báo cáo)
  niche/             models, keywords, autocomplete, scoring, phrases, concepts, store (SQLite), report, pipeline
  niche/sources/     fixture, csv_source, apify, creators
  metadata/          brief, categories, generate (Claude/template + repair), score (rubric), apply (ruamel), report
  story/             manuscript (Markdown), epub (builder + validator), print_pdf (Platypus), draft (Claude), kindle_previewer, pipeline
  watch/             models (watchlist), store (SQLite), sources (fixture/csv/creators/apify), report, insights, covers, pipeline
  publish/           quota (tuần KDP), store (events/titles/queue), checklist, selectors, browser (Playwright có rào chắn), flow (3 bước + cổng duyệt), pipeline
  monitor/           status (mốc KDP), ads (CSV Amazon Ads), sales (royalty KDP), report
  cli.py             validate | build | preflight | price | cover-size | niche … | metadata … | story … | watch … | publish … | monitor …
examples/            bold-easy-flowers (tô màu), lantern-lane (truyện, 6 chương), watchlist.yaml, reviews-sample.txt
tests/mock_kdp/      ba trang KDP giả lập (details, content, pricing) để test luồng publish không cần tài khoản
library/             thư viện hash chống trùng xuyên sách
docs/                báo cáo nghiên cứu KDP & kiến trúc bộ công cụ
tests/               unit + end-to-end (build thật 10 trang rồi preflight)
```
