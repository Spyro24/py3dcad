"""Document tab bar for PY3DCAD."""

from typing import Callable, List, Optional, Tuple

import pygame

from ..document import Document
from .layout import Rect


class TabBar:
    """Draws the top bar with the brand and one tab per open document."""

    def __init__(
        self,
        on_select: Callable[[int], None],
        on_close: Callable[[int], None],
        on_new: Callable[[], None],
    ) -> None:
        self.on_select = on_select
        self.on_close = on_close
        self.on_new = on_new
        self.scale = 1.0

        self._font_brand: Optional[pygame.font.Font] = None
        self._font_page: Optional[pygame.font.Font] = None
        self._font_tab: Optional[pygame.font.Font] = None
        self._font_close: Optional[pygame.font.Font] = None

        self._hover_tab: int = -1
        self._hover_close: int = -1
        self._hover_new: bool = False

        self.bg_color = pygame.Color(24, 24, 29)
        self.tab_bg = pygame.Color(34, 34, 40)
        self.tab_hover = pygame.Color(40, 40, 47)
        self.tab_active = pygame.Color(48, 48, 56)
        self.border_color = pygame.Color(52, 52, 60)
        self.text_primary = pygame.Color(232, 232, 237)
        self.text_muted = pygame.Color(140, 140, 150)
        self.accent = pygame.Color(59, 130, 246)

    def set_scale(self, scale: float) -> None:
        if abs(scale - self.scale) < 1e-6:
            return
        self.scale = scale
        self._font_brand = None
        self._font_page = None
        self._font_tab = None
        self._font_close = None

    def _s(self, value: float) -> int:
        return max(1, int(round(value * self.scale)))

    def _init_fonts(self) -> None:
        if self._font_tab is not None:
            return
        self._font_brand = pygame.font.SysFont("Segoe UI", self._s(16), bold=True)
        self._font_page = pygame.font.SysFont("Segoe UI", self._s(13))
        self._font_tab = pygame.font.SysFont("Segoe UI", self._s(13))
        self._font_close = pygame.font.SysFont("Segoe UI", self._s(15))

    def handle_event(
        self,
        event: pygame.event.Event,
        region: Rect,
        documents: List[Document],
        active_id: Optional[int],
    ) -> bool:
        """Handle tab interactions. Returns True if the event was consumed."""
        self._init_fonts()
        tabs, plus_rect = self._layout(region, documents)

        if event.type == pygame.MOUSEMOTION:
            self._update_hover(event.pos, tabs, plus_rect)
            return False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if plus_rect.collidepoint(event.pos):
                self.on_new()
                return True
            for index, tab_rect, close_rect in tabs:
                if close_rect.collidepoint(event.pos):
                    self.on_close(documents[index].id)
                    return True
                if tab_rect.collidepoint(event.pos):
                    if documents[index].id != active_id:
                        self.on_select(documents[index].id)
                    return True

        return False

    def draw(
        self,
        surface: pygame.Surface,
        region: Rect,
        documents: List[Document],
        active_id: Optional[int],
    ) -> None:
        self._init_fonts()
        pygame.draw.rect(surface, self.bg_color, region.rect)
        pygame.draw.line(
            surface, self.border_color,
            (region.x, region.bottom - 1), (region.right, region.bottom - 1),
        )

        brand = self._font_brand.render("PY3DCAD", True, self.text_primary)
        surface.blit(brand, brand.get_rect(x=region.x + self._s(16), centery=region.centery))

        tabs_x = region.x + self._s(16) + brand.get_width() + self._s(16)
        pygame.draw.line(
            surface, self.border_color,
            (tabs_x - self._s(8), region.y + self._s(8)),
            (tabs_x - self._s(8), region.bottom - self._s(8)),
        )

        tabs, plus_rect = self._layout(region, documents)

        if not documents:
            page = self._font_page.render("Start", True, self.text_muted)
            surface.blit(
                page,
                page.get_rect(x=tabs_x - self._s(4), centery=region.centery),
            )
        else:
            for index, tab_rect, close_rect in tabs:
                document = documents[index]
                active = document.id == active_id
                hovered = index == self._hover_tab

                if active:
                    bg = self.tab_active
                elif hovered:
                    bg = self.tab_hover
                else:
                    bg = self.tab_bg

                pygame.draw.rect(surface, bg, tab_rect, border_top_left_radius=5,
                                 border_top_right_radius=5)
                if active:
                    pygame.draw.rect(
                        surface, self.accent,
                        pygame.Rect(tab_rect.x, tab_rect.bottom - self._s(2),
                                    tab_rect.w, self._s(2)),
                    )

                text_color = self.text_primary if active else self.text_muted
                available = tab_rect.w - self._s(34)
                label = document.name + (" *" if document.dirty else "")
                text = self._fit_text(self._font_tab, label, text_color, available)
                surface.blit(
                    text,
                    text.get_rect(x=tab_rect.x + self._s(12), centery=tab_rect.centery),
                )

                close_color = (
                    self.text_primary if index == self._hover_close else self.text_muted
                )
                self._draw_close(surface, close_rect, close_color)

        self._draw_plus(surface, plus_rect, self._hover_new)

        pygame.draw.line(
            surface, self.border_color,
            (tabs_x, region.bottom - 1), (region.right, region.bottom - 1),
        )

    def _layout(
        self, region: Rect, documents: List[Document]
    ) -> Tuple[List[Tuple[int, pygame.Rect, pygame.Rect]], pygame.Rect]:
        """Compute tab and close-button rectangles plus the new-tab button."""
        self._init_fonts()
        brand_width = self._font_brand.size("PY3DCAD")[0]
        x = region.x + self._s(16) + brand_width + self._s(16)
        gap = self._s(4)
        plus_w = self._s(30)
        tab_h = region.h - self._s(8)
        y = region.y + self._s(4)

        if not documents:
            page_width = self._font_page.size("Start")[0]
            plus_x = x - self._s(4) + page_width + self._s(10)
            return [], pygame.Rect(plus_x, y, plus_w, tab_h)

        available = region.right - x - self._s(8) - plus_w - gap
        count = len(documents)
        tab_w = (available - gap * (count - 1)) // count
        tab_w = min(self._s(220), max(self._s(96), tab_w))

        tabs: List[Tuple[int, pygame.Rect, pygame.Rect]] = []
        for index in range(count):
            tab_rect = pygame.Rect(x + index * (tab_w + gap), y, tab_w, tab_h)
            close_size = self._s(14)
            close_rect = pygame.Rect(
                tab_rect.right - close_size - self._s(8),
                tab_rect.centery - close_size // 2,
                close_size, close_size,
            )
            tabs.append((index, tab_rect, close_rect))

        plus_rect = pygame.Rect(x + count * (tab_w + gap), y, plus_w, tab_h)
        return tabs, plus_rect

    def _update_hover(
        self, pos: Tuple[int, int],
        tabs: List[Tuple[int, pygame.Rect, pygame.Rect]],
        plus_rect: pygame.Rect,
    ) -> None:
        self._hover_tab = -1
        self._hover_close = -1
        self._hover_new = plus_rect.collidepoint(pos)
        for index, tab_rect, close_rect in tabs:
            if tab_rect.collidepoint(pos):
                self._hover_tab = index
                if close_rect.collidepoint(pos):
                    self._hover_close = index
                return

    def _draw_plus(
        self, surface: pygame.Surface, rect: pygame.Rect, hovered: bool
    ) -> None:
        if hovered:
            pygame.draw.rect(
                surface, self.tab_hover, rect, border_radius=self._s(5)
            )
        color = self.text_primary if hovered else self.text_muted
        pad = self._s(9)
        thickness = max(1, self._s(2))
        pygame.draw.line(
            surface, color,
            (rect.x + pad, rect.centery), (rect.right - pad, rect.centery), thickness,
        )
        pygame.draw.line(
            surface, color,
            (rect.centerx, rect.y + pad), (rect.centerx, rect.bottom - pad), thickness,
        )

    def _draw_close(
        self, surface: pygame.Surface, rect: pygame.Rect, color: pygame.Color
    ) -> None:
        pad = self._s(4)
        pygame.draw.line(
            surface, color,
            (rect.x + pad, rect.y + pad), (rect.right - pad, rect.bottom - pad), 2,
        )
        pygame.draw.line(
            surface, color,
            (rect.right - pad, rect.y + pad), (rect.x + pad, rect.bottom - pad), 2,
        )

    def _fit_text(
        self, font: pygame.font.Font, text: str,
        color: pygame.Color, max_width: int,
    ) -> pygame.Surface:
        if font.size(text)[0] <= max_width:
            return font.render(text, True, color)
        ellipsis = "..."
        available = max_width - font.size(ellipsis)[0]
        if available <= 0:
            return font.render(ellipsis, True, color)
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if font.size(text[:mid])[0] <= available:
                low = mid
            else:
                high = mid - 1
        return font.render(text[:low] + ellipsis, True, color)
