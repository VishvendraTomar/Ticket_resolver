"""Token estimation shared by chunking and the embedding budget check.

Provider tokenisers differ (and Gemini's isn't available offline), so we use a
deterministic, slightly pessimistic estimate: word-ish pieces and punctuation,
scaled by 1.3. Chunk targets and the embedding cap leave wide margins for error.
"""

from __future__ import annotations

import math
import re

_PIECES = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def estimate_tokens(text: str) -> int:
    return math.ceil(len(_PIECES.findall(text)) * 1.3)
