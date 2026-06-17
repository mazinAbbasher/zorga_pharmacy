"""Custom test runner for the project's ``apps/`` layout.

Because ``apps/`` is added to ``sys.path`` (see ``config/settings.py``), every
app is importable by its bare label (``drugs``, ``users``, ...). That matches how
the apps are registered in ``INSTALLED_APPS`` and how they import each other.

The default test discovery, however, walks from the project root and imports the
test modules as ``apps.drugs.tests``. A ``from .models import X`` inside such a
module then loads a *second* copy of the models under ``apps.drugs.models``,
which Django rejects because that copy isn't in ``INSTALLED_APPS``.

This runner forces discovery to treat ``apps/`` as the top-level directory so
test modules are imported as ``drugs.tests`` — the same name the rest of the
project uses — keeping a single, registered copy of every model.
"""

import os

from django.conf import settings
from django.test.runner import DiscoverRunner

APPS_DIR = os.path.join(settings.BASE_DIR, "apps")


class AppsTestRunner(DiscoverRunner):
    def __init__(self, *args, **kwargs):
        if kwargs.get("top_level") is None:
            kwargs["top_level"] = APPS_DIR
        super().__init__(*args, **kwargs)

    def build_suite(self, test_labels=None, **kwargs):
        # Default to discovering everything under apps/ when no label is given.
        if not test_labels:
            test_labels = [APPS_DIR]
        return super().build_suite(test_labels, **kwargs)
