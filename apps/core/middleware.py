"""Project middleware."""

from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed


class DesktopZoomMiddleware:
    """Scale down page content for the desktop window.

    Windows display scaling makes the embedded browser (WebView2) render larger
    than a normal browser. When ``settings.DESKTOP_ZOOM`` is set (the desktop
    launcher sets ``PHARMACY_ZOOM``), this shrinks the content to match.

    We scale the **root font size** rather than using CSS ``zoom``. The UI is
    built with rem-based sizing (Tailwind), so reducing the root font size
    shrinks all content proportionally while leaving viewport units (``100vh`` /
    ``h-screen``) at the true window height. CSS ``zoom`` instead shrinks
    ``100vh`` too, which left a blank strip at the bottom of full-height layouts.

    Disabled (raises ``MiddlewareNotUsed``) when no zoom is configured, so the
    normal web app and development are unaffected.
    """

    BASE_FONT_PX = 16  # browser default root font size

    def __init__(self, get_response):
        self.get_response = get_response
        raw = str(getattr(settings, "DESKTOP_ZOOM", "") or "").strip()
        try:
            factor = float(raw)
        except (TypeError, ValueError):
            raise MiddlewareNotUsed
        if not (0 < factor < 1):  # only ever scale down; 1 (or invalid) = off
            raise MiddlewareNotUsed

        font_px = round(self.BASE_FONT_PX * factor, 2)
        self._style = (
            "<style>html{font-size:%gpx}</style>" % font_px
        ).encode("utf-8")

    def __call__(self, request):
        response = self.get_response(request)

        content_type = response.get("Content-Type", "")
        if "text/html" not in content_type:
            return response
        # Streaming responses have no .content; skip them.
        if getattr(response, "streaming", False) or not hasattr(response, "content"):
            return response

        content = response.content
        if b"</head>" in content:
            response.content = content.replace(b"</head>", self._style + b"</head>", 1)
            if response.has_header("Content-Length"):
                response["Content-Length"] = str(len(response.content))
        return response
