import json
from typing import cast


def decode(text: str) -> object:
    return cast("object", json.loads(text))
