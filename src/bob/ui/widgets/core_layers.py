"""The layers that compose B.O.B.'s core.

Each layer is a ``QGraphicsItem`` in a shared scene. The scene is exactly the
size of the core, so nothing behind it is ever repainted.

**The performance contract.** Layers do not own timers. The view advances them
all from one clock via :meth:`CoreLayer.advance`, which returns ``True`` only if
the layer's appearance actually changed. The view then calls ``update()`` on
just those layers. Layers whose shape is fixed and which only rotate set a
device-coordinate cache, so spinning them is a cached-pixmap blit rather than a
re-render.

Visual identity: an orrery. Partial orbital arcs at different inclinations
around a dark aperture. Light comes from edges, never from a bloom filter.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from bob.ui.visual import CoreVisual

TWO_PI = 2.0 * math.pi


def _midpoint(a: QPointF, b: QPointF) -> QPointF:
    return QPointF((a.x() + b.x()) / 2.0, (a.y() + b.y()) / 2.0)


def _qcolor(hex_value: str, alpha: float = 1.0) -> QColor:
    color = QColor(hex_value)
    color.setAlphaF(max(0.0, min(1.0, alpha)))
    return color


class CoreLayer(QGraphicsItem):
    """Base class: knows the current visual, and whether it needs a repaint."""

    def __init__(self, radius: float) -> None:
        super().__init__()
        self._radius = radius
        self._visual = CoreVisual()
        self._phase = 0.0
        self._level = 0.0

    # -- geometry --------------------------------------------------------

    def boundingRect(self) -> QRectF:
        r = self._radius
        return QRectF(-r, -r, 2 * r, 2 * r)

    def set_radius(self, radius: float) -> None:
        self.prepareGeometryChange()
        self._radius = radius

    # -- driven by the view ----------------------------------------------

    def set_visual(self, visual: CoreVisual) -> None:
        self._visual = visual

    def set_level(self, level: float) -> None:
        """Audio level, 0..1. Only the waveform layer reacts."""
        self._level = level

    def advance_phase(self, elapsed_s: float, dt: float) -> bool:
        """Advance animation. Return whether a repaint is needed."""
        self._phase = elapsed_s
        return False


class HaloLayer(CoreLayer):
    """Soft ambient field behind everything. Breathes; never sharp."""

    def __init__(self, radius: float) -> None:
        super().__init__(radius)
        self._scale = 1.0
        self.setZValue(0)

    def advance_phase(self, elapsed_s: float, dt: float) -> bool:
        v = self._visual
        if v.breath_depth <= 0.0 or v.breath_period_s <= 0.0:
            new_scale = 1.0
        else:
            wave = math.sin(TWO_PI * elapsed_s / v.breath_period_s)
            new_scale = 1.0 + v.breath_depth * wave
        # Repaint only on a visible change — sub-pixel breathing is invisible.
        if abs(new_scale - self._scale) < 0.002:
            return False
        self._scale = new_scale
        return True

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        v = self._visual
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self._radius * self._scale
        gradient = QRadialGradient(QPointF(0, 0), r)
        gradient.setColorAt(0.0, _qcolor(v.accent, 0.09 * v.energy))
        gradient.setColorAt(0.45, _qcolor(v.accent, 0.05 * v.energy))
        gradient.setColorAt(1.0, _qcolor(v.accent, 0.0))
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(0, 0), r, r)


class OrbitLayer(CoreLayer):
    """One orbital arc, drawn as an inclined ellipse.

    Only a *portion* of each ellipse is stroked, so the result reads as an
    instrument's armature rather than as a loading spinner. The shape never
    changes — only ``setRotation`` — so a device-coordinate cache makes the
    animation nearly free.
    """

    def __init__(
        self,
        radius: float,
        *,
        index: int,
        inclination: float,
        span_deg: float,
        squash: float,
    ) -> None:
        super().__init__(radius)
        self._index = index
        self._inclination = inclination
        self._span = span_deg
        self._squash = squash
        self._angle = 0.0
        self.setZValue(10 + index)
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)

    @property
    def inclination(self) -> float:
        return self._inclination

    def advance_phase(self, elapsed_s: float, dt: float) -> bool:
        speed = self._visual.orbit_speeds[self._index]
        if speed == 0.0:
            return False
        self._angle = (self._angle + speed * dt * 360.0) % 360.0
        # Rotation is a transform, not a repaint: the cached pixmap is reused.
        self.setRotation(self._inclination + self._angle)
        return False

    def point_at(self, t: float) -> QPointF:
        """Position on this orbit at parameter ``t`` (0..1), in item coordinates."""
        theta = TWO_PI * t
        rx = self._radius
        ry = self._radius * self._squash
        x = rx * math.cos(theta)
        y = ry * math.sin(theta)
        rot = math.radians(self._inclination + self._angle)
        return QPointF(
            x * math.cos(rot) - y * math.sin(rot),
            x * math.sin(rot) + y * math.cos(rot),
        )

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        v = self._visual
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rx = self._radius
        ry = self._radius * self._squash
        rect = QRectF(-rx, -ry, 2 * rx, 2 * ry)

        # A gradient along the arc so it fades out at the tail — this is what
        # gives the ring direction without drawing an arrowhead.
        gradient = QLinearGradient(-rx, 0, rx, 0)
        base_alpha = 0.16 + 0.62 * v.energy
        gradient.setColorAt(0.0, _qcolor(v.accent, 0.0))
        gradient.setColorAt(0.5, _qcolor(v.accent, base_alpha))
        gradient.setColorAt(1.0, _qcolor(v.accent, base_alpha * 0.15))

        painter.setBrush(Qt.BrushStyle.NoBrush)

        # The complete ring, very faint: the armature is always there.
        painter.setPen(QPen(_qcolor(v.accent, 0.06 + 0.10 * v.energy), 1.0))
        painter.drawEllipse(rect)

        # The lit portion, which is what actually rotates.
        pen = QPen(QBrush(gradient), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        # Qt angles are in 1/16 degree.
        painter.drawArc(rect, 0, int(self._span * 16))


class NodeLayer(CoreLayer):
    """Data points riding the orbits.

    Count scales with ``node_density`` so THINKING visibly has more going on
    than IDLE. Node positions are recomputed per frame, but there are at most a
    couple of dozen of them and each is a 2px dot.
    """

    MAX_NODES = 22

    def __init__(self, radius: float, orbits: list[OrbitLayer]) -> None:
        super().__init__(radius)
        self._orbits = orbits
        self._offsets = [
            (i * 0.618_033) % 1.0 for i in range(self.MAX_NODES)
        ]  # golden-ratio spacing avoids visible clumping
        self.setZValue(30)

    def advance_phase(self, elapsed_s: float, dt: float) -> bool:
        return self._visual.node_density > 0.0 and self._visual.node_brightness > 0.0

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        v = self._visual
        count = int(self.MAX_NODES * v.node_density)
        if count <= 0 or not self._orbits:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        for i in range(count):
            orbit = self._orbits[i % len(self._orbits)]
            speed = v.orbit_speeds[i % len(v.orbit_speeds)]
            t = (self._offsets[i] + self._phase * speed * 0.5) % 1.0
            point = orbit.point_at(t)
            # Nodes on the far side of the inclined ellipse read as dimmer.
            depth = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(TWO_PI * t))
            size = 1.1 + 1.4 * depth
            painter.setBrush(_qcolor(v.accent, v.node_brightness * depth))
            painter.drawEllipse(point, size, size)


class ApertureLayer(CoreLayer):
    """The signature: a mechanical iris over a dark well.

    Deliberately *not* a glowing sphere. Six blades meet at a hexagonal opening;
    the light in the middle of B.O.B. is the bright **edge** where those blades
    meet, plus a faint core seen through the gap. ``aperture`` retracts the
    blades, so OFFLINE is sealed shut and WAKE_DETECTED is wide open.

    The hexagonal opening is what makes this read as an instrument rather than
    as an orb, so the geometry is kept crisp: straight edges, visible seams
    between blades, and a hard rim.
    """

    BLADES = 6
    _STEP = 360.0 / BLADES

    def __init__(self, radius: float) -> None:
        super().__init__(radius)
        self._open = 0.0
        self._spin = 0.0
        self.setZValue(40)

    def advance_phase(self, elapsed_s: float, dt: float) -> bool:
        v = self._visual
        # Blades ease toward the target rather than snapping to it.
        self._open += (v.aperture - self._open) * min(1.0, dt * 6.0)
        # Blades counter-rotate slightly as they open, like a real iris.
        self._spin = (self._spin + dt * 6.0 * v.energy) % 360.0
        return True

    def _hexagon(self, radius: float) -> QPainterPath:
        path = QPainterPath()
        for i in range(self.BLADES):
            angle = math.radians(i * self._STEP + self._spin)
            point = QPointF(radius * math.cos(angle), radius * math.sin(angle))
            if i == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        path.closeSubpath()
        return path

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        v = self._visual
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self._radius

        closed_r = r * 0.10
        open_r = r * 0.62
        gap_r = closed_r + (open_r - closed_r) * self._open

        # 1. The blade plate: a dark disc the blades are cut from.
        plate = QRadialGradient(QPointF(0, 0), r)
        plate.setColorAt(0.0, QColor(9, 13, 22, 255))
        plate.setColorAt(0.72, QColor(6, 9, 16, 255))
        plate.setColorAt(1.0, QColor(5, 8, 14, 0))
        painter.setBrush(QBrush(plate))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(0, 0), r, r)

        # 2. Seams between blades: thin radial joints, dim.
        seam = QPen(_qcolor(v.accent, 0.10 + 0.14 * v.energy), 1.0)
        painter.setPen(seam)
        for i in range(self.BLADES):
            angle = math.radians(i * self._STEP + self._spin + self._STEP / 2)
            cos_a, sin_a = math.cos(angle), math.sin(angle)
            painter.drawLine(
                QPointF(gap_r * cos_a, gap_r * sin_a),
                QPointF(r * 0.98 * cos_a, r * 0.98 * sin_a),
            )

        # 3. What is visible through the opening: a faint, cool core.
        if gap_r > 1.0:
            hexagon = self._hexagon(gap_r)
            well = QRadialGradient(QPointF(0, 0), gap_r)
            well.setColorAt(0.0, _qcolor(v.accent, 0.30 * v.energy))
            well.setColorAt(0.55, _qcolor(v.accent, 0.10 * v.energy))
            well.setColorAt(1.0, QColor(3, 5, 10, 255))
            painter.setBrush(QBrush(well))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(hexagon)

            # 4. The bright edge — this is B.O.B.'s actual light source.
            edge = QPen(_qcolor(v.accent, 0.55 + 0.45 * v.energy), 1.6)
            edge.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            painter.setPen(edge)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(hexagon)

        # 5. The rim the blades retract into.
        painter.setPen(QPen(_qcolor(v.accent, 0.18 + 0.22 * v.energy), 1.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(0, 0), r * 0.98, r * 0.98)


class WaveformLayer(CoreLayer):
    """Radial amplitude band, live only in LISTENING and SPEAKING.

    Kept as a thin annulus rather than a full disc so the repaint area stays
    small. When inactive it draws nothing and reports no change, so it costs
    nothing in the other seven states.
    """

    BINS = 48
    DECAY = 6.0

    def __init__(self, radius: float) -> None:
        super().__init__(radius)
        self._bins = [0.0] * self.BINS
        self._active = False
        self.setZValue(35)

    def advance_phase(self, elapsed_s: float, dt: float) -> bool:
        v = self._visual
        if not v.waveform:
            if not self._active:
                return False
            self._active = False
            self._bins = [0.0] * self.BINS
            return True

        self._active = True
        level = min(1.0, self._level * v.waveform_gain)
        decay = math.exp(-self.DECAY * dt)
        for i in range(self.BINS):
            # A standing-wave shape keyed to the bin index gives the band
            # structure; the live level scales the whole thing.
            shape = 0.35 + 0.65 * abs(
                math.sin(elapsed_s * 2.2 + i * 0.44) * math.cos(elapsed_s * 1.3 + i * 0.19)
            )
            target = level * shape
            self._bins[i] = max(target, self._bins[i] * decay)
        return True

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        if not self._active:
            return
        v = self._visual
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # A closed membrane whose radius is modulated by the bins. Drawn as one
        # smooth curve rather than as radial ticks, which would read as a dial.
        base_r = self._radius * 0.78
        extend = self._radius * 0.17

        path = QPainterPath()
        points: list[QPointF] = []
        for i in range(self.BINS):
            angle = TWO_PI * i / self.BINS
            radius = base_r + extend * self._bins[i]
            points.append(QPointF(radius * math.cos(angle), radius * math.sin(angle)))

        # Catmull-Rom-ish smoothing via midpoints keeps the curve organic
        # without a spline library.
        path.moveTo(_midpoint(points[-1], points[0]))
        for i in range(len(points)):
            current = points[i]
            nxt = points[(i + 1) % len(points)]
            path.quadTo(current, _midpoint(current, nxt))
        path.closeSubpath()

        peak = max(self._bins) if self._bins else 0.0
        painter.setPen(QPen(_qcolor(v.accent, 0.35 + 0.45 * peak), 1.5))
        painter.setBrush(_qcolor(v.accent, 0.05 + 0.09 * peak))
        painter.drawPath(path)


class StatusRingLayer(CoreLayer):
    """Outer ring: B.O.B.'s state, readable at a glance from across the room.

    Normally a complete thin circle. In states with ``ring_sweep`` it becomes a
    travelling arc, which is how EXECUTING reads as progress without a progress
    bar. ``unrest`` gives ERROR an asymmetric wobble instead of a flash — a
    flashing ring would be both ugly and an accessibility problem.
    """

    def __init__(self, radius: float) -> None:
        super().__init__(radius)
        self._sweep = 0.0
        self._pulse = 0.0
        self.setZValue(50)

    def advance_phase(self, elapsed_s: float, dt: float) -> bool:
        v = self._visual
        changed = False
        if v.ring_sweep:
            self._sweep = (self._sweep + dt * 150.0) % 360.0
            changed = True
        if v.unrest > 0.0:
            self._pulse = 0.5 + 0.5 * math.sin(elapsed_s * 2.4)
            changed = True
        elif self._pulse != 0.0:
            self._pulse = 0.0
            changed = True
        return changed

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        v = self._visual
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self._radius * 0.97
        rect = QRectF(-r, -r, 2 * r, 2 * r)
        width = 1.0 + 1.6 * v.ring_thickness

        # Base ring: always present, so the core never looks unfinished.
        base_alpha = 0.14 + 0.20 * v.energy
        if v.unrest:
            base_alpha *= 0.6 + 0.4 * self._pulse
        painter.setPen(QPen(_qcolor(v.accent, base_alpha), width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect)

        if v.ring_sweep:
            pen = QPen(_qcolor(v.accent, 0.75), width + 0.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(rect, int(-self._sweep * 16), (70 * 16))
