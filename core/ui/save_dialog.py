"""Modal save dialog for PY3DCAD."""

from typing import Callable, Optional

import pygame

from .layout import Rect


class SaveDialog:
    """A minimal path input dialog used to save documents."""

    def __init__(self, on_submit: Callable[[str], Optional[str]]) -> None:
        self.on_submit = on_submit
        self.active = False
        self.text = ""
        self.error = ""
        self.scale = 1.0

        self._font_title: Optional[pygame.font.Font] = None
        self._font_label: Optional[pygame.font.Font] = None
        self._font_input: Optional[pygame.font.Font] = None
        self._font_small: Optional[pygame.font.Font] = None

        self.panel_bg = pygame.Color(38, 38, 45)
        self.input_bg = pygame.Color(27, 27, 33)
        self.border_color = pygame.Color(64, 64, 74)
        self.text_primary = pygame.Color(230, 230, 235)
        self.text_muted = pygame.Color(130, 130, 140)
        self.accent = pygame.Color(59, 130, 246)
        self.error_color = pygame.Color(235, 100, 100)

    def set_scale(self, scale: float) -> None:
        if abs(scale - self.scale) < 1e-6:
            return
        self.scale = scale
        self._font_title = None
        self._font_label = None
        self._font_input = None
        self._font_small = None

    def _s(self, value: float) -> int:
        return max(1, int(round(value * self.scale)))

    def _init_fonts(self) -> None:
        if self._font_title is not None:
            return
        self._font_title = pygame.font.SysFont("Segoe UI", self._s(18), bold=True)
        self._font_label = pygame.font.SysFont("Segoe UI", self._s(12))
        self._font_input = pygame.font.SysFont("Consolas", self._s(13))
        self._font_small = pygame.font.SysFont("Segoe UI", self._s(11))

    def open(self, default_path: str) -> None:
        self.active = True
        self.text = default_path
        self.error = ""

    def close(self) -> None:
        self.active = False
        self.error = ""

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Handle dialog input. Always consumes events while active."""
        if not self.active:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.close()
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._submit()
            elif event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif not (event.mod & pygame.KMOD_CTRL):
                if event.unicode and event.unicode.isprintable() and len(self.text) < 300:
                    self.text += event.unicode
            return True

        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEWHEEL):
            return True

        return event.type in (pygame.MOUSEMOTION,)

    def _submit(self) -> None:
        path = self.text.strip()
        if not path:
            self.error = "Please enter a file path."
            return
        error = self.on_submit(path)
        if error:
            self.error = error
        else:
            self.active = False

    def draw(self, surface: pygame.Surface, region: Rect) -> None:
        if not self.active:
            return
        self._init_fonts()

        overlay = pygame.Surface(region.rect.size, pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        surface.blit(overlay, (region.x, region.y))

        width = min(self._s(620), region.w - self._s(40))
        height = self._s(200)
        panel = pygame.Rect(0, 0, width, height)
        panel.center = region.center
        pygame.draw.rect(surface, self.panel_bg, panel, border_radius=8)
        pygame.draw.rect(surface, self.border_color, panel, width=1, border_radius=8)

        title = self._font_title.render("Save Document", True, self.text_primary)
        surface.blit(title, (panel.x + self._s(18), panel.y + self._s(16)))

        label = self._font_label.render("File path", True, self.text_muted)
        surface.blit(label, (panel.x + self._s(18), panel.y + self._s(52)))

        input_rect = pygame.Rect(
            panel.x + self._s(18), panel.y + self._s(72),
            panel.w - self._s(36), self._s(34),
        )
        pygame.draw.rect(surface, self.input_bg, input_rect, border_radius=4)
        pygame.draw.rect(surface, self.accent, input_rect, width=1, border_radius=4)

        previous_clip = surface.get_clip()
        surface.set_clip(input_rect.inflate(-self._s(8), 0))
        text = self._font_input.render(self.text, True, self.text_primary)
        text_x = input_rect.x + self._s(8)
        if text.get_width() > input_rect.w - self._s(16):
            text_x = input_rect.right - self._s(8) - text.get_width()
        surface.blit(text, text.get_rect(x=text_x, centery=input_rect.centery))
        caret_x = text_x + text.get_width() + 1
        pygame.draw.line(
            surface, self.text_primary,
            (caret_x, input_rect.y + self._s(7)),
            (caret_x, input_rect.bottom - self._s(7)), 1,
        )
        surface.set_clip(previous_clip)

        if self.error:
            error = self._font_small.render(self.error, True, self.error_color)
            surface.blit(error, (panel.x + self._s(18), panel.y + self._s(112)))
        else:
            hint = self._font_small.render(
                "Enter to save  ·  Esc to cancel", True, self.text_muted
            )
            surface.blit(hint, (panel.x + self._s(18), panel.y + self._s(114)))
