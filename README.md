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

# Viết bản thảo: brief -> story bible -> outline -> từng chương (-> --polish biên tập lại). Claude khi có ANTHROPIC_API_KEY,
# không thì Llama 3.3 trên Cloudflare Workers AI (miễn phí, cùng key với vẽ ảnh); PROVENANCE.md ghi lại engine đã dùng
python -m kdp_studio story draft --brief examples/lantern-lane/story_brief.yaml --out drafts/lantern-lane
```

Bản thảo là thư mục `manuscript/` với `chapters/*.md` (dòng `# Tiêu đề` đầu file là tên chương; `***` là ngắt cảnh; `--` thành gạch ngang dài; ngoặc kép thẳng thành ngoặc cong), tùy chọn `dedication.md`, `epigraph.md`, `about-author.md`, `also-by.md`, `review-cta.md`. Khối `interior` trong `book.yaml` ([ví dụ](examples/lantern-lane/book.yaml)) chọn font, cỡ chữ, lề, nhãn chương, front/back matter.

**Tạo truyện chữ từ giao diện (2026-10-25).** Trang **Tạo sách** có hai tab: *Sách tô màu* và *Truyện chữ + eBook*. Tab truyện hỏi thư mục, tiêu đề, bút danh, thể loại, tiền đề, bối cảnh, giọng văn, số chương, số từ mỗi chương, khổ in (5x8 … 6x9), giá in và giá eBook, từ khoá và dàn ý (mỗi dòng một chương `Tên chương: chuyện gì xảy ra`); **Gợi ý điền tất cả** hoàn thiện các ô còn trống cho khớp nhau (Claude → Cloudflare Workers AI → mẫu có sẵn, `kind=story` trên cùng route `/create/suggest`). **Tạo** sinh `book.yaml` (`type: story`, `formats: [paperback, ebook]`, `pricing.ebook_list_price`, category theo thể loại, `provenance.text: ai_generated` kèm tên công cụ để khai báo với KDP, hoặc `human` khi bạn tự viết), `story_brief.yaml` cho `kdp story draft` và một file Markdown mỗi chương chứa dòng dàn ý (`bookgen.new_story_book`). Trên trang sách, **Viết nháp các chương** chạy `kdp story draft` nền với log và thanh tiến trình (số chương đã có nội dung, số từ, chương mới nhất); các khung chương chưa viết được thay bằng chương AI viết, file bạn viết tay giữ nguyên. Sau đó Build như mọi truyện chữ: `interior.pdf`, `.epub`, bìa, preflight; hàng đợi đăng điền paperback rồi eBook.

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

## Giao diện web — `kdp ui`

```bash
python -m kdp_studio ui                     # mở http://127.0.0.1:8765 : sách, build, image-test, hàng đợi, lần chạy, quota, key, license
python -m kdp_studio ui --books "D:\sach"   # quét thêm thư mục chứa <cuốn>/book.yaml
```

Trang **Cài đặt** quản lý API key của các nền tảng (Cloudflare, OpenAI, Gemini, Stability, pollinations, Anthropic, Hugging Face): ghi vào `.env`, chỉ hiện đầu và cuối key, nút **Kiểm tra** gọi một lệnh rẻ để biết key có dùng được (Stability còn hiện số credit), kèm hướng dẫn từng bước và link lấy key; dòng lệnh tương đương `kdp keys --check` và `kdp keys --set TEN=gia_tri`. Trang **Tạo sách** sinh `book.yaml` mới trong `books/<thư mục>/` từ một form ngắn (tiêu đề, tác giả, chủ đề, số trang, khổ, nguồn ảnh, chủ đề từng trang) rồi đưa tới trang sách; nút **Gợi ý điền tất cả** ở cuối form hoàn thiện mọi ô còn trống cho khớp với những gì đã gõ (tiêu đề, phụ đề, bút danh, theme, 7 từ khoá ≤ 50 ký tự, đủ số chủ đề từng trang và không có người) — qua Claude nếu có `ANTHROPIC_API_KEY`, không thì model văn bản của Cloudflare Workers AI (cùng key vẽ ảnh), không có key nào thì thư viện 20 ngách trong `kdp_studio/themes.py` (gõ sai chính tả như `ocenan` vẫn ra ocean animals); tick *ghi đè cả ô đã điền* để viết lại cả ô đã có; ô **Tiến trình tạo ruột** trên trang sách hiện số trang đã xong trên tổng, số lần sinh lại, giây mỗi trang, ảnh thu nhỏ các trang mới nhất và liên kết PDF, cập nhật 4 giây một lần với bất kỳ build nào đang chạy. Trang **Sách** có nút **Mở** và **Thư mục** (mở Explorer tại thư mục sách) cho từng cuốn, và thẻ **Thư mục sách** để nạp sách có sẵn từ thư mục bất kỳ: gõ đường dẫn hoặc bấm *Chọn thư mục…* (hộp thoại chọn thư mục của Windows); thư mục có `book.yaml` trực tiếp hoặc chứa nhiều thư mục sách đều được, danh sách nhớ trong `state/book_dirs.json` nên lần mở sau vẫn còn, và sách nạp vào dùng được mọi chức năng kể cả Hàng đợi và publish. Trang job của một lần Build hiện thanh tiến độ, số trang đã xong, giây mỗi trang và ảnh thu nhỏ ngay trên log; log cũng in một dòng `page 7/30 done in 81 s` sau mỗi trang và một dòng tổng kết cuối cùng. Trang **Hàng đợi** cho phép tick nhiều cuốn, chọn định dạng và ưu tiên rồi "Chạy tựa kế tiếp còn quota": tool mở một cửa sổ console chạy `kdp publish next` để các cổng duyệt (Details, Content, Pricing) vẫn hiện cho bạn như khi chạy tay. Build và image-test chạy nền với log trực tiếp trong trình duyệt.

## Bìa và trang đầu kiểu sách bán chạy (2026-10-25)

Đối chiếu với các bìa đứng đầu nhóm coloring book trên Amazon (ví dụ dòng 100 Flowers / 100 Bold and Easy của Jade Summer): nền đơn sắc (đen hoặc pastel), một tranh màu dạng sticker có viền trắng chiếm 2/3 trên, tiêu đề chữ display rất lớn, phụ đề chữ condensed màu nhấn, tên tác giả chữ script, bìa sau có trang mẫu. `cover.layout: poster` (mặc định cho sách mới) dựng đúng cấu trúc đó; `theme: midnight | pastel | cream` là bộ màu sẵn, ghi đè từng màu trong `palette`; `badge: "30 designs"` thêm huy hiệu tròn; bìa sau hiện `sample_pages` trang ruột trong thẻ trắng cùng blurb, gạch đầu dòng và ô barcode. Font đóng gói sẵn trong `kdp_studio/assets/fonts/` (Anton, Bebas Neue, Luckiest Guy, Pacifico, Great Vibes, Poppins — giấy phép OFL/Apache kèm theo), gọi bằng tên ngắn: `title_font: anton`, `subtitle_font: bebas`, `author_font: pacifico`. Tranh bìa: `art.provider: colorize` tô màu phẳng chính một trang ruột đã build (`page: 2`, màu chọn theo cụm lân cận nên mỗi bông hoa 1–2 màu, vùng thon dài thành lá xanh), `local`/`auto`/`cloudflare` để model vẽ tranh màu riêng theo prompt sticker, `file` để dùng ảnh của bạn; `sticker: true` tách tranh khỏi nền trắng, thêm viền trắng và bóng mờ. Trang tiêu đề ruột có khung bo góc, tiêu đề chữ display, phụ đề condensed, tác giả chữ script; trang "This book belongs to" có khung. `--skip-interior --pages N` dựng riêng bìa trong vài giây để thử màu.

## Vẽ trang trực tiếp bằng Claude (vector spec) và chi phí token (2026-10-25)

`provider: spec` không dùng model ảnh: mỗi trang là một file JSON trong `drawings/` mô tả hình (circle, ellipse, arc, line, curve, bezier, polygon, petal, dot, repeat, mirror; xem `kdp_studio/interior/vector.py`) và tool rasterize thành nét đen đều trên nền trắng, rồi đi qua cleanup/QA như mọi trang khác (bộ lọc người/chữ được bỏ qua vì không có model vẽ). Claude viết spec rất ổn với hoa, đồ vật, hoa văn; `books/flowers-vector` là cuốn flowers vẽ lại kiểu này: `make_specs.py` ghép 30 trang từ một thư viện nhỏ (vòng cánh, thân, lá, chậu, nơ, chuông, bèo) và ghi `drawings/*.json`; `kdp draw-preview books/flowers-vector/drawings` để xem, `kdp build` để ra sách. Khai báo với KDP: `provenance.interior_images: ai_generated`, công cụ "Claude (vector drawing specs)".

Chi phí khi gọi qua API (đo trên 30 spec của cuốn flowers: 865–7.023 ký tự, trung bình 2.656 ≈ 850–950 token đầu ra mỗi trang, trang nhiều chi tiết ≈ 2.500; đầu vào ≈ 800 token gồm hướng dẫn, mô tả lược đồ và chủ đề):

| Model | Giá (vào / ra, mỗi triệu token) | Một trang | 30 trang |
|---|---|---|---|
| Claude Opus 5.5 | $4 / $20 | ≈ $0,02 | ≈ $0,65 |
| Claude Sonnet 5.5 | $2 / $10 | ≈ $0,01 | ≈ $0,33 |
| Claude Haiku 5.5 | $0,10 / $0,50 | ≈ $0,0005 | ≈ $0,02 |

Các model này bật suy nghĩ (thinking) mặc định, có thể thêm 1.000–3.000 token đầu ra mỗi trang, tức tối đa gấp 2–3 lần số trên. Cần `ANTHROPIC_API_KEY` ở Cài đặt; chưa có key thì vẫn có thể nhờ Claude trong chat viết spec rồi chép vào `drawings/`, đúng như cuốn flowers-vector.

**Vẽ bằng lệnh `claude` (Claude Code CLI), không cần API key.** Máy nào đã cài Claude Code và đăng nhập thì tool gọi `claude -p` (headless) bằng gói Claude đang dùng: `kdp draw books/x/book.yaml [--pages 1-5,8] [--model sonnet|opus|haiku] [--overwrite] [--set-provider]`, hoặc nút **Vẽ trang bằng Claude** trên trang sách. Mỗi trang là một lần gọi với system prompt riêng, tắt tool, tắt file cài đặt và MCP (`--tools "" --setting-sources "" --strict-mcp-config`) nên ngữ cảnh chỉ khoảng 1.100 token; prompt đi qua stdin, kết quả đọc từ phong bì JSON (`usage`, `total_cost_usd`, `structured_output`), chạy được cả từ trong một phiên Claude Code. Spec về được kiểm tra (hợp lệ, trong khung, đủ lớn, mực 1,5–35 %), sai thì gửi lại kèm lý do một lần, rồi ghi `drawings/NNN_slug.json`; `drawings/_draw_log.json` lưu token vào/ra, token suy nghĩ, chi phí niêm yết và thời gian từng trang. `--set-provider` sửa `interior.source` sang `spec` và khai báo `provenance` ngay trong book.yaml (giữ nguyên comment). Thứ tự engine cho mọi bước gọi LLM (gợi ý, viết truyện, metadata) giờ là: Anthropic API khi có key → lệnh `claude` → Cloudflare Workers AI → mẫu có sẵn (`KDP_STUDIO_SUGGEST=cli` để ép; `KDP_STUDIO_NO_CLAUDE_CLI=1` để tắt; `KDP_STUDIO_CLI_MODEL` chọn model). `kdp doctor` có dòng "claude CLI".

**Engine OpenAI-compatible (`--engine compat`): Oxion AI, OpenRouter, Groq, Together, Ollama...** Ba biến ở Cài đặt (mục "OpenAI-compatible API"): `OPENAI_COMPAT_BASE_URL` (ví dụ `https://oxionai.com/v1`), `OPENAI_COMPAT_API_KEY` (bỏ trống với server local) và `OPENAI_COMPAT_MODEL` (đúng id trong `/models` của dịch vụ); nút Kiểm tra gọi `GET /models`. Tool chỉ dùng `POST /chat/completions`: xin JSON mode, server nào từ chối thì tự bỏ; gặp 429/502/503/504 thì chờ 5, 15, 30 giây rồi gọi lại; token đọc từ `usage`, giá lấy từ `/models/{id}` khi dịch vụ công bố (Oxion, OpenRouter) hoặc `OPENAI_COMPAT_PRICE_IN/_OUT` (USD mỗi triệu token), không có thì ghi 0. Dùng được ở `kdp draw --engine compat`, nút Vẽ, gợi ý (`KDP_STUDIO_SUGGEST=compat`), `kdp story draft --engine compat` và mọi bước LLM khác: thứ tự tự động là Anthropic API → lệnh `claude` → OpenAI-compatible → Cloudflare, hoặc ép một engine bằng `KDP_STUDIO_LLM=compat`. Khai báo KDP: `--set-provider` ghi tên model kèm "via" vào `provenance.ai_tools`. Oxion AI (đọc 10/2026): cổng API ẩn danh ra mắt 8/2026, 33 model chữ, free 0,5 triệu token/tháng, gói từ 3,50 USD/50 triệu token, không có tạo ảnh; nên thử free tier và kiểm tra model trả lời có đúng danh tính trước khi tin.

**Engine Gemini (`--engine gemini`, ô Engine trên trang sách).** Cùng cách vẽ vector nhưng gọi Gemini API (`GEMINI_API_KEY` ở Cài đặt, mục Google), model mặc định `gemini-2.5-flash` (đổi bằng `--model` hoặc `KDP_STUDIO_GEMINI_MODEL`; `gemini-2.5-pro` đã đóng với người dùng mới, 10/2026). Các model chữ Gemini Flash có free tier nên không tốn tiền; log vẫn ghi giá niêm yết: đo trên cuốn flowers với `gemini-2.5-flash` mỗi trang ≈ 670 token vào và 5.000–12.000 token ra (phần lớn là suy nghĩ), ≈ $0,02 niêm yết, 25–50 giây. Chất lượng bản vẽ của 2.5 Flash kém Claude rõ rệt (hình thô, hay dùng chấm đen to làm nhụy, bố cục lệch), nên bộ kiểm tra spec từ chối chấm đen bán kính quá 3 % khung và gửi lại lý do. Với `gemini-3.8-flash` (free tier) chất lượng gần Claude nhưng 2–4 phút mỗi trang vì hàng đợi, ≈ 400 token vào và 2.500 ra, ≈ $0,01 niêm yết; cả hai model đều chạm hạn mức ngày của free tier (429) sau 16–19 trang, chạy lại hôm sau với cùng lệnh thì tool bỏ qua trang đã có và vẽ nốt. Cũng cùng key đó, `interior.source.provider: google` với `model: gemini-2.5-flash-image` hoặc `gemini-3.1-flash-image` vẽ ảnh raster qua Gemini (không free tier, ≈ $0,04–0,07 mỗi ảnh), chưa thử được vì key hiện không có hạn mức ảnh.

## Nhiều tài khoản, nhiều API và tự chuyển khi hết quota

Mỗi nền tảng có thể có nhiều tài khoản: cùng tên biến với đuôi `_2`, `_3`… (`CF_ACCOUNT_ID_2`/`CF_API_TOKEN_2`, `OPENAI_API_KEY_2`…), thêm bằng nút **Thêm tài khoản dự phòng** ở Cài đặt hoặc `kdp keys --set CF_API_TOKEN_2=...`. Khi build, tool tự xoay giữa các tài khoản của nền tảng đang chọn; nguồn ảnh `auto` còn xoay giữa các nền tảng theo **chuỗi dự phòng**: mặc định mọi tài khoản Cloudflare rồi GPU cục bộ (nếu đã cài), hoặc thứ tự bạn ghi trong `KDP_STUDIO_PROVIDER_CHAIN=cloudflare, cloudflare#2, local, openai` (nguồn trả tiền chỉ được dùng khi bạn tự ghi vào chuỗi; trong `book.yaml` có thể đặt `source.chain` riêng cho một cuốn). Gặp HTTP 429/402 (hết quota, hết tiền) hay 401/403 (key bị từ chối), tool khóa tài khoản đó trong `state/provider_state.json` đến giờ quota quay lại (Cloudflare: 00:00 UTC; rate limit thường: 1 giờ; hết tiền hay key hỏng: 24 giờ), chuyển ngay sang thành viên kế tiếp và làm tiếp trang đang dở; lỗi kiểm duyệt prompt (400) chỉ tốn một lượt sinh lại, không đổi tài khoản. `interior_manifest.json` ghi `providers_used` và `provider_chain`; trang Cài đặt hiện trạng thái từng tài khoản (sẵn sàng / tạm khóa đến mấy giờ, số ảnh hôm nay) kèm nút **Mở khóa**; `kdp keys` in cùng thông tin. Nút Gợi ý ở trang Tạo sách cũng xoay qua các tài khoản Cloudflare như vậy.

Quota Cloudflare tính ra bao nhiêu ảnh: 10.000 neuron/ngày cho mỗi tài khoản; FLUX.1 schnell tính 4,8 neuron mỗi ô 512×512 cộng 9,6 neuron mỗi bước *trên mỗi ô* (đo 2026-10-24: khoảng 40 ảnh 1024² ở 6 bước làm hết quota, khớp ~250 neuron/ảnh). Tool giờ dùng 4 bước, mức schnell được thiết kế: ~173 neuron/ảnh → khoảng 55 ảnh/ngày/tài khoản, đủ một cuốn 30 trang kể cả sinh lại. Lập nhiều tài khoản của cùng một người để nhân hạn mức miễn phí có thể vi phạm điều khoản Cloudflare và bị khóa; khi cần nhiều hơn, gói Workers Paid (5 USD/tháng) tính 0,011 USD mỗi 1.000 neuron, tức khoảng 0,002 USD một ảnh, hoặc để chuỗi rơi sang GPU cục bộ.

## Bản EXE dùng thử và key dùng thử

`build_exe.ps1` (PyInstaller) tạo `dist/kdp-studio/kdp-studio.exe` cùng thư mục kèm và `dist/kdp-studio-<version>-win64.zip`: máy nhận không cần cài Python, bấm đúp là mở giao diện; dữ liệu (sách, `.env`, state, publishing) nằm trong `Documents\kdp-studio` (hoặc `KDP_STUDIO_HOME`), lần đầu chạy được chép sẵn sách mẫu. Bản EXE không kèm model GPU cục bộ và bộ lọc OWLv2 (quá nặng); phần đăng KDP dùng Edge/Chrome có sẵn trên máy. Key dùng thử cho mọi máy: `kdp license issue --key <license_private.pem> --to "Ban dung thu" --machine "*" --days 30` (verify chấp nhận `machine: "*"`); kèm `README-DUNG-THU.md` hướng dẫn người thử và xin góp ý. `kdp doctor` kiểm tra máy đích; `start.bat`/`install.ps1`/`package.ps1` là đường cài từ mã nguồn khi cần GPU.

## Chuyển sang máy khác và license

1. Trên máy đích cài Python 3.11+ rồi chạy `install.ps1` (thêm `-UI` cho giao diện web, `-Local` cho model ảnh cục bộ). Script cài gói ở chế độ người dùng, tạo `.env` từ `.env.example`.
2. Máy đích chạy `python -m kdp_studio license machine-id` và gửi mã cho bạn.
3. Bạn (chủ) cấp key bằng khoá riêng nằm ngoài repo: `python -m kdp_studio license issue --key <thư mục>/license_private.pem --to "Tên" --machine <mã máy> --days 365`.
4. Máy đích kích hoạt: `python -m kdp_studio license activate <key>` (hoặc dán vào trang License của giao diện web). Thiếu key hợp lệ, mọi lệnh ngoài `license` đều từ chối chạy.

Khoá công khai nằm trong `kdp_studio/license_pub.py` (tạo bằng `kdp license keygen`, đã commit); khoá riêng chỉ ở máy chủ sở hữu. Máy của chủ đặt `KDP_STUDIO_DEV=1` trong `.env` để bỏ qua kiểm tra. Đây là cơ chế chữ ký Ed25519 gắn mã máy, đủ chặn sao chép tuỳ tiện; mã nguồn Python vẫn đọc được nên không phải DRM tuyệt đối.

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
- **Sinh ảnh**: `interior.source.provider` và `cover.art.provider` nhận `openai` (gpt-image-1, `OPENAI_API_KEY`), `google` (Imagen 4 qua Gemini API, `GEMINI_API_KEY`) hoặc `stability` (Stable Image core/ultra/sd3, `STABILITY_API_KEY`). Key đặt trong file `.env` ở thư mục dự án (đã gitignore, xem `.env.example`) hoặc biến môi trường; `kdp keys` cho biết key nào đang có. Thử trước vài trang với `kdp image-test examples/bold-easy-flowers/book.yaml --n 3 --provider openai` (hoặc `--provider local`, `--lora repo:file.safetensors`): ảnh gốc và ảnh đã làm sạch nằm cạnh nhau trong `build/image-test/contact_sheet.png`, kèm QA và ước tính chi phí. Ba provider viết theo tài liệu công khai và chưa chạy với key thật trong repo này. Hoặc sinh ảnh bằng ComfyUI/Midjourney rồi dùng `provider: folder`.
- **Nguồn miễn phí**: `provider: spec` không cần model hay key: Claude (hoặc bạn) viết bản vẽ vector dạng JSON (đường tròn, cung, đường cong trơn, cánh hoa, lặp đối xứng) trong `drawings/`, tool tô nét dày thành trang tô màu sắc nét ở mọi DPI; xem `examples/bold-easy-flowers/drawings/` và `kdp draw-preview <thư mục>`. Hợp với mandala, hoa văn, hình khối to kiểu "bold & easy". `provider: pollinations` (FLUX, không key) chạy được nhưng ở mức ẩn danh cho ảnh nhỏ 630×940, có watermark và nhiều mảng đen, 3/3 trang thử bị QA loại (2026-10-24); `provider: cloudflare` (Workers AI, tài khoản Cloudflare miễn phí) là nguồn miễn phí tốt nhất đã đo: FLUX.1 schnell vẽ 30/30 trang cuốn hoa trong vài phút (~2 giây/trang, 2026-10-24), nét sạch đúng kiểu bold & easy. Gói miễn phí cấp 10.000 neuron/ngày (đủ vài chục đến hơn trăm trang FLUX 1024²; hết sau hai lần build thử trong ngày); khi hết, API trả HTTP 429 và build dừng ngay, giữ các trang đã đạt, ghi lý do vào `interior_manifest.json`; quota đặt lại lúc 00:00 UTC (07:00 giờ Việt Nam). Bộ lọc nội dung của Workers AI thỉnh thoảng chặn cả prompt hoa vô hại (HTTP 400 "NSFW"); tool coi đó là một lượt sinh lại. Máy có GPU 4 GB chạy được `provider: local` (Stable Diffusion 1.5 + LoRA coloring-book, ~60–70 giây/trang) nhưng model hay chèn người và nét rối hơn (27/30 trang cùng cuốn hoa, 3 trang bị bộ lọc người loại), nên là phương án dự phòng.
- **Model cục bộ (miễn phí, vô hạn)**: `provider: local` chạy Stable Diffusion 1.5 (mặc định `Lykon/dreamshaper-8`) qua diffusers trên GPU của bạn, kèm LoRA tuỳ chọn. Đo trên GTX 1050 Ti 4 GB: khoảng 60–70 giây một trang 512×768 ở 22–28 bước (chậm gấp 3 nếu có tiến trình khác dùng GPU); tool phóng lên cỡ in và tô nét lại. Cài bằng `kdp local-setup` (torch cu126 + diffusers + peft, tải model ~4 GB một lần). LoRA `ColoringBookRedmond15V` (từ khoá `ColoringBookAF` trong `style_prompt`) cho đúng chất sách tô màu nhưng hay tự thêm nhân vật; khai báo `interior.subjects` (mỗi trang một chủ đề cụ thể) và negative prompt có `person, face` giảm hẳn, trang lỗi bị QA loại và sinh lại với seed khác. Ví dụ `bold-easy-flowers` đang cấu hình theo đường này.
- **Làm sạch nét (2026-10-25)**: ảnh model (512 px) được phóng lên khổ trang *ở dạng xám* bằng Lanczos rồi mới nhị phân hóa, nên nét trơn thay vì răng cưa; khép các vết đứt cỡ một pixel gốc (`cleanup.close_gaps`), bỏ đốm nhỏ hơn ~3 pixel gốc theo diện tích thành phần liên thông (`despeckle`, không còn dùng median 3x3 vốn xóa cả nét 1 px), chỉ đục rỗng những mảng đen có lõi đủ lớn (`hollow_min_core`) nên chấm và mảng nhỏ giữ nguyên thay vì thành ô vuông rỗng, rồi làm tròn góc. `kdp build --reuse-raw` (hoặc ô *chỉ làm lại nét từ ảnh đã vẽ* trên trang sách) làm lại nét, QA và dàn trang từ ảnh gốc trong `build/raw` mà không gọi GPU/API, ~1,5 giây mỗi trang. QA heuristic có thêm ba kiểm tra chống trang quá rối: số mảnh mực rời (`qa.max_components`), tỷ lệ mực nằm trong mảnh vụn (`qa.max_fragment_ink`) và tỷ lệ trang bị chia thành ô trắng nhỏ dưới ~1 cm (`qa.max_tiny_white`, mặc định 10%; 30 trang FLUX bold & easy đo được ≤ 4%, các trang SD1.5 quá chi tiết 10–19%).
- **Chuẩn "bold & easy" và chuẩn hóa nét (2026-10-25)**: các sách bán chạy nhóm Bold & Easy / Simple / Large Print trên Amazon có chung đặc điểm: nét đều một cỡ khoảng 2–4 pt, không gạch bóng hay texture, mỗi hình khép kín, vùng tô rộng cỡ 1–2 cm trở lên, một chủ thể mỗi trang, lề rộng. Tool áp phần xử lý được bằng hậu kỳ: rút mọi nét về đường tâm (Zhang-Suen, chạy ở nửa độ phân giải rồi hoàn thiện ở độ phân giải đủ), bỏ nét rời ngắn hơn 2% bề rộng trang (`min_stroke_frac`: gạch bóng, vạch texture), tỉa nhánh thừa, nối đầu nét hở với mực phía trước trong 1,5% bề rộng (`bridge_frac`, số đầu nét hở giảm khoảng một nửa trên các trang SD1.5) rồi vẽ lại toàn bộ ở một độ dày chọn theo mật độ hình: tool đo tổng chiều dài nét và chọn độ dày sao cho mực phủ khoảng `target_ink` (12%) của trang, kẹp trong [`min_weight_frac`, `line_weight_frac`] = [0,003; 0,008] bề rộng ≈ 1,6–4,3 pt. Hình đơn giản kiểu FLUX nhận nét đậm (~4 pt, đúng chất bold), hình dày đặc kiểu SD1.5 nhận nét mảnh (~1,6–2 pt) để còn chỗ tô; đặt `line_weight_frac: 0` để giữ nét gốc của model. Nhụy hoa, mắt, chấm đặc (lõi tròn gọn) giữ nguyên, còn nét béo thì được rút mảnh. Phần không hậu kỳ được là mật độ hình vẽ: QA `max_tiny_white` loại trang quá chi tiết và sinh lại, còn nguồn ảnh quyết định phần lớn: FLUX (Cloudflare) ra trang đơn giản đúng kiểu, SD1.5 + LoRA ColoringBookRedmond ra tranh chi tiết nên cần ngưỡng nới hơn hoặc LoRA khác.
- **Lọc chữ giả**: cùng detector OWLv2, truy vấn "a watermark"/"a signature" bắt các dòng chữ ký giả model hay viết sát mép trang (`qa.reject_text`, ngưỡng 0,25; đo 2026-10-25: 4/30 trang có chữ đạt 0,39–0,61, 26 trang sạch ≤ 0,10, không bắt nhầm); trang bị loại được vẽ lại.
- **Lọc nội dung**: `cleanup.hollow_fills` (mặc định bật) biến vùng tô đen đặc thành đường viền để tô được, cứu phần lớn trang model vẽ lá/cành đen; `qa.reject_people` (mặc định bật, chỉ áp cho ảnh từ model) dùng CLIP zero-shot cục bộ (openai/clip-vit-base-patch32, miễn phí, tải một lần ~600 MB) loại trang có người, nội dung khoả thân hoặc chữ, vì LoRA coloring book hay tự chèn nhân vật kể cả khi prompt cấm. Trang bị loại được sinh lại với seed khác (tối đa `qa.max_retries`).
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
