import json
from dataclasses import dataclass, asdict, field

from .articles import FILENAME_CHARS


@dataclass
class Recipe:
    link_selector: str
    url_filter: str
    headline_selector: str
    date_selector: str
    headline_fallback: str = ""
    date_fallback: str = ""
    item_selector: str = ""
    headline_on_listing: bool = False
    date_on_listing: bool = False
    dayfirst: bool = False
    boilerplate: list = field(default_factory=list)
    # raised for a site whose same-day headlines share an ending, like the old per-site setting
    filename_chars: int = FILENAME_CHARS

    def to_json(self):
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(text):
        return Recipe(**json.loads(text))
