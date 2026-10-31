"""Run once: python -m app.form_worker (from backend). No model calls."""
import json
import sys

from .form_sync import FormSyncError, sync_once


def main():
    try:
        result = sync_once()
    except FormSyncError as error:
        print(f'Form sync failed: {error}', file=sys.stderr)
        return 1
    except Exception:
        # Do not print DB exceptions, URLs, SQL parameters or raw answers.
        print('Form sync failed: check database connection, permissions and migration state', file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
