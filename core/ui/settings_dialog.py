"""Modal settings dialog for PY3DCAD."""

from typing import Callable, Optional

import pygame

from .layout import Rect


class SettingsDialog:
    """A small modal panel for application display settings."""

    def __init__(
        self, on_show_orientation_cube: Callable[[bool], None]
    ) -> None:
        self.on_show_orientation_cube = on_show_orientation_cube
        self.active = False
        self.show_orientation_cube = True
        self.scale = 1.0
        self._hover_checkbox = False
        self._hover_close = False

        self._font_title: Optional[pygame.font.Font] = None
        self._font_label: Optional[pygame.font.Font] = None
        self._font_small: Optional[pygame.font.Font] = None

        self.panel_bg = pygame.Color(38, 38, 45)
        self.border_color = pygame.Color(64, 64, 74)
        self.text_primary = pygame.Color(230, 230, 235)
        self.text_muted = pygame.Color(130, 130, 140)
        self.accent = pygame.Color(59, 130, 246)
        self.checkbox_bg = pygame.Color(27, 27, 33)
        self.hover_bg = pygame.Color(48, 48, 56)

    def set_scale(self, scale: float) -> None:
        if abs(scale - self.scale) < 1e-6:
            return
        self.scale = scale
        self._font_title = None
        self._font_label = None
        self._font_small = None

    def _s(self, value: float) -> int:
        return max(1, int(round(value * self.scale)))

    def _init_fonts(self) -> None:
        if self._font_title is not None:
            return
        self._font_title = pygame.font.SysFont(
            "Segoe UI", self._s(18), bold=True
        )
        self._font_label = pygame.font.SysFont("Segoe UI", self._s(13))
        self._font_small = pygame.font.SysFont("Segoe UI", self._s(11))

    def open(self, show_orientation_cube: bool) -> None:
        self.active = True
        self.show_orientation_cube = show_orientation_cube
        self._hover_checkbox = False
        self._hover_close = False

    def close(self) -> None:
        self.active = False

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _panel_rect(self, region: Rect) -> pygame.Rect:
        width = min(self._s(440), region.w - self._s(40))
        height = self._s(196)
        panel = pygame.Rect(0, 0, width, height)
        panel.center = region.center
        return panel

    def _checkbox_rect(self, panel: pygame.Rect) -> pygame.Rect:
        size = self._s(18)
        return pygame.Rect(
            panel.x + self._s(24),
            panel.y + self._s(84),
            size,
            size,
        )

    def _close_rect(self, panel: pygame.Rect) -> pygame.Rect:
        size = self._s(24)
        return pygame.Rect(
            panel.right - self._s(14) - size,
            panel.y + self._s(12),
            size,
            size,
        )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def handle_event(
        self, event: pygame.event.Event, region: Rect
    ) -> bool:
        if not self.active:
            return False

        panel = self._panel_rect(region)
        checkbox = self._checkbox_rect(panel)
        close = self._close_rect(panel)

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER):
                self.close()
            elif event.key == pygame.K_SPACE:
                self._toggle()
            return True

        if event.type == pygame.MOUSEMOTION:
            self._hover_checkbox = checkbox.collidepoint(event.pos)
            self._hover_close = close.collidepoint(event.pos)
            return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if checkbox.collidepoint(event.pos):
                self._toggle()
            elif close.collidepoint(event.pos) or not panel.collidepoint(event.pos):
                self.close()
            return True

        return event.type in (
            pygame.MOUSEBUTTONUP,
            pygame.MOUSEWHEEL,
        )

    def _toggle(self) -> None:
        self.show_orientation_cube = not self.show_orientation_cube
        self.on_show_orientation_cube(self.show_orientation_cube)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self, surface: pygame.Surface, region: Rect) -> None:
        if not self.active:
            return
        self._init_fonts()

        overlay = pygame.Surface(region.rect.size, pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        surface.blit(overlay, (region.x, region.y))

        panel = self._panel_rect(region)
        pygame.draw.rect(surface, self.panel_bg, panel, border_radius=8)
        pygame.draw.rect(
            surface, self.border_color, panel, width=1, border_radius=8
        )

        title = self._font_title.render("Settings", True, self.text_primary)
        surface.blit(title, (panel.x + self._s(22), panel.y + self._s(14)))

        close = self._close_rect(panel)
        if self._hover_close:
            pygame.draw.rect(
                surface, self.hover_bg, close, border_radius=self._s(4)
            )
        self._draw_close_icon(surface, close, self.text_muted)

        checkbox = self._checkbox_rect(panel)
        pygame.draw.rect(
            surface, self.checkbox_bg, checkbox,
            border_radius=self._s(3),
        )
        border = self.accent if self._hover_checkbox else self.border_color
        pygame.draw.rect(
            surface, border, checkbox, width=1, border_radius=self._s(3)
        )
        if self.show_orientation_cube:
            self._draw_check(surface, checkbox)

        label = self._font_label.render(
            "Show orientation cube", True, self.text_primary
        )
        surface.blit(
            label,
            (checkbox.right + self._s(12), checkbox.y - self._s(1)),
        )

        description = self._font_small.render(
            "Display the axis cube in the top-right corner of the viewport.",
            True, self.text_muted,
        )
        surface.blit(
            description,
            (checkbox.x, checkbox.bottom + self._s(12)),
        )

        hint = self._font_small.render(
            "Esc or click outside to close", True, self.text_muted
        )
        surface.blit(
            hint,
            (panel.x + self._s(24), panel.bottom - self._s(28)),
        )

    def _draw_check(
        self, surface: pygame.Surface, rect: pygame.Rect
    ) -> None:
        points = [
            (rect.x + rect.w * 0.22, rect.centery),
            (rect.x + rect.w * 0.42, rect.bottom - rect.h * 0.26),
            (rect.right - rect.w * 0.18, rect.y + rect.h * 0.28),
        ]
        pygame.draw.lines(
            surface, self.accent, False, points, max(2, self._s(2))
        )

    def _draw_close_icon(
        self, surface: pygame.Surface, rect: pygame.Rect,
        color: pygame.Color,
    ) -> None:
        pad = rect.w // 3
        pygame.draw.line(
            surface, color,
            (rect.x + pad, rect.y + pad),
            (rect.right - pad, rect.bottom - pad), 2,
        )
        pygame.draw.line(
            surface, color,
            (rect.right - pad, rect.y + pad),
            (rect.x + pad, rect.bottom - pad), 2,
        )
