"""Preventive pagination policy shared by every report component."""
from __future__ import annotations

from dataclasses import dataclass

from .page_context import PageContext


@dataclass(frozen=True)
class Section:
    section_id: str
    title: str = ""
    estimated_height: float = 0
    keep_together: bool = False
    allow_split: bool = True
    min_split_height: float = 52


class FlowLayout:
    """Coordinates page starts, safe footer clearance and single rendering."""
    safety_buffer = 48

    def __init__(self, pdf, context: PageContext | None = None):
        self.pdf, self.context = pdf, context or PageContext()
        self.rendered_sections: set[str] = set()

    @property
    def y(self): return self.context.cursor_y
    def move(self, amount): self.context.move_cursor(amount)
    def add_page(self):
        self.pdf.page(); self.context.page_number += 1; self.context.set_cursor(self.context.content_top)
    def ensure_space(self, required_height: float, *, keep_together=False, allow_split=True):
        # Do not strand a tiny unusable strip at the bottom of a page.
        needed = required_height + (self.safety_buffer if keep_together else 0)
        if needed > self.context.available_height() and (keep_together or not allow_split or self.context.available_height() < required_height):
            self.add_page()
            return True
        return False

    def begin(self, section: Section) -> bool:
        if section.section_id in self.rendered_sections:
            return False
        self.ensure_space(section.estimated_height, keep_together=section.keep_together, allow_split=section.allow_split)
        self.rendered_sections.add(section.section_id)
        return True
