class solverError(BaseException):
    pass

class point2d:
    """A mutable 2D point that also behaves like a two-item tuple.

    Sketch geometry stores real :class:`point2d` objects, while rendering,
    serialisation, and the solver still read them with tuple syntax.
    """

    __slots__ = ("x", "y")

    def __init__(self, point: tuple[float, float]):
        if isinstance(point, point2d):
            self.x = point.x
            self.y = point.y
            return
        self.x = float(point[0])
        self.y = float(point[1])

    def __iter__(self):
        yield self.x
        yield self.y

    def __len__(self) -> int:
        return 2

    def __getitem__(self, index):
        return (self.x, self.y)[index]

    def __eq__(self, other) -> bool:
        if isinstance(other, point2d):
            return self.x == other.x and self.y == other.y
        if isinstance(other, (tuple, list)) and len(other) == 2:
            return self.x == other[0] and self.y == other[1]
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.x, self.y))

    def __repr__(self) -> str:
        return f"point2d({self.x!r}, {self.y!r})"

    def copy(self) -> "point2d":
        return point2d(self)

    def as_tuple(self) -> tuple[float, float]:
        return self.x, self.y

    def move(self, amount: tuple[float, float]) -> None:
        self.x += amount[0]
        self.y += amount[1]

    def setPos(self, pos: tuple[float, float]) -> None:
        self.x = float(pos[0])
        self.y = float(pos[1])

    def set_pos(self, pos: tuple[float, float]) -> None:
        self.setPos(pos)

class line2d:
    """A mutable 2D line that also behaves like a two-item tuple.

    Sketch geometry exposes real :class:`line2d` objects, while rendering,
    selection, and serialisation still read them with tuple syntax.
    """

    __slots__ = ("p1", "p2")

    def __init__(self, points: tuple[point2d, point2d]):
        if isinstance(points, line2d):
            self.p1 = points.p1
            self.p2 = points.p2
            return
        self.p1 = (
            points[0] if isinstance(points[0], point2d)
            else point2d(points[0])
        )
        self.p2 = (
            points[1] if isinstance(points[1], point2d)
            else point2d(points[1])
        )

    def __iter__(self):
        yield self.p1
        yield self.p2

    def __len__(self) -> int:
        return 2

    def __getitem__(self, index):
        return (self.p1, self.p2)[index]

    def __eq__(self, other) -> bool:
        if isinstance(other, line2d):
            return self.p1 == other.p1 and self.p2 == other.p2
        if isinstance(other, (tuple, list)) and len(other) == 2:
            return self.p1 == other[0] and self.p2 == other[1]
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.p1, self.p2))

    def __repr__(self) -> str:
        return f"line2d({self.p1!r}, {self.p2!r})"

    def copy(self) -> "line2d":
        return line2d((self.p1.copy(), self.p2.copy()))

    def as_tuple(self) -> tuple[point2d, point2d]:
        return self.p1, self.p2

    def move(self, amount: tuple[float, float]) -> None:
        self.p1.move(amount)
        self.p2.move(amount)

class circle2d:
    """A mutable 2D circle defined by its midpoint and diameter."""

    __slots__ = ("midPoint", "diameter")

    def __init__(self, midPoint: point2d, diameter: float):
        self.midPoint = (
            midPoint if isinstance(midPoint, point2d)
            else point2d(midPoint)
        )
        self.diameter = float(diameter)

    @property
    def radius(self) -> float:
        return self.diameter / 2.0

    def change_diameter(self, new_diameter: float) -> None:
        self.diameter = float(new_diameter)

    def __repr__(self) -> str:
        return f"circle2d({self.midPoint!r}, {self.diameter!r})"

    def copy(self) -> "circle2d":
        return circle2d(self.midPoint.copy(), self.diameter)
        
