import os

# The owner's machines skip the license gate; tests must not depend on a key being activated.
os.environ.setdefault("KDP_STUDIO_DEV", "1")
# Example books may point at the local GPU model; tests always render placeholders.
os.environ.setdefault("KDP_STUDIO_FORCE_PROVIDER", "placeholder")
# No CLIP download during tests.
os.environ.setdefault("KDP_STUDIO_SKIP_CONTENT_QA", "1")
