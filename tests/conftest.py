import os

# The owner's machines skip the license gate; tests must not depend on a key being activated.
os.environ.setdefault("KDP_STUDIO_DEV", "1")
