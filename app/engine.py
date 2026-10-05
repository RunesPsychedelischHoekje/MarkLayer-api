"""The heavy, long-lived objects (ONNX models, signing identity), built once at startup.

LESSON: loading the two ONNX models takes ~185 MB and a second or two, so it happens once in the
lifespan hook, not per request. Endpoints receive the Engine through a dependency, which tests
can override.
"""
import threading
from contextlib import contextmanager

from fastapi import Request

from app.config import Settings
from app.errors import ApiError
from app.services.c2pa_io import C2pa, load_identity
from app.services.watermark import Watermarker


class Engine:
    def __init__(self, settings: Settings, extra_anchors_pem: bytes | None = None):
        self.settings = settings
        self.wm = Watermarker(settings.model_dir)
        self.c2pa = C2pa(load_identity(settings.signing_cert_pem, settings.signing_key_pem),
                         settings.tsa_url, settings.data_dir, extra_anchors_pem)
        self._slots = threading.BoundedSemaphore(settings.max_concurrent_jobs)

    @contextmanager
    def slot(self, wait_s: float = 60.0):
        """Run at most `max_concurrent_jobs` image jobs at once; the rest queue, then get a 503."""
        if not self._slots.acquire(timeout=wait_s):
            raise ApiError(503, "busy", "All workers are busy. Retry in a few seconds.")
        try:
            yield
        finally:
            self._slots.release()


def get_engine(request: Request) -> Engine:
    return request.app.state.engine
