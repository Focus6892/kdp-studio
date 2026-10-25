import os

# The owner's machines skip the license gate; tests must not depend on a key being activated.
os.environ.setdefault("KDP_STUDIO_DEV", "1")
# Example books may point at the local GPU model; tests always render placeholders.
os.environ.setdefault("KDP_STUDIO_FORCE_PROVIDER", "placeholder")
# No CLIP download during tests.
os.environ.setdefault("KDP_STUDIO_SKIP_CONTENT_QA", "1")
# The create-form "Gợi ý" button never calls Claude or Cloudflare during tests (the real .env may hold keys).
os.environ.setdefault("KDP_STUDIO_SUGGEST", "offline")
os.environ["KDP_STUDIO_NO_CLAUDE_CLI"] = "1"  # never shell out to the real claude command in tests
