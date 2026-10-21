"""Only for side-effect-free reads. Never retry publishing or committed writes here."""
import random
import time
from sqlalchemy.exc import OperationalError


def read_with_retry(operation, *, retries=3, sleep=time.sleep, reset=lambda: None):
    for attempt in range(retries + 1):
        try:
            return operation()
        except OperationalError as exc:
            code = getattr(exc.orig, "sqlstate", None)
            transient = code is None or code.startswith("08") or code in {"57P01", "57P02", "57P03", "53300"}
            if not transient or attempt == retries:
                raise
            reset()
            sleep(2 ** (attempt + 1) + random.uniform(0, 0.5))
