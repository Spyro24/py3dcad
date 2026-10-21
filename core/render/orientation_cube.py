"""Small orientation cube drawn in the corner of the viewport."""

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Tuple

import pygame

from .camera import OrbitCamera, Point3

if TYPE_CHECKING:
    from .scene import ScenePalette


@dataclass(frozen=True)
class _CubeFace:
    normal: Point3
    vertices: Tuple[Point3, ...]
    label: str
    color_key: str


# Cube vertices: (±1, ±1, ±1) with winding such that normal points outward
# Cube vertices indexed:
# 0: (-1, -1, -1)  1: (1, -1, -1)  2: (1, 1, -1)  3: (-1, 1, -1)
# 4: (-1, -1, 1)   5: (1, -1, 1)   6: (1, 1, 1)   7: (-1, 1, 1)

# Face vertices in CCW order when viewed from outside
# +X (RIGHT): vertices 1, 5, 6, 2
# -X (LEFT):  vertices 3, 7, 4, 0
# +Y (FRONT): vertices 5, 1, 2, 6
# -Y (BACK):  vertices 0, 3, 7, 4
# +Z (TOP):   vertices 4, 5, 6, 7
# -Z (BOTTOM): vertices 0, 1, 5, 4 (viewed from below)

CUBE_FACES = (
    # TOP (+Z)
    _CubeFace(
        (0, 0, 1),
        ((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)),
        "TOP",
        "cube_top",
    ),
    # BOTTOM (-Z)
    _CubeFace(
        (0, 0, -1),
        ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1)),
        "BOTTOM",
        "cube_bottom",
    ),
    # RIGHT (+X)
    _CubeFace(
        (1, 0, 0),
        ((1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)),
        "RIGHT",
        "cube_side",
    ),
    # LEFT (-X)
    _CubeFace(
        (-1, 0, 0),
        ((-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)),
        "LEFT",
        "cube_side",
    ),
    # FRONT (+Y)
    _CubeFace(
        (0, 1, 0),
        ((1, 1, -1), (-1, 1, -1), (-1, 1, 1), (1, 1, 1)),
        "FRONT",
        "cube_side_dark",
    ),
    # BACK (-Y)
    _CubeFace(
        (0, -1, 0),
        ((-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)),
        "BACK",
        "cube_side_dark",
    ),
)


class OrientationCube:
    """Draws a compact, camera-aligned cube in the top-right corner."""

    def __init__(self) -> None:
        self.ui_scale = 1.0
        self._font: Optional[pygame.font.Font] = None
        self._font_tiny: Optional[pygame.font.Font] = None

    def set_scale(self, scale: float) -> None:
        if abs(scale - self.ui_scale) < 1e-6:
            return
        self.ui_scale = scale
        self._font = None
        self._font_tiny = None

    def _s(self, value: float) -> int:
        return max(1, int(round(value * self.ui_scale)))

    def _init_fonts(self) -> None:
        if self._font is not None:
            return
        self._font = pygame.font.SysFont(
            "Segoe UI", max(7, self._s(8)), bold=True
        )
        self._font_tiny = pygame.font.SysFont(
            "Segoe UI", max(6, self._s(7)), bold=True
        )

    def draw(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        camera: OrbitCamera,
        palette: "ScenePalette",
    ) -> None:
        if rect.w < self._s(150) or rect.h < self._s(120):
            return
        self._init_fonts()

        size = self._s(92)
        scale = size / 3.95
        half_w = size * 0.36
        half_h = size * 0.42
        margin = self._s(12)
        center = (
            rect.right - margin - half_w,
            rect.top + margin + half_h,
        )

        # Use the camera's view direction for face visibility
        view_x, view_y, view_z = camera.view_direction()

        visible = []
        for face in CUBE_FACES:
            # Backface culling: only render faces facing the camera
            facing = (
                face.normal[0] * view_x
                + face.normal[1] * view_y
                + face.normal[2] * view_z
            )
            if facing <= 0.01:
                continue
            
            # Compute face center depth for proper depth sorting
            face_center = (
                sum(v[0] for v in face.vertices) / 4.0,
                sum(v[1] for v in face.vertices) / 4.0,
                sum(v[2] for v in face.vertices) / 4.0,
            )
            depth = (
                face_center[0] * view_x
                + face_center[1] * view_y
                + face_center[2] * view_z
            )
            
            points = [
                self._project(vertex, center, camera, scale)
                for vertex in face.vertices
            ]
            color = getattr(palette, face.color_key)
            visible.append((depth, facing, points, face, color))

        # Sort by depth (farther first for painter's algorithm)
        visible.sort(key=lambda item: item[0], reverse=True)
        edge_width = max(1, self._s(1))
        for _, _, points, _, color in visible:
            pygame.draw.polygon(surface, color, points)
        for _, _, points, _, _ in visible:
            pygame.draw.polygon(surface, palette.cube_edge, points, edge_width)

        for _, facing, points, face, _ in visible:
            if facing < 0.28:
                continue
            label = self._font.render(face.label, True, palette.cube_text)
            center_x = sum(point[0] for point in points) / len(points)
            center_y = sum(point[1] for point in points) / len(points)
            surface.blit(
                label,
                label.get_rect(
                    center=(int(center_x), int(center_y))
                ),
            )

        self._draw_axes(surface, center, camera, palette, size)

    @staticmethod
    def _project(
        point: Point3,
        center: Tuple[float, float],
        camera: OrbitCamera,
        scale: float,
    ) -> Tuple[float, float]:
        """Project a point using the same projection as the main camera."""
        x, y, z = point
        sin_yaw = math.sin(camera.yaw)
        cos_yaw = math.cos(camera.yaw)
        sin_pitch = math.sin(camera.pitch)
        cos_pitch = math.cos(camera.pitch)
        # Match camera.project(): screen_x = cx + (-x*sin_yaw + y*cos_yaw) * scale
        # screen_y = cy - (-x*cos_yaw*sin_pitch - y*sin_yaw*sin_pitch + z*cos_pitch) * scale
        screen_x = center[0] + (-x * sin_yaw + y * cos_yaw) * scale
        screen_y = center[1] - (
            -x * cos_yaw * sin_pitch - y * sin_yaw * sin_pitch + z * cos_pitch
        ) * scale
        return screen_x, screen_y

    def _draw_axes(
        self,
        surface: pygame.Surface,
        center: Tuple[float, float],
        camera: OrbitCamera,
        palette: "ScenePalette",
        size: int,
    ) -> None:
        origin = (
            center[0] - size * 0.44,
            center[1] + size * 0.43,
        )
        length = size * 0.19

        # Project world axes using the same projection as the camera
        for axis, color, label in (
            ((1, 0, 0), palette.x_axis, "X"),
            ((0, 1, 0), palette.y_axis, "Y"),
            ((0, 0, 1), palette.z_axis, "Z"),
        ):
            end = self._project(
                (axis[0] * length, axis[1] * length, axis[2] * length),
                origin, camera, 1.0
            )
            pygame.draw.line(surface, color, origin, end, max(1, self._s(1)))
            text = self._font_tiny.render(label, True, color)
            text_center = (
                int(end[0] + (end[0] - origin[0]) * 0.3),
                int(end[1] + (end[1] - origin[1]) * 0.3),
            )
            surface.blit(text, text.get_rect(center=text_center))

    def set_scale(self, scale: float) -> None:
        if abs(scale - self.ui_scale) < 1e-6:
            return
        self.ui_scale = scale
        self._font = None
        self._font_tiny = None

    def _s(self, value: float) -> int:
        return max(1, int(round(value * self.ui_scale)))

    def _init_fonts(self) -> None:
        if self._font is not None:
            return
        self._font = pygame.font.SysFont(
            "Segoe UI", max(7, self._s(8)), bold=True
        )
        self._font_tiny = pygame.font.SysFont(
            "Segoe UI", max(6, self._s(7)), bold=True
        )