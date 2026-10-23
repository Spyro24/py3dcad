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
    def __init__(self, points: tuple[point2d, point2d]):
        pass
        
