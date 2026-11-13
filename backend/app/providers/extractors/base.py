from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(slots=True)
class ExtractedPage:
    text: str
    page_number: int | None = None
    section_title: str | None = None


@dataclass(slots=True)
class ExtractedDocument:
    pages: list[ExtractedPage]
    page_count: int
    title: str | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text.strip())


class DocumentExtractor(ABC):
    """Extracts structured text and page metadata from raw document bytes."""

    @abstractmethod
    def extract(self, data: bytes, *, filename: str = "") -> ExtractedDocument:
        """Parse bytes into ExtractedDocument."""
