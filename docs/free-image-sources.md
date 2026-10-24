# Nguồn sinh ảnh miễn phí và repo tham khảo (khảo sát 2026-10-24)

Tóm tắt cho kdp-studio (máy tham chiếu: Windows 10, GTX 1050 Ti 4 GB, 32 GB RAM, Python 3.14). Chi tiết tiếng Anh ở phần dưới; mục đánh dấu *unverified* chưa xác nhận được từ trang chính thức.

## Kết luận nhanh

| Mục đích | Lựa chọn miễn phí tốt nhất | Trong tool |
|---|---|---|
| Trang tô màu "bold & easy" | Bản vẽ vector do Claude/bạn soạn (không model) · SD1.5 cục bộ (DreamShaper-8 hoặc ColoringBookSD + LoRA ColoringBookRedmond15V) | `provider: spec` · `provider: local` |
| Trang minh hoạ chi tiết | Cloudflare Workers AI `@cf/black-forest-labs/flux-1-schnell` (≈170–230 ảnh/ngày miễn phí) rồi làm sạch nét | `provider: cloudflare` |
| Ảnh in độ phân giải cao | Cloudflare `@cf/lykon/dreamshaper-8-lcm` hoặc SDXL tới 2048 px | `provider: cloudflare` + `model:` |
| Bìa màu | Cloudflare FLUX/SDXL; 25 credit dùng thử của Stability cho vài bìa đẹp | `cover.art.provider: cloudflare` / `stability` |
| Bản nháp nhanh, không tài khoản | pollinations.ai ẩn danh (nhỏ, có watermark, hạn chế 1 ảnh/45 giây) | `provider: pollinations` |

Không miễn phí (10/2026): Hugging Face Inference Providers (tài khoản free không có hạn mức), Gemini API image models (không có free tier), Together FLUX-schnell-Free (đã rút, *unverified*), Replicate/fal (chỉ dùng thử), Leonardo/Ideogram (chỉ web).

## Chạy cục bộ trên GTX 1050 Ti (Pascal, 4 GB)

- PyTorch: dùng đúng index `https://download.pytorch.org/whl/cu126` (torch 2.9–2.14 có bản cp314 Windows). cu128/cu129/CUDA 13 đã bỏ Pascal; cu126 dừng ở torch 2.14. `kdp local-setup` mặc định cu126.
- SD1.5 fp16 ở 512–768 px chạy vừa; SDXL không vừa trong PyTorch (stable-diffusion.cpp có thể chạy FLUX q2_k 3.7 GB nhưng chậm).
- File tải không cần đăng nhập trên Hugging Face:
  - `Lykon/dreamshaper-8` (diffusers, unet fp16 1.72 GB, openrail-m) — checkpoint SD1.5 tổng quát tốt nhất.
  - `artificialguybr/coloringbook-redmond-1-5v-coloring-book-lora-for-liberteredmond-sd-1-5` → `ColoringBookRedmond15V-LiberteRedmond-ColoringBookAF.safetensors` (76 MB, từ khoá kích hoạt `ColoringBookAF`); license "bespoke-lora-trained-license", allowCommercialUse=Rent — **kiểm tra lại trước khi bán sách**.
  - `artificialguybr/ColoringBookSD` → `VARPJ1.safetensors` (2.13 GB, openrail-m), prompt "in VARPJ1 Coloring Book Art Style".
  - `whitebearhands/lineart-lora` (51 MB, MIT, chưa kiểm chứng chất lượng).
  - `lllyasviel/control_v11p_sd15_lineart` (723 MB fp16) — chuyển ảnh thành nét vẽ (ControlNet).
  - Tránh `MrHup/coloring-book` (GPL-3.0).
- Runner khác: stable-diffusion.cpp (MIT, có bản Windows CUDA 12 cho sm 61+), ComfyUI portable (GPL-3.0: chỉ gọi như tiến trình riêng, không nhúng), Fooocus không hỗ trợ GTX 1xxx 4 GB.

## Repo GitHub đáng tham khảo

- Chuyển ảnh thành nét: `carolineec/informative-drawings` (MIT), `Mukosame/Anime2Sketch` (MIT), `huggingface/controlnet_aux` (Apache-2.0), `lllyasviel/ControlNet` (Apache-2.0).
- Vector hoá để in nét: `vtracer` (MIT, raster → SVG), `resvg-py` (MIT/MPL) hoặc `svglib` (LGPL) để rasterize SVG; potrace là GPL.
- KDP PDF/bìa: `pushkar-mishra/BookForge`, `devanasolver/kdp-toolkit`, `alanherron/kdp-cover-math` (đều MIT) — cùng công thức gáy 0.002252"/trang trắng, 0.0025"/trang kem, bleed 0.125".
- Tự động hoá KDP bằng trình duyệt: `ekr0/auto-kdp` (MIT, Puppeteer, headed mode cho upload; vỡ khi KDP đổi id); không có dự án Playwright/Selenium đáng kể. Rủi ro điều khoản dịch vụ như đã ghi trong README.
- Mandala: `evoluteur/mandala-maker` (MIT, JS, xuất SVG); RandomMandala (Artistic licence).
- Tránh (GPL/AGPL/CC BY-NC): hemchand/coloring-book-generator, R0mb0/Mandala_coloring_PDF_generator, ComfyUI (nhúng), potrace.

## Cloudflare Workers AI (chi tiết)

- Tài khoản miễn phí, cần `CF_ACCOUNT_ID` + `CF_API_TOKEN` (quyền Workers AI). Hạn mức 10.000 neuron/ngày, reset 00:00 UTC; FLUX schnell ≈ 4,8 neuron/ô 512² + 9,6/bước → khoảng 170–230 ảnh/ngày. SDXL và DreamShaper-LCM ở trạng thái Beta, chưa có trong bảng giá.
- Model: `@cf/black-forest-labs/flux-1-schnell` (Apache-2.0, ≤ 8 bước, kích thước đầu ra chưa rõ, *unverified*), `@cf/stabilityai/stable-diffusion-xl-base-1.0` (OpenRAIL++-M, 256–2048 px), `@cf/lykon/dreamshaper-8-lcm` (openrail, 256–2048 px, ít bước).

## Báo cáo gốc của agent nghiên cứu (tiếng Anh)

Bảng đầy đủ và các đường dẫn nguồn nằm trong lịch sử phiên làm việc 2026-10-24; các con số trên được chép nguyên từ báo cáo đó.

## Kết quả đo thực tế trong tool (2026-10-24, GTX 1050 Ti)

| Hướng | Kết quả |
|---|---|
| Vector spec (Claude soạn) | 3/3 trang qua QA, nét sạch tuyệt đối, 0 giây GPU |
| Pollinations ẩn danh | 0/3 qua QA: ảnh 630×940, watermark, mảng đen lớn |
| local DreamShaper-8, prompt chung | bó hoa cúc rất đẹp (sau khi hạ ngưỡng làm sạch xuống 128), mandala quá rậm; ~70 s/trang |
| local DreamShaper-8 + LoRA ColoringBookAF + subjects | 2/3 qua QA (cúc, tulip đẹp), 1 trang LoRA tự chèn người → QA loại, pipeline sinh lại |
| **Cloudflare Workers AI FLUX schnell** (key miễn phí) | **3/3 qua QA, nét sạch đúng kiểu bold & easy, ~2,2 s/trang**, ảnh 1024×1024 JPEG được đặt vào khung trang; không thấy người trong 3 trang thử |

Cần nhớ: giấy phép LoRA ColoringBookRedmond là "bespoke-lora-trained-license" (Civitai, allowCommercialUse=Rent) — xác nhận trước khi bán sách làm bằng LoRA này; DreamShaper-8 là openrail-m, cho phép thương mại với điều kiện sử dụng có trách nhiệm.

