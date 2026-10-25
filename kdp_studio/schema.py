"""book.yaml schema: the single source of truth for one title."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import specs

Origin = Literal["human", "ai_assisted", "ai_generated"]

DEFAULT_STYLE_PROMPT = (
    "black and white line art coloring book page, clean bold outlines, no shading, "
    "no gray, pure white background, no text, no watermark, high contrast, centered composition"
)
DEFAULT_NEGATIVE_PROMPT = (
    "color, shading, gradients, gray fill, text, letters, numbers, watermark, signature, blurry, photo"
)


class Provenance(BaseModel):
    """Who/what produced each kind of content. Drives the KDP AI disclosure answers."""

    text: Origin = "human"
    interior_images: Origin = "human"
    cover_art: Origin = "human"
    translation: Literal["none", "human", "ai_generated"] = "none"
    ai_tools: list[str] = Field(default_factory=list)  # KDP (2026-10) asks which AI tools made the images/text, e.g. ["gpt-image-1"]
    notes: str | None = None


class AgeRange(BaseModel):
    min: int = Field(ge=0, le=18)
    max: int = Field(ge=0, le=18)

    @model_validator(mode="after")
    def _ordered(self) -> "AgeRange":
        if self.min > self.max:
            raise ValueError("reading_age.min must be <= reading_age.max")
        return self


class Series(BaseModel):
    name: str
    number: int | None = Field(default=None, ge=1)


class Metadata(BaseModel):
    title: str = Field(min_length=1)
    subtitle: str | None = None
    author: str = Field(min_length=1)
    contributors: list[str] = Field(default_factory=list)
    description_html: str = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list, max_length=7)
    categories: list[str] = Field(default_factory=list, max_length=3)
    reading_age: AgeRange | None = None
    series: Series | None = None
    language: str = "English"
    low_content: bool = False
    large_print: bool = False  # KDP's checkbox: body text set in 16-point type or larger (not about image size)
    sexually_explicit: bool = False
    edition: str | None = None

    @property
    def full_title(self) -> str:
        return f"{self.title}: {self.subtitle}" if self.subtitle else self.title


class PrintSpec(BaseModel):
    trim: str = "8.5x11"
    paper: specs.PaperType = "white_bw"
    bleed: bool = True
    cover_finish: Literal["matte", "glossy"] = "matte"
    isbn: Literal["kdp_free", "own", "none"] = "kdp_free"
    isbn_number: str | None = None
    imprint: str | None = None  # publisher/imprint name KDP asks for with your own ISBN

    @field_validator("trim")
    @classmethod
    def _known_trim(cls, v: str) -> str:
        specs.get_trim(v)
        return v

    @property
    def trim_size(self) -> specs.Trim:
        return specs.get_trim(self.trim)


class ImageSource(BaseModel):
    provider: Literal["placeholder", "folder", "spec", "local", "openai", "google", "stability", "pollinations", "cloudflare", "auto"] = "placeholder"
    path: str | None = None
    chain: list[str] | None = None  # provider 'auto': members in order, e.g. [cloudflare, cloudflare#2, local]; None = the default chain (Cài đặt)
    model: str | None = None  # API model name, or for 'local' a Hugging Face repo id / .safetensors path (SD 1.5 family)
    size: str = "1024x1536"
    seed: int = 7
    # 'local' (diffusers on your GPU) only
    lora: str | None = None  # Hugging Face repo id (or repo:file.safetensors / local path) of a coloring-book LoRA
    lora_scale: float = Field(0.8, ge=0.0, le=2.0)
    steps: int = Field(28, ge=4, le=80)
    guidance: float = Field(7.0, ge=0.0, le=20.0)
    local_size: str = "512x768"  # generation size on the GPU; the page is upscaled and re-thresholded afterwards

    @model_validator(mode="after")
    def _folder_needs_path(self) -> "ImageSource":
        if self.provider in ("folder", "spec") and not self.path:
            raise ValueError(f"source.path is required when provider is '{self.provider}'")
        return self


class CleanupOptions(BaseModel):
    threshold: int = Field(128, ge=1, le=254)  # pixels darker than this become ink; 128 keeps diffusion-model gray shading out of the lines
    min_line_px: int = Field(3, ge=1, le=15)
    despeckle: int = Field(1, ge=0, le=5)  # drop ink blobs smaller than about 3 source pixels per step (0 = keep everything)
    autocontrast: bool = True
    art_margin_in: float = Field(0.5, ge=0.25, le=2.0)
    close_gaps: bool = True  # bridge hairline breaks (about one source pixel) so strokes stay continuous
    hollow_fills: bool = True  # large solid black regions become outlines (colorable) instead of failing QA
    hollow_border_frac: float = Field(0.006, ge=0.001, le=0.03)  # border kept around hollowed regions, as a fraction of the art width
    hollow_min_core: int = Field(6, ge=1, le=30)  # only solid cores at least (border * this)^2 px are hollowed; smaller fills and dots stay solid
    # stroke normalisation: every line is redrawn at one weight, like the bold-and-easy books (0 = keep the model's own line widths)
    line_weight_frac: float = Field(0.008, ge=0.0, le=0.02)  # heaviest stroke, as a fraction of the art width: 0.008 = 16 px on a 2000 px box = about 4.3 pt (0 = keep the model's own widths)
    min_weight_frac: float = Field(0.003, ge=0.0, le=0.02)  # lightest stroke: 6 px = about 1.6 pt, still above KDP's 0.75 pt minimum
    target_ink: float = Field(0.12, ge=0.02, le=0.4)  # the weight is chosen so ink covers about this share of the page: sparse drawings get bold lines, dense ones thin lines
    bridge_frac: float = Field(0.015, ge=0.0, le=0.05)  # open stroke ends are joined to ink found ahead within this fraction of the art width
    min_stroke_frac: float = Field(0.02, ge=0.0, le=0.2)  # isolated strokes shorter than this fraction of the art width are dropped (hatching, ticks)


class DedupeOptions(BaseModel):
    """Duplicate = pHash distance <= max_distance AND density correlation >= min_correlation."""

    enabled: bool = True
    max_distance: int = Field(6, ge=0, le=32)
    min_correlation: float = Field(0.985, ge=0.0, le=1.0)
    library: str = "library/image_hashes.json"


class QAOptions(BaseModel):
    heuristic: bool = True
    claude: bool = False
    model: str = "claude-opus-5-5"
    min_ink_ratio: float = Field(0.01, ge=0.0, le=1.0)
    max_ink_ratio: float = Field(0.30, ge=0.0, le=1.0)
    max_solid_black: float = Field(0.03, ge=0.0, le=0.5)
    max_components: int = Field(400, ge=10, le=100000)  # separate ink pieces after cleanup; bold-and-easy pages have tens, noisy textures thousands
    max_fragment_ink: float = Field(0.30, ge=0.0, le=1.0)  # share of ink sitting in small pieces (under 0.05% of the page each)
    max_tiny_white: float = Field(0.10, ge=0.0, le=1.0)  # share of the page in enclosed white cells under 0.1% of the page (~1 cm): fine texture is not bold-and-easy
    reject_people: bool = True  # free local OWLv2 detector: people and nudity (model-generated pages only)
    people_threshold: float = Field(0.27, ge=0.05, le=0.95)  # calibrated: people >= 0.33, flowers-only <= 0.21
    reject_text: bool = True  # the same detector flags pseudo-text / fake signatures the models like to write near the page edge
    text_threshold: float = Field(0.25, ge=0.05, le=0.95)  # calibrated 2026-10-25: 4 pages with fake signatures scored 0.39-0.61, 26 clean pages <= 0.10
    content_model: str = "google/owlv2-base-patch16-ensemble"
    content_device: Literal["cpu", "cuda"] = "cpu"  # cpu keeps a 4 GB GPU free for Stable Diffusion  # share of the page that is solid black after erosion (flower centres etc. are fine)
    max_retries: int = Field(2, ge=0, le=5)


FrontMatterItem = Literal["title", "copyright", "belongs_to", "test_colors", "blank"]
BackMatterItem = Literal["thank_you", "test_colors", "blank"]


class ColoringInterior(BaseModel):
    type: Literal["coloring"] = "coloring"
    theme: str = Field(min_length=1)
    audience: str = "adults"
    style_prompt: str = DEFAULT_STYLE_PROMPT
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT
    subjects: list[str] = Field(default_factory=list)  # one concrete drawing subject per page; beats the generic theme templates
    images: int = Field(30, ge=1, le=400)
    single_sided: bool = True
    back_page: Literal["blank", "test_colors"] = "blank"
    front_matter: list[FrontMatterItem] = Field(
        default_factory=lambda: ["title", "copyright", "belongs_to", "blank"]
    )
    back_matter: list[BackMatterItem] = Field(default_factory=lambda: ["thank_you", "blank"])
    copyright_notice: str | None = None
    source: ImageSource = Field(default_factory=ImageSource)
    cleanup: CleanupOptions = Field(default_factory=CleanupOptions)
    dedupe: DedupeOptions = Field(default_factory=DedupeOptions)
    qa: QAOptions = Field(default_factory=QAOptions)
    prompts_with_claude: bool = False
    prompts_model: str = "claude-opus-5-5"

    @model_validator(mode="after")
    def _images_start_on_recto(self) -> "ColoringInterior":
        # Image pages must start on a right-hand (odd) page.
        if len(self.front_matter) % 2 == 1:
            self.front_matter = [*self.front_matter, "blank"]
        return self

    def planned_pages(self, image_count: int | None = None) -> int:
        n = self.images if image_count is None else image_count
        per_image = 2 if self.single_sided else 1
        total = len(self.front_matter) + n * per_image + len(self.back_matter)
        total = max(total, specs.MIN_PAGES)
        return total + (total % 2)


class PrintMargins(BaseModel):
    """Typographic margins in inches; the builder raises `inside` to KDP's gutter minimum when needed."""

    inside: float = Field(0.75, ge=0.375, le=2.0)
    outside: float = Field(0.6, ge=0.25, le=2.0)
    top: float = Field(0.75, ge=0.5, le=2.0)
    bottom: float = Field(0.75, ge=0.5, le=2.0)


class EpubOptions(BaseModel):
    include_cover: bool = True
    css: str | None = None  # path to a custom stylesheet (relative to the book dir)
    publisher: str | None = None


FrontMatterStory = Literal["title", "copyright", "dedication", "epigraph"]
BackMatterStory = Literal["about_author", "also_by", "review_cta"]


class StoryInterior(BaseModel):
    """Markdown manuscript -> EPUB3 (reflowable) + print PDF."""

    type: Literal["story"] = "story"
    manuscript_dir: str = "manuscript"
    chapters_glob: str = "chapters/*.md"
    body_font: str | None = None  # TTF stem such as 'georgia'; variants are found automatically
    font_size_pt: float = Field(11.0, ge=7.0, le=16.0)
    leading: float = Field(1.4, ge=1.0, le=2.0)
    paragraph_indent_in: float = Field(0.3, ge=0.0, le=1.0)
    margins: PrintMargins = Field(default_factory=PrintMargins)
    chapter_start_recto: bool = True
    running_heads: bool = True
    page_numbers: bool = True
    numbered_chapters: bool = True
    chapter_label: str = "Chapter"
    front_matter: list[FrontMatterStory] = Field(default_factory=lambda: ["title", "copyright"])
    back_matter: list[BackMatterStory] = Field(default_factory=list)
    dedication: str | None = None
    epigraph: str | None = None
    epigraph_source: str | None = None
    about_author: str | None = None
    also_by: list[str] = Field(default_factory=list)
    review_cta: str | None = None
    copyright_notice: str | None = None
    smart_quotes: bool = True
    pad_to_min_pages: bool = True
    min_words: int | None = Field(default=None, ge=0)
    epub: EpubOptions = Field(default_factory=EpubOptions)
    kindle_previewer: bool = True


Interior = Annotated[Union[ColoringInterior, StoryInterior], Field(discriminator="type")]


class ArtSource(BaseModel):
    provider: Literal["placeholder", "file", "openai", "google", "stability", "pollinations", "cloudflare"] = "placeholder"
    path: str | None = None
    prompt: str | None = None
    model: str | None = None
    size: str = "1024x1536"
    seed: int = 11

    @model_validator(mode="after")
    def _file_needs_path(self) -> "ArtSource":
        if self.provider == "file" and not self.path:
            raise ValueError("cover.art.path is required when provider is 'file'")
        return self


class Palette(BaseModel):
    background: str = "#F6E7C1"
    accent: str = "#C94C4C"
    text: str = "#2B2B2B"
    title_text: str = "#FFFFFF"
    spine: str | None = None
    back: str | None = None


class CoverSpec(BaseModel):
    art: ArtSource = Field(default_factory=ArtSource)
    palette: Palette = Field(default_factory=Palette)
    title_font: str | None = None
    body_font: str | None = None
    spine_text: bool | None = None  # None = automatic (only when pages >= 79)
    back_blurb: str | None = None
    back_bullets: list[str] = Field(default_factory=list)
    barcode_box: bool = True
    debug_guides: bool = False


class EbookSpec(BaseModel):
    """Kindle eBook options that have no print counterpart."""

    drm: bool = False  # KDP requires an answer; DRM cannot be changed after publishing
    # KDP accessibility questionnaire: do informative images carry alternative text? (text-only books: 'none' of their images need it,
    # but answer what is true for your file; 'unknown' leaves KDP's default)
    accessibility_images: Literal["unknown", "none", "some", "all"] = "unknown"


class Pricing(BaseModel):
    marketplace: Literal["amazon.com"] = "amazon.com"
    list_price: float = Field(gt=0)
    ebook_list_price: float | None = Field(default=None, gt=0)
    expanded_distribution: bool = False  # paperback only; 40% royalty before printing cost
    kdp_select: bool = False  # eBook only; 90-day Kindle exclusivity for Kindle Unlimited


class Book(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    type: Literal["coloring", "story"]
    niche: str | None = None
    formats: list[Literal["paperback", "hardcover", "ebook"]] = Field(default_factory=lambda: ["paperback"])
    metadata: Metadata
    print_: PrintSpec = Field(default_factory=PrintSpec, alias="print")
    ebook: EbookSpec = Field(default_factory=EbookSpec)
    interior: Interior
    cover: CoverSpec = Field(default_factory=CoverSpec)
    pricing: Pricing
    provenance: Provenance = Field(default_factory=Provenance)
    output_dir: str = "build"
    source_path: Path | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _types_match(self) -> "Book":
        if self.interior.type != self.type:
            raise ValueError(f"book.type is '{self.type}' but interior.type is '{self.interior.type}'")
        return self

    @property
    def book_dir(self) -> Path:
        return self.source_path.parent if self.source_path else Path.cwd()

    def resolve(self, p: str | Path) -> Path:
        p = Path(p)
        return p if p.is_absolute() else (self.book_dir / p)

    @property
    def build_dir(self) -> Path:
        return self.resolve(self.output_dir)

    def ai_disclosure(self) -> dict[str, str]:
        """Answers for KDP's 'AI-Generated Content' section, derived from provenance."""
        p = self.provenance
        images = "ai_generated" if "ai_generated" in (p.interior_images, p.cover_art) else (
            "ai_assisted" if "ai_assisted" in (p.interior_images, p.cover_art) else "human"
        )
        used_ai = any(x == "ai_generated" for x in (p.text, images, p.translation))

        def label(origin: str) -> str:
            return {
                "ai_generated": "AI-generated — MUST be declared",
                "ai_assisted": "AI-assisted — no declaration required",
                "human": "None",
                "none": "None",
            }[origin]

        out = {
            "Did you use AI tools in creating texts, images and/or translations?": "Yes" if used_ai else "No",
            "Text": label(p.text),
            "Images": label(images),
            "Translations": label(p.translation),
        }
        if used_ai:
            scope = self.ai_scope()
            if images == "ai_generated":
                out["Images scope"] = scope["Images"][0] + (" (cover art only)" if p.interior_images != "ai_generated" else " (interior pages)")
            if p.text == "ai_generated":
                out["Text scope"] = scope["Text"][0]
            out["AI tools"] = ", ".join(p.ai_tools) if p.ai_tools else "REQUIRED - type the tool names in KDP's 'Which tool(s) did you use' field"
            out["Confirmation"] = "tick 'I confirm that my answers are accurate' yourself (KDP asks again whenever a file changes)"
        return out

    def ai_scope(self) -> dict[str, list[str]]:
        """Needles (in preference order) for KDP's per-category scope dropdowns: how much of the work is AI-made.
        A single AI cover is 'one or a few' images; AI interior pages are 'many or all'."""
        p = self.provenance
        images = ["many or all", "entire", "all", "many"] if p.interior_images == "ai_generated" else ["one or a few", "few", "some"]
        text = ["entire", "all", "many or all"] if p.text == "ai_generated" else ["some", "entire", "all"]
        return {"Text": text, "Images": images, "Translations": ["entire", "all", "some"]}


def load_book(path: str | Path) -> Book:
    path = Path(path).resolve()
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a YAML mapping")
    book = Book.model_validate(data)
    book.source_path = path
    return book
