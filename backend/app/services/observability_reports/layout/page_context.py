"""Page geometry and safe cursor management."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PageContext:
    page_width: float = 595
    page_height: float = 842
    margin_top: float = 42
    margin_bottom: float = 42
    margin_left: float = 42
    margin_right: float = 42
    header_height: float = 0
    footer_height: float = 42
    page_number: int = 1
    cursor_y: float = 800

    def __post_init__(self): self.cursor_y = self.content_top
    @property
    def content_top(self) -> float: return self.page_height - self.margin_top - self.header_height
    @property
    def content_bottom(self) -> float: return self.margin_bottom + self.footer_height
    @property
    def content_width(self) -> float: return self.page_width - self.margin_left - self.margin_right
    def available_height(self) -> float: return self.cursor_y - self.content_bottom
    def reserve_space(self, height: float) -> None: self.cursor_y -= height
    def move_cursor(self, amount: float) -> None: self.reserve_space(amount)
    def set_cursor(self, y: float) -> None: self.cursor_y = y
