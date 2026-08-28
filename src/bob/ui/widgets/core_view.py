"""The animated B.O.B. core.

One ``QGraphicsView`` over a scene sized to the core itself, driven by **one**
timer. The rules that keep it cheap:

1. A single :class:`QTimer` advances every layer. Layers do not own timers.
2. ``advance()`` returns whether a layer changed; only those get ``update()``.
3. The scene rect is the core's bounds, so panels behind it never repaint.
4. The timer stops entirely when the widget is hidden or the window is
   minimised — an animation nobody can see is pure waste.
5. OFFLINE drops to ``dormant_fps``; ``reduced_motion`` drops to
   ``reduced_motion_fps`` and stills the moving layers.

State changes morph the visual over ``motion.slower`` rather than snapping, by
interpolating :class:`CoreVisual` parameters through an eased blend.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QHideEvent, QPainter, QResizeEvent, QShowEvent
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QWidget

from bob.core.states import BobState
from bob.ui.theme.easing import ease
from bob.ui.theme.tokens import Theme
from bob.ui.visual import CoreVisual, VisualCatalogue, blend
from bob.ui.widgets.core_layers import (
    ApertureLayer,
    CoreLayer,
    HaloLayer,
    NodeLayer,
    OrbitLayer,
    StatusRingLayer,
    WaveformLayer,
)

#: Inclination, arc span and vertical squash for the three orbital rings.
#: Different inclinations are what make it read as an armillary sphere rather
#: than as concentric circles.
ORBIT_GEOMETRY: tuple[tuple[float, float, float], ...] = (
    (18.0, 250.0, 0.34),
    (-42.0, 300.0, 0.52),
    (74.0, 210.0, 0.26),
)


class CoreView(QGraphicsView):
    """B.O.B.'s visual signature."""

    #: Emitted when the animation clock changes rate, for the debug overlay.
    fpsChanged = Signal(int)

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._catalogue = VisualCatalogue(theme)

        self._state = BobState.OFFLINE
        self._current: CoreVisual = self._catalogue.for_state(BobState.OFFLINE)
        self._from: CoreVisual = self._current
        self._to: CoreVisual = self._current
        self._morph_start = 0.0
        self._morph_ms = float(theme.motion.slower)

        self._radius = 150.0
        self._level = 0.0
        self._started = time.monotonic()
        self._last_tick = self._started
        self._fps = theme.motion.idle_fps

        self._configure_view()
        self._build_scene()

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    # -- construction ----------------------------------------------------

    def _configure_view(self) -> None:
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("background: transparent;")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # Only repaint the region a layer actually invalidated.
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate)
        self.setOptimizationFlag(QGraphicsView.OptimizationFlag.DontSavePainterState, True)
        self.setInteractive(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("B.O.B. core")

    def _build_scene(self) -> None:
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        r = self._radius
        self._halo = HaloLayer(r * 1.32)
        self._orbits = [
            OrbitLayer(
                r * scale,
                index=i,
                inclination=inc,
                span_deg=span,
                squash=squash,
            )
            for i, ((inc, span, squash), scale) in enumerate(
                zip(ORBIT_GEOMETRY, (1.0, 0.84, 0.68), strict=True)
            )
        ]
        self._nodes = NodeLayer(r, self._orbits)
        self._waveform = WaveformLayer(r)
        self._aperture = ApertureLayer(r * 0.62)
        self._ring = StatusRingLayer(r)

        self._layers: list[CoreLayer] = [
            self._halo,
            *self._orbits,
            self._nodes,
            self._waveform,
            self._aperture,
            self._ring,
        ]
        for layer in self._layers:
            self._scene.addItem(layer)
            layer.set_visual(self._current)

    # -- public API ------------------------------------------------------

    @property
    def state(self) -> BobState:
        return self._state

    @property
    def fps(self) -> int:
        return self._fps

    def set_state(self, state: BobState) -> None:
        """Morph the core to a new state's appearance."""
        if state is self._state:
            return
        self._state = state
        self._from = self._current
        self._to = self._catalogue.for_state(state)
        self._morph_start = time.monotonic()
        # WAKE_DETECTED should feel like a flinch, not a fade.
        self._morph_ms = (
            self._theme.motion.fast * 1.6
            if state is BobState.WAKE_DETECTED
            else float(self._theme.motion.slower)
        )
        self._apply_frame_rate()

    def set_level(self, level: float) -> None:
        """Feed the waveform an audio level in 0..1."""
        self._level = max(0.0, min(1.0, level))

    def set_diameter(self, diameter: int) -> None:
        """Resize the core. Called by the shell on layout changes only."""
        radius = max(60.0, diameter / 2.0)
        if abs(radius - self._radius) < 1.0:
            return
        self._radius = radius
        self._halo.set_radius(radius * 1.32)
        for orbit, scale in zip(self._orbits, (1.0, 0.84, 0.68), strict=True):
            orbit.set_radius(radius * scale)
        self._nodes.set_radius(radius)
        self._waveform.set_radius(radius)
        self._aperture.set_radius(radius * 0.62)
        self._ring.set_radius(radius)
        self._update_scene_rect()

    # -- animation clock -------------------------------------------------

    def _target_fps(self) -> int:
        motion = self._theme.motion
        if self._theme.reduced_motion:
            return motion.reduced_motion_fps
        if self._state is BobState.OFFLINE and not self._morphing():
            return motion.dormant_fps
        return motion.idle_fps

    def _morphing(self) -> bool:
        if self._morph_ms <= 0.0:
            return False
        return (time.monotonic() - self._morph_start) * 1000.0 < self._morph_ms

    def _apply_frame_rate(self) -> None:
        fps = self._target_fps()
        if fps != self._fps or not self._timer.isActive():
            self._fps = fps
            self._timer.start(max(1, int(1000 / fps)))
            self.fpsChanged.emit(fps)

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(0.1, now - self._last_tick)  # clamp after a stall
        self._last_tick = now
        elapsed = now - self._started

        self._advance_morph(now)

        for layer in self._layers:
            layer.set_visual(self._current)
        self._waveform.set_level(self._level)

        for layer in self._layers:
            if layer.advance_phase(elapsed, dt):
                layer.update()

        # Drop back to the dormant rate once a morph into OFFLINE completes.
        if self._fps != self._target_fps():
            self._apply_frame_rate()

    def _advance_morph(self, now: float) -> None:
        if self._current == self._to:
            return
        if self._morph_ms <= 0.0:
            self._current = self._to
            return
        progress = (now - self._morph_start) * 1000.0 / self._morph_ms
        if progress >= 1.0:
            self._current = self._to
            return
        self._current = blend(
            self._from, self._to, ease(self._theme.motion.ease_emphasis, progress)
        )

    # -- Qt events -------------------------------------------------------

    def _update_scene_rect(self) -> None:
        r = self._radius * 1.36
        self._scene.setSceneRect(QRectF(-r, -r, 2 * r, 2 * r))
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_scene_rect()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._last_tick = time.monotonic()
        self._apply_frame_rate()

    def hideEvent(self, event: QHideEvent) -> None:
        # Nobody can see it; stop burning frames.
        self._timer.stop()
        super().hideEvent(event)
