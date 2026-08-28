"""Audio capture, segmentation and metering.

Layering, from pure to impure:

``frames``      immutable frame types, pre-roll and bounded queues — pure
``segmenter``   the VAD state machine (pre-roll, min speech, end silence) — pure
``levels``      amplitude metering and rate limiting — pure
``devices``     device model and selection logic — pure; enumeration behind a Protocol
``capture``     the PortAudio backend — the only part that touches hardware
``pipeline``    wires the above to the kernel, the VAD provider and the STT provider

Everything above ``capture`` is unit-testable with synthetic audio, which is why
the test suite needs neither a microphone nor a model download.
"""
