"""Orbit camera and orthographic projection for PY3DCAD."""

import math
from typing import Optional, Sequence, Tuple

from ..sketch import PlaneFrame, PlaneLike, plane_frame

Point2 = Tuple[float, float]
Point3 = Tuple[float, float, float]

DEFAULT_YAW = math.radians(45)
DEFAULT_PITCH = math.atan(1 / math.sqrt(2))
PROJECTION_SCALE = math.sqrt(1.5)
ORBIT_SPEED = 0.007
MIN_PITCH = math.radians(-89)
MAX_PITCH = math.radians(89)
MIN_ZOOM = 0.5
MAX_ZOOM = 30.0


def clamp(value: float, low: float, high: float) -> float:
    """Return value constrained to the inclusive range [low, high]."""
    return max(low, min(high, value))


class OrbitCamera:
    """Orthographic camera orbiting the Z=0 sketch plane.

    The default yaw/pitch and projection scale reproduce the original
    isometric view exactly, while allowing the user to orbit freely.
    """

    def __init__(self) -> None:
        self.yaw = DEFAULT_YAW
        self.pitch = DEFAULT_PITCH
        self.zoom = 3.2
        self.pan_x = 0.0
        self.pan_y = 0.0

    def project(self, point: Sequence[float], center: Point2) -> Point2:
        """Project a world-space point to screen pixels."""
        x, y, z = point
        cx = center[0] + self.pan_x
        cy = center[1] + self.pan_y
        sin_yaw = math.sin(self.yaw)
        cos_yaw = math.cos(self.yaw)
        sin_pitch = math.sin(self.pitch)
        cos_pitch = math.cos(self.pitch)
        scale = PROJECTION_SCALE * self.zoom
        # Camera right vector R = (-sin_yaw, cos_yaw, 0)
        # Camera up vector U = (-cos_yaw*sin_pitch, -sin_yaw*sin_pitch, cos_pitch)
        # screen_x = (P - center) · R = -x*sin_yaw + y*cos_yaw
        # screen_y = (P - center) · U = -x*cos_yaw*sin_pitch - y*sin_yaw*sin_pitch + z*cos_pitch
        screen_x = cx + (-x * sin_yaw + y * cos_yaw) * scale
        screen_y = cy + (
            - (x * cos_yaw + y * sin_yaw) * sin_pitch + z * cos_pitch
        ) * scale
        return screen_x, screen_y

    def unproject_plane(self, pos: Sequence[float], center: Point2) -> Point2:
        """Map a screen position onto the Z=0 sketch plane."""
        cx = center[0] + self.pan_x
        cy = center[1] + self.pan_y
        sin_pitch = math.sin(self.pitch)
        if abs(sin_pitch) < 1e-9:
            return (0.0, 0.0)

        scale = PROJECTION_SCALE * self.zoom
        # screen_x = -x*sin_yaw + y*cos_yaw
        # screen_y = -x*cos_yaw*sin_pitch - y*sin_yaw*sin_pitch
        # Solve for x,y given screen_x, screen_y:
        # [screen_x]   [ -sin_yaw   cos_yaw ] [x]
        # [screen_y] = [ -cos_yaw*sin_pitch  -sin_yaw*sin_pitch ] [y]
        # 
        # Determinant = sin_yaw*sin_yaw*sin_pitch + cos_yaw*cos_yaw*sin_pitch = sin_pitch
        # x = (-screen_x*sin_yaw*sin_pitch - screen_y*cos_yaw) / sin_pitch
        # y = (screen_x*cos_yaw*sin_pitch - screen_y*sin_yaw) / sin_pitch
        right = (pos[0] - cx) / scale
        forward = (pos[1] - cy) / scale
        sin_yaw = math.sin(self.yaw)
        cos_yaw = math.cos(self.yaw)
        x = -right * sin_yaw - forward * cos_yaw / sin_pitch
        y = right * cos_yaw / sin_pitch - forward * sin_yaw / sin_pitch
        return (x, y)

    def unproject_on_plane(
        self,
        pos: Sequence[float],
        center: Point2,
        plane: PlaneLike = "XY",
    ) -> Optional[Point2]:
        """Map a screen position onto a sketch plane.

        Returns local (u, v) coordinates for the sketch plane, or ``None``
        when the plane is edge-on and has no unique screen intersection.
        """
        frame = plane_frame(plane)
        origin, u_axis, v_axis, normal = (
            frame.origin, frame.u, frame.v, frame.normal,
        )

        # Camera basis vectors (orthonormal), matching the projection matrix.
        # R: world direction mapping to +screen X (right) = (-sin_yaw, cos_yaw, 0)
        # U: world direction mapping to +screen Y (up) = (-cos_yaw*sin_pitch, -sin_yaw*sin_pitch, cos_pitch)
        # V: view direction (world direction from scene to camera) = (cos_yaw*cos_pitch, sin_yaw*cos_pitch, sin_pitch)
        sin_yaw = math.sin(self.yaw)
        cos_yaw = math.cos(self.yaw)
        sin_pitch = math.sin(self.pitch)
        cos_pitch = math.cos(self.pitch)
        V = (cos_yaw * cos_pitch, sin_yaw * cos_pitch, sin_pitch)
        R = (-sin_yaw, cos_yaw, 0.0)
        U = (
            -cos_yaw * sin_pitch,
            -sin_yaw * sin_pitch,
            cos_pitch,
        )

        scale = PROJECTION_SCALE * self.zoom
        cx = center[0] + self.pan_x
        cy = center[1] + self.pan_y

        # Point on the image plane (orthographic: all rays parallel to V).
        # P0 = R * ((sx - cx) / scale) + U * ((sy - cy) / scale)
        rx = (pos[0] - cx) / scale
        uy = (pos[1] - cy) / scale
        p0 = (
            R[0] * rx + U[0] * uy,
            R[1] * rx + U[1] * uy,
            R[2] * rx + U[2] * uy,
        )

        # Intersect ray P0 + t*V with the plane.
        denom = normal[0] * V[0] + normal[1] * V[1] + normal[2] * V[2]
        if abs(denom) < 1e-9:
            return None
        d_plane = normal[0] * origin[0] + normal[1] * origin[1] + normal[2] * origin[2]
        d_p0 = normal[0] * p0[0] + normal[1] * p0[1] + normal[2] * p0[2]
        t = (d_plane - d_p0) / denom
        point = (
            p0[0] + V[0] * t,
            p0[1] + V[1] * t,
            p0[2] + V[2] * t,
        )

        # Convert to local (u, v) coordinates.
        dx = point[0] - origin[0]
        dy = point[1] - origin[1]
        dz = point[2] - origin[2]
        return (
            u_axis[0] * dx + u_axis[1] * dy + u_axis[2] * dz,
            v_axis[0] * dx + v_axis[1] * dy + v_axis[2] * dz,
        )

    def depth(self, points: Sequence[Sequence[float]]) -> float:
        """Average camera-depth of a polygon; larger is closer to the camera.

        view_direction points from camera to scene. Points farther along the view
        direction are farther from the camera. Negate so larger depth = closer.
        """
        view_x, view_y, view_z = self.view_direction()
        return -sum(
            point[0] * view_x + point[1] * view_y + point[2] * view_z
            for point in points
        ) / max(1, len(points))

    def view_direction(self) -> Point3:
        """Unit vector pointing from the scene toward the camera."""
        cos_pitch = math.cos(self.pitch)
        return (
            math.cos(self.yaw) * cos_pitch,
            math.sin(self.yaw) * cos_pitch,
            math.sin(self.pitch),
        )

    def orbit(self, dx: float, dy: float) -> None:
        """Rotate the camera by a mouse drag in pixels."""
        self.yaw = (self.yaw + dx * ORBIT_SPEED) % (2 * math.pi)
        self.pitch = clamp(
            self.pitch + dy * ORBIT_SPEED, MIN_PITCH, MAX_PITCH
        )

    def pan(self, dx: float, dy: float) -> None:
        """Translate the view by a mouse drag in pixels."""
        self.pan_x += dx
        self.pan_y += dy

    def zoom_by(self, factor: float) -> None:
        """Scale the view by a positive factor within the allowed range."""
        if factor <= 0:
            return
        self.zoom = clamp(self.zoom * factor, MIN_ZOOM, MAX_ZOOM)

    def set_zoom(self, value: float) -> None:
        self.zoom = clamp(value, MIN_ZOOM, MAX_ZOOM)

    def align_to_plane(self, frame: PlaneFrame, scale: float = 1.0, zoom: Optional[float] = None) -> None:
        """Orient the camera to look directly at a sketch plane.

        The view direction points opposite to the plane's normal (front view:
        camera on the positive side of the plane looking toward the origin).
        The camera's pan is set so the plane's origin appears at the screen centre.
        If ``zoom`` is provided it is used directly; otherwise the current zoom is kept.
        """
        normal = frame.normal
        u_axis = frame.u

        # Desired view direction points opposite to the plane normal
        # (camera on the positive side looking toward the plane).
        view_x, view_y, view_z = -normal[0], -normal[1], -normal[2]

        # Clamp view_z to avoid exactly +/-1 which would make pitch +/-90 and
        # lose yaw definition.
        view_z = clamp(view_z, -0.999999, 0.999999)
        self.pitch = math.asin(view_z)

        cos_pitch = math.cos(self.pitch)
        # If the view is nearly straight up/down (horizontal plane), the yaw
        # is ill-defined from the view direction alone.  Use the sketch's U axis
        # projected onto the horizontal plane to pick a yaw that puts U to the
        # right on screen.
        if abs(view_z) > 0.999:
            ux, uy = u_axis[0], u_axis[1]
            horiz_len = math.hypot(ux, uy)
            if horiz_len < 1e-6:
                self.yaw = 0.0
            else:
                # Camera right = (-sin_yaw, cos_yaw).  We want it to align with
                # the horizontal projection of u_axis.
                self.yaw = math.atan2(-ux / horiz_len, uy / horiz_len)
        else:
            self.yaw = math.atan2(view_y / cos_pitch, view_x / cos_pitch)

        # Center the plane origin on screen.
        self.pan_x = 0.0
        self.pan_y = 0.0

        if zoom is not None:
            self.zoom = clamp(zoom, MIN_ZOOM, MAX_ZOOM)
        # else: keep current zoom
