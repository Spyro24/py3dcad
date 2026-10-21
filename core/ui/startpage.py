"""Start page UI for PY3DCAD."""

import pygame
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .layout import Rect


@dataclass
class RecentFile:
    """Represents a recently opened file."""
    name: str
    path: str
    opened: str = ""
    preview_kind: str = "box"
    preview_surface: Optional[pygame.Surface] = None


@dataclass
class ExampleFile:
    """Represents an example file shipped with the app."""
    name: str
    path: str
    description: str = ""
    preview_kind: str = "box"
    preview_surface: Optional[pygame.Surface] = None


@dataclass
class _Geometry:
    """Computed positions for the start page content."""
    new_button: pygame.Rect
    open_button: pygame.Rect
    recent_label_y: int
    samples_label_y: int
    recent_cards: List[pygame.Rect] = field(default_factory=list)
    sample_cards: List[pygame.Rect] = field(default_factory=list)
    content_height: int = 0


class StartPage:
    """Start page shown when no document is open."""

    MARGIN = 16
    GAP = 16
    TOP_PADDING = 20
    BOTTOM_PADDING = 24
    BUTTON_W = 180
    BUTTON_H = 66
    LABEL_H = 20
    SECTION_GAP = 24
    SCROLL_STEP = 48

    def __init__(
        self,
        on_new_document: Callable[[], None],
        on_open_document: Callable[[], None],
        on_open_recent: Callable[[str], None],
        on_open_example: Callable[[str], None],
    ):
        self.on_new_document = on_new_document
        self.on_open_document = on_open_document
        self.on_open_recent = on_open_recent
        self.on_open_example = on_open_example

        self.recent_files: List[RecentFile] = []
        self.example_files: List[ExampleFile] = []
        self.scale = 1.0

        self._hovered_button: Optional[str] = None
        self._hovered_recent: int = -1
        self._hovered_example: int = -1
        self._mouse_pos: Tuple[int, int] = (0, 0)
        self._scroll: int = 0
        self._last_region: Optional[Rect] = None
        self._preview_cache: Dict[tuple, pygame.Surface] = {}

        self._font_brand: Optional[pygame.font.Font] = None
        self._font_label: Optional[pygame.font.Font] = None
        self._font_button: Optional[pygame.font.Font] = None
        self._font_name: Optional[pygame.font.Font] = None
        self._font_small: Optional[pygame.font.Font] = None

        self.bg_color = pygame.Color(26, 26, 30)
        self.card_bg = pygame.Color(35, 35, 40)
        self.card_hover = pygame.Color(40, 40, 46)
        self.border_color = pygame.Color(51, 51, 56)
        self.text_primary = pygame.Color(230, 230, 235)
        self.text_secondary = pygame.Color(176, 176, 184)
        self.text_muted = pygame.Color(130, 130, 140)
        self.accent = pygame.Color(59, 130, 246)
        self.accent_hover = pygame.Color(88, 155, 255)
        self.divider_color = pygame.Color(48, 48, 55)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_recent_files(self, files: List[RecentFile]) -> None:
        self.recent_files = files
        self._scroll = 0

    def set_example_files(self, files: List[ExampleFile]) -> None:
        self.example_files = files
        self._scroll = 0

    def set_scale(self, scale: float) -> None:
        if abs(scale - self.scale) < 1e-6:
            return
        self.scale = scale
        self._font_brand = None
        self._font_label = None
        self._font_button = None
        self._font_name = None
        self._font_small = None
        self._preview_cache.clear()

    def _s(self, value: float) -> int:
        return max(1, int(round(value * self.scale)))

    def handle_event(self, event: pygame.event.Event, region: Rect) -> bool:
        """Handle mouse events. Returns True if the event was consumed."""
        self._init_fonts()
        self._last_region = region

        if event.type == pygame.MOUSEWHEEL:
            return self._handle_wheel(event)

        geometry = self._compute_geometry(region)
        if event.type == pygame.MOUSEMOTION:
            self._mouse_pos = event.pos
            self._update_hover(event.pos, geometry)
            return False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._mouse_pos = event.pos
            self._update_hover(event.pos, geometry)
            return self._handle_click(event.pos, geometry)

        return False

    def draw(self, surface: pygame.Surface, region: Rect) -> None:
        """Draw the start page within the given region."""
        self._init_fonts()
        self._last_region = region
        geometry = self._compute_geometry(region)

        previous_clip = surface.get_clip()
        surface.set_clip(region.rect)
        pygame.draw.rect(surface, self.bg_color, region.rect)

        self._draw_action_buttons(surface, geometry)
        if self.recent_files:
            self._draw_section_label(surface, geometry.recent_label_y, "Recent")
            self._draw_recent_cards(surface, geometry)
        else:
            hint = self._font_label.render(
                "No recent documents yet", True, self.text_muted
            )
            surface.blit(hint, (self._s(self.MARGIN), geometry.recent_label_y))

        if self.example_files:
            self._draw_section_label(surface, geometry.samples_label_y, "Samples")
            self._draw_sample_cards(surface, geometry)

        if self._hovered_recent >= 0:
            self._draw_tooltip(surface, region, geometry)

        self._draw_scrollbar(surface, region, geometry)
        surface.set_clip(previous_clip)

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _columns(self, content_w: int) -> Tuple[int, int]:
        """Return (column count, card width) for the card grids."""
        gap = self._s(self.GAP)
        target = self._s(272)
        cols = max(1, (content_w + gap) // (target + gap))
        card_w = (content_w - gap * (cols - 1)) // cols
        return cols, card_w

    def _layout_grid(
        self, count: int, x: int, y: int, cols: int,
        card_w: int, card_h: int,
    ) -> Tuple[List[pygame.Rect], int]:
        """Lay out cards in a grid, returning the rects and bottom edge."""
        rects: List[pygame.Rect] = []
        gap = self._s(self.GAP)
        for index in range(count):
            row, col = divmod(index, cols)
            rects.append(pygame.Rect(
                x + col * (card_w + gap),
                y + row * (card_h + gap),
                card_w, card_h,
            ))
        rows = (count + cols - 1) // cols if count else 0
        bottom = y + rows * card_h + max(0, rows - 1) * gap
        return rects, bottom

    def _compute_geometry(self, region: Rect) -> _Geometry:
        margin = self._s(self.MARGIN)
        gap = self._s(self.GAP)
        content_w = max(self._s(240), region.w - 2 * margin)
        x = region.x + margin
        y = region.y + self._s(self.TOP_PADDING)

        button_w = min(self._s(self.BUTTON_W), (content_w - gap) // 2)
        button_h = self._s(self.BUTTON_H)
        new_button = pygame.Rect(x, y, button_w, button_h)
        open_button = pygame.Rect(x + button_w + gap, y, button_w, button_h)
        y += button_h + self._s(self.SECTION_GAP)

        recent_label_y = y
        y += self._s(self.LABEL_H) + self._s(10)

        cols, card_w = self._columns(content_w)
        preview_h = int(card_w * 0.48)
        recent_h = preview_h + self._s(80)
        sample_h = preview_h + self._s(58)

        recent_cards, y = self._layout_grid(
            len(self.recent_files), x, y, cols, card_w, recent_h
        )
        y += self._s(self.SECTION_GAP)

        samples_label_y = y
        sample_cards: List[pygame.Rect] = []
        if self.example_files:
            y += self._s(self.LABEL_H) + self._s(10)
            sample_cards, y = self._layout_grid(
                len(self.example_files), x, y, cols, card_w, sample_h
            )

        content_height = (
            y - (region.y + self._s(self.TOP_PADDING))
        ) + self._s(self.BOTTOM_PADDING)
        max_scroll = max(0, content_height - region.h)
        self._scroll = max(0, min(self._scroll, max_scroll))

        offset = self._scroll
        new_button.y -= offset
        open_button.y -= offset
        recent_label_y -= offset
        samples_label_y -= offset
        for card in recent_cards:
            card.y -= offset
        for card in sample_cards:
            card.y -= offset

        return _Geometry(
            new_button=new_button,
            open_button=open_button,
            recent_label_y=recent_label_y,
            samples_label_y=samples_label_y,
            recent_cards=recent_cards,
            sample_cards=sample_cards,
            content_height=content_height,
        )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _handle_wheel(self, event: pygame.event.Event) -> bool:
        if self._last_region is None:
            return False
        geometry = self._compute_geometry(self._last_region)
        max_scroll = max(0, geometry.content_height - self._last_region.h)
        if max_scroll <= 0:
            return False
        self._scroll = max(
            0, min(max_scroll, self._scroll - event.y * self._s(self.SCROLL_STEP))
        )
        return True

    def _update_hover(self, pos: Tuple[int, int], geometry: _Geometry) -> None:
        self._hovered_button = None
        self._hovered_recent = -1
        self._hovered_example = -1

        if geometry.new_button.collidepoint(pos):
            self._hovered_button = "new"
        elif geometry.open_button.collidepoint(pos):
            self._hovered_button = "open"

        for index, card in enumerate(geometry.recent_cards):
            if card.collidepoint(pos):
                self._hovered_recent = index
                break
        for index, card in enumerate(geometry.sample_cards):
            if card.collidepoint(pos):
                self._hovered_example = index
                break

    def _handle_click(self, pos: Tuple[int, int], geometry: _Geometry) -> bool:
        if geometry.new_button.collidepoint(pos):
            self.on_new_document()
            return True
        if geometry.open_button.collidepoint(pos):
            self.on_open_document()
            return True
        for index, card in enumerate(geometry.recent_cards):
            if card.collidepoint(pos):
                self.on_open_recent(self.recent_files[index].path)
                return True
        for index, card in enumerate(geometry.sample_cards):
            if card.collidepoint(pos):
                self.on_open_example(self.example_files[index].path)
                return True
        return False

    # ------------------------------------------------------------------
    # Fonts and drawing
    # ------------------------------------------------------------------

    def _init_fonts(self) -> None:
        if self._font_label is not None:
            return
        self._font_brand = pygame.font.SysFont("Segoe UI", self._s(16), bold=True)
        self._font_label = pygame.font.SysFont("Segoe UI", self._s(15))
        self._font_button = pygame.font.SysFont("Segoe UI", self._s(15))
        self._font_name = pygame.font.SysFont("Segoe UI", self._s(14))
        self._font_small = pygame.font.SysFont("Segoe UI", self._s(12))

    def _draw_action_buttons(
        self, surface: pygame.Surface, geometry: _Geometry
    ) -> None:
        self._draw_button(
            surface, geometry.new_button, "New Design", primary=True,
            hovered=self._hovered_button == "new",
        )
        self._draw_button(
            surface, geometry.open_button, "Open...", primary=False,
            hovered=self._hovered_button == "open",
        )

    def _draw_button(
        self, surface: pygame.Surface, rect: pygame.Rect,
        label: str, primary: bool, hovered: bool,
    ) -> None:
        if primary:
            bg = self.accent_hover if hovered else self.accent
            border = bg
        else:
            bg = self.card_hover if hovered else self.card_bg
            border = self.accent if hovered else self.border_color

        pygame.draw.rect(surface, bg, rect, border_radius=6)
        pygame.draw.rect(surface, border, rect, width=1, border_radius=6)

        icon_cx = rect.x + self._s(28)
        icon_cy = rect.centery
        if primary:
            self._draw_document_icon(surface, icon_cx, icon_cy, pygame.Color(255, 255, 255))
        else:
            self._draw_folder_icon(surface, icon_cx, icon_cy, self.text_primary)

        text_color = pygame.Color(255, 255, 255) if primary else self.text_primary
        text = self._font_button.render(label, True, text_color)
        surface.blit(text, text.get_rect(x=rect.x + self._s(48), centery=rect.centery))

    def _draw_document_icon(
        self, surface: pygame.Surface, cx: int, cy: int, color: pygame.Color
    ) -> None:
        page = pygame.Rect(cx - self._s(9), cy - self._s(13), self._s(18), self._s(26))
        pygame.draw.rect(surface, color, page, border_radius=2)
        for offset in (-6, 0, 6):
            pygame.draw.line(
                surface, self.accent if color == pygame.Color(255, 255, 255) else self.bg_color,
                (page.x + self._s(5), cy + self._s(offset)),
                (page.right - self._s(5), cy + self._s(offset)), 2,
            )

    def _draw_folder_icon(
        self, surface: pygame.Surface, cx: int, cy: int, color: pygame.Color
    ) -> None:
        folder = pygame.Rect(
            cx - self._s(12), cy - self._s(9), self._s(24), self._s(18)
        )
        pygame.draw.rect(surface, color, folder, width=2, border_radius=2)
        pygame.draw.line(
            surface, color,
            (folder.x + self._s(2), folder.y),
            (folder.x + self._s(10), folder.y), 2,
        )

    def _draw_section_label(
        self, surface: pygame.Surface, y: int, label: str
    ) -> None:
        text = self._font_label.render(label, True, self.text_secondary)
        surface.blit(text, (self._s(self.MARGIN), y))

    def _draw_recent_cards(self, surface: pygame.Surface, geometry: _Geometry) -> None:
        for index, rect in enumerate(geometry.recent_cards):
            self._draw_recent_card(
                surface, rect, self.recent_files[index],
                hovered=index == self._hovered_recent,
            )

    def _draw_recent_card(
        self, surface: pygame.Surface, rect: pygame.Rect,
        file: RecentFile, hovered: bool,
    ) -> None:
        self._draw_card_frame(surface, rect, hovered)
        preview_h = rect.h - self._s(80)
        self._blit_preview(surface, file.path, file.preview_kind,
                           file.preview_surface, rect, preview_h)

        info_y = rect.y + preview_h + self._s(10)
        pad = self._s(10)
        width = rect.w - self._s(20)
        name = self._fit_text(self._font_name, file.name, self.text_primary, width)
        surface.blit(name, (rect.x + pad, info_y))

        path = self._fit_text(self._font_small, file.path, self.text_secondary, width)
        surface.blit(path, (rect.x + pad, info_y + self._s(20)))

        status = file.opened or "missing"
        status_color = self.text_muted if file.opened else self.text_secondary
        status_surf = self._fit_text(self._font_small, status, status_color, width)
        surface.blit(status_surf, (rect.x + pad, info_y + self._s(38)))

    def _draw_sample_cards(self, surface: pygame.Surface, geometry: _Geometry) -> None:
        for index, rect in enumerate(geometry.sample_cards):
            self._draw_sample_card(
                surface, rect, self.example_files[index],
                hovered=index == self._hovered_example,
            )

    def _draw_sample_card(
        self, surface: pygame.Surface, rect: pygame.Rect,
        file: ExampleFile, hovered: bool,
    ) -> None:
        self._draw_card_frame(surface, rect, hovered)
        preview_h = rect.h - self._s(58)
        self._blit_preview(surface, file.path, file.preview_kind,
                           file.preview_surface, rect, preview_h)

        info_y = rect.y + preview_h + self._s(9)
        pad = self._s(10)
        width = rect.w - self._s(20)
        name = self._fit_text(self._font_name, file.name, self.text_primary, width)
        surface.blit(name, (rect.x + pad, info_y))

        desc = self._fit_text(self._font_small, file.description, self.text_muted, width)
        surface.blit(desc, (rect.x + pad, info_y + self._s(20)))

    def _draw_card_frame(
        self, surface: pygame.Surface, rect: pygame.Rect, hovered: bool
    ) -> None:
        bg = self.card_hover if hovered else self.card_bg
        pygame.draw.rect(surface, bg, rect, border_radius=6)
        border = self.accent if hovered else self.border_color
        pygame.draw.rect(surface, border, rect, width=1, border_radius=6)

    def _blit_preview(
        self, surface: pygame.Surface, key: str, kind: str,
        preview: Optional[pygame.Surface], card: pygame.Rect, preview_h: int,
    ) -> None:
        size = (card.w - 2, preview_h - 2)
        if preview is not None:
            image = pygame.transform.smoothscale(preview, size)
        else:
            cache_key = (key, size, kind)
            image = self._preview_cache.get(cache_key)
            if image is None:
                image = self._render_preview(size, kind)
                self._preview_cache[cache_key] = image
        surface.blit(image, (card.x + 1, card.y + 1))

    # ------------------------------------------------------------------
    # Preview generation
    # ------------------------------------------------------------------

    def _render_preview(self, size: Tuple[int, int], kind: str) -> pygame.Surface:
        width, height = max(8, size[0]), max(8, size[1])
        surface = pygame.Surface((width, height))
        surface.fill(pygame.Color(232, 232, 234))

        grid = pygame.Color(207, 207, 211)
        for x in range(0, width, 12):
            pygame.draw.line(surface, grid, (x, 0), (x, height))
        for y in range(0, height, 12):
            pygame.draw.line(surface, grid, (0, y), (width, y))

        self._draw_axes(surface)
        self._draw_shape(surface, kind, width // 2, height // 2)
        return surface

    def _draw_axes(self, surface: pygame.Surface) -> None:
        ox, oy = 14, surface.get_height() - 14
        pygame.draw.line(surface, pygame.Color(210, 70, 70), (ox, oy), (ox + 18, oy), 2)
        pygame.draw.line(surface, pygame.Color(70, 170, 70), (ox, oy), (ox, oy - 18), 2)
        pygame.draw.circle(surface, pygame.Color(70, 100, 220), (ox - 1, oy + 1), 2)

    def _draw_shape(
        self, surface: pygame.Surface, kind: str, cx: int, cy: int
    ) -> None:
        if kind == "flange":
            self._draw_cylinder(surface, cx, cy)
            return

        if kind == "bracket":
            self._draw_iso_box(surface, cx - 4, cy + 12, 40, 14, 8)
            self._draw_iso_box(surface, cx - 26, cy - 4, 11, 14, 30)
            return

        if kind == "hinge":
            self._draw_iso_box(surface, cx - 22, cy + 4, 20, 12, 9)
            self._draw_iso_box(surface, cx + 20, cy + 4, 20, 12, 9)
            pygame.draw.line(
                surface, pygame.Color(90, 90, 96),
                (cx - 2, cy - 6), (cx + 2, cy + 20), 3,
            )
            return

        params = {
            "plate": (44, 15, 9),
            "enclosure": (40, 18, 20),
            "vent": (46, 15, 8),
            "cube": (30, 17, 30),
        }
        w, d, h = params.get(kind, params["cube"])
        self._draw_iso_box(surface, cx, cy, w, d, h)

        if kind == "plate":
            self._draw_top_holes(surface, cx, cy, w, d, h)
        elif kind == "vent":
            self._draw_top_slots(surface, cx, cy, w, d, h)
        elif kind == "enclosure":
            self._draw_top_inset(surface, cx, cy, w, d, h)

    def _iso_faces(
        self, cx: int, cy: int, w: int, d: int, h: int
    ) -> Tuple[List[tuple], List[tuple], List[tuple]]:
        top_y = cy - d - h // 2
        top = [(cx, top_y), (cx + w, top_y + d), (cx, top_y + 2 * d), (cx - w, top_y + d)]
        left = [
            (cx - w, top_y + d), (cx, top_y + 2 * d),
            (cx, top_y + 2 * d + h), (cx - w, top_y + d + h),
        ]
        right = [
            (cx + w, top_y + d), (cx, top_y + 2 * d),
            (cx, top_y + 2 * d + h), (cx + w, top_y + d + h),
        ]
        return top, left, right

    def _draw_iso_box(
        self, surface: pygame.Surface, cx: int, cy: int,
        w: int, d: int, h: int,
        colors: Optional[Tuple[pygame.Color, pygame.Color, pygame.Color]] = None,
    ) -> None:
        top_face, left_face, right_face = self._iso_faces(cx, cy, w, d, h)
        if colors is None:
            colors = (
                pygame.Color(198, 198, 202),
                pygame.Color(158, 158, 164),
                pygame.Color(128, 128, 134),
            )
        edge = pygame.Color(78, 78, 84)
        for face, color in zip((top_face, left_face, right_face), colors):
            pygame.draw.polygon(surface, color, face)
            pygame.draw.polygon(surface, edge, face, 2)

    def _draw_top_holes(
        self, surface: pygame.Surface, cx: int, cy: int, w: int, d: int, h: int
    ) -> None:
        top_y = cy - d - h // 2
        for dx in (-w // 2, w // 2):
            hole = pygame.Rect(0, 0, 9, 5)
            hole.center = (cx + dx, top_y + d)
            pygame.draw.ellipse(surface, pygame.Color(110, 110, 116), hole)

    def _draw_top_slots(
        self, surface: pygame.Surface, cx: int, cy: int, w: int, d: int, h: int
    ) -> None:
        top_y = cy - d - h // 2
        for i in range(-2, 3):
            offset = i * 10
            start = (cx + offset - 7, top_y + d + offset // 3)
            end = (cx + offset + 7, top_y + d + offset // 3)
            pygame.draw.line(surface, pygame.Color(120, 120, 126), start, end, 2)

    def _draw_top_inset(
        self, surface: pygame.Surface, cx: int, cy: int, w: int, d: int, h: int
    ) -> None:
        top_y = cy - d - h // 2
        inset = 7
        points = [
            (cx, top_y + inset), (cx + w - inset, top_y + d),
            (cx, top_y + 2 * d - inset), (cx - w + inset, top_y + d),
        ]
        pygame.draw.polygon(surface, pygame.Color(172, 172, 178), points)
        pygame.draw.polygon(surface, pygame.Color(78, 78, 84), points, 2)

    def _draw_cylinder(self, surface: pygame.Surface, cx: int, cy: int) -> None:
        w, d, h = 38, 15, 12
        top_y = cy - d - h // 2
        edge = pygame.Color(78, 78, 84)

        pygame.draw.rect(
            surface, pygame.Color(150, 150, 156),
            (cx - w, top_y + d, 2 * w, h),
        )
        pygame.draw.ellipse(
            surface, pygame.Color(130, 130, 136),
            (cx - w, top_y + d + h, 2 * w, 2 * d),
        )
        pygame.draw.ellipse(
            surface, pygame.Color(198, 198, 202), (cx - w, top_y, 2 * w, 2 * d)
        )
        hole = pygame.Rect(0, 0, w, d)
        hole.center = (cx, top_y + d)
        pygame.draw.ellipse(surface, pygame.Color(120, 120, 126), hole)
        pygame.draw.ellipse(surface, edge, (cx - w, top_y, 2 * w, 2 * d), 2)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _draw_tooltip(
        self, surface: pygame.Surface, region: Rect, geometry: _Geometry
    ) -> None:
        card = geometry.recent_cards[self._hovered_recent]
        path = self.recent_files[self._hovered_recent].path
        text = self._font_small.render(path, True, self.text_primary)
        pad = self._s(8)
        width = text.get_width() + pad * 2
        height = text.get_height() + pad * 2
        margin = self._s(4)
        x = max(region.x + margin, min(card.x + margin, region.right - width - margin))
        y = card.bottom + self._s(6)
        if y + height > region.bottom - margin:
            y = card.y - height - self._s(6)
        box = pygame.Rect(x, y, width, height)
        pygame.draw.rect(surface, pygame.Color(40, 40, 46), box, border_radius=4)
        pygame.draw.rect(surface, self.border_color, box, width=1, border_radius=4)
        surface.blit(text, (box.x + pad, box.y + pad))

    def _draw_scrollbar(
        self, surface: pygame.Surface, region: Rect, geometry: _Geometry
    ) -> None:
        max_scroll = geometry.content_height - region.h
        if max_scroll <= 0:
            return
        track_h = region.h - self._s(16)
        track_y = region.y + self._s(8)
        thumb_h = max(self._s(32), int(track_h * region.h / geometry.content_height))
        thumb_y = track_y + int(
            (track_h - thumb_h) * (self._scroll / max_scroll)
        )
        x = region.right - self._s(8)
        bar_w = self._s(4)
        pygame.draw.rect(
            surface, pygame.Color(45, 45, 52),
            pygame.Rect(x, track_y, bar_w, track_h), border_radius=2,
        )
        pygame.draw.rect(
            surface, pygame.Color(90, 90, 100),
            pygame.Rect(x, thumb_y, bar_w, thumb_h), border_radius=2,
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
