# kdp-studio

Bộ công cụ sản xuất sách cho Amazon KDP, bắt đầu từ sách tô màu: một file `book.yaml` làm nguồn sự thật duy nhất → ruột sách PDF, bìa wrap PDF (CMYK, 300 DPI), bìa eBook JPEG và báo cáo preflight kiểm tra theo đúng thông số KDP.

Trạng thái: **Giai đoạn 0** (interior-forge cho sách tô màu + cover-forge + preflight). Nghiên cứu thị trường, chính sách và kiến trúc đầy đủ của toàn bộ bộ công cụ nằm trong [docs/KDP-Toolkit-Research.md](docs/KDP-Toolkit-Research.md).

## Cài đặt

Yêu cầu Python 3.11+. Không cần GPU hay API key để chạy thử (provider `placeholder` vẽ line art thủ tục).

```bash
python -m venv .venv && . .venv/bin/activate      # Linux/macOS
python -m pip install -e ".[dev,ai]"
python -m pytest
```

Trên Windows nếu `venv` lỗi `ensurepip` (bản Python từ Python Install Manager), cài thẳng vào user site:

```bash
python -m pip install --user -e ".[dev,ai]"
```

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

## book.yaml

Xem [examples/bold-easy-flowers/book.yaml](examples/bold-easy-flowers/book.yaml) có chú thích đầy đủ. Các khối chính:

- `metadata` — title, subtitle, author, `description_html`, 7 `keywords`, 3 `categories`, `reading_age`, `low_content` (phải `false` với sách tô màu).
- `print` — `trim` (16 cỡ KDP), `paper` (`white_bw`, `cream_bw`, `groundwood_bw`, `standard_color`, `premium_color`), `bleed`, `isbn`.
- `interior` (type `coloring`) — `theme`, `audience`, số `images`, in một mặt (`single_sided`), front/back matter, `source.provider` (`placeholder` | `folder` | `openai`), `cleanup`, `dedupe`, `qa`, `prompts_with_claude`.
- `cover` — `art.provider` (`placeholder` | `file` | `openai`), `palette`, font, `back_blurb`, `back_bullets`, `spine_text`, `barcode_box`.
- `pricing` — `list_price` trên amazon.com.
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
- **QA thị giác từng trang**: `interior.qa.claude: true`. Mỗi trang được chấm: line art sạch, có chữ rác, mảng đen lớn, lỗi hình, rủi ro IP, phù hợp tuổi.
- **Sinh ảnh**: `source.provider: openai` / `cover.art.provider: openai` + `OPENAI_API_KEY` (gọi Images API, chưa kiểm thử trong repo này; sửa `model`/`size` theo tài liệu hiện hành). Hoặc sinh ảnh bằng ComfyUI/Midjourney rồi dùng `provider: folder`.
- Mọi ảnh do model sinh ra là **AI-generated** theo định nghĩa KDP, kể cả khi đã chỉnh sửa nhiều → đặt `provenance` đúng.

## Giới hạn hiện tại

- Chỉ ruột sách tô màu; ruột truyện chữ (Markdown → EPUB + PDF) là Giai đoạn 2.
- Chưa render bìa hardcover (case laminate) — dùng KDP cover calculator.
- Chuyển RGB → CMYK bằng Pillow (không ICC profile); màu in có thể lệch nhẹ so với màn hình.
- Upscale bằng LANCZOS + re-threshold; chưa tích hợp Real-ESRGAN.
- Ước lượng DPI trong preflight giả định ảnh trải hết chiều rộng trang.
- Chưa có module upload; theo nghiên cứu, chỉ nên làm bán tự động có người bấm Publish.

## Lộ trình

1. **Giai đoạn 0 (này)**: schema, interior-forge tô màu, cover-forge, preflight. Upload thủ công 2 cuốn để Amazon xác nhận file chuẩn.
2. **Giai đoạn 1**: `niche-scout` (Creators API / Apify / Keepa) + `metadata-writer` + dashboard.
3. **Giai đoạn 2**: pipeline truyện chữ (Pandoc EPUB, Typst PDF, Kindle Previewer CLI) + `competitor-watch`.
4. **Giai đoạn 3**: `assisted-publisher` (Playwright, human-in-the-loop, hàng đợi theo quota tuần) + theo dõi sau xuất bản.

## Cấu trúc

```
kdp_studio/
  schema.py          book.yaml (pydantic) + suy ra khai báo AI
  specs.py           thông số KDP: trim, trang, lề, spine, bìa eBook
  pricing.py         chi phí in, royalty, giá sàn
  metadata_rules.py  luật metadata KDP
  fonts.py           tìm TTF, fallback Vera (reportlab) cho mọi hệ điều hành
  interior/          pagegeom, prompts, generate (providers), cleanup, dedupe, qa, layout, pipeline
  cover/             geometry, text, render
  preflight/         pdf_checks (pypdf), run (báo cáo)
  cli.py             validate | build | preflight | price | cover-size
examples/            book.yaml mẫu
library/             thư viện hash chống trùng xuyên sách
docs/                báo cáo nghiên cứu KDP & kiến trúc bộ công cụ
tests/               unit + end-to-end (build thật 10 trang rồi preflight)
```
