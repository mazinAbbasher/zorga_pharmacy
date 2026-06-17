"""Project middleware."""

from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed


class DesktopZoomMiddleware:
    """Scale down page content for the desktop window.

    Windows display scaling makes the embedded browser (WebView2) render larger
    than a normal browser. When ``settings.DESKTOP_ZOOM`` is set (the desktop
    launcher sets ``PHARMACY_ZOOM``), this injects a ``zoom`` style into every
    full HTML page so everything renders smaller -- the equivalent of pressing
    Ctrl+- in a browser, applied before the page paints.

    Disabled (raises ``MiddlewareNotUsed``) when no zoom is configured, so the
    normal web app and development are unaffected.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.zoom = str(getattr(settings, "DESKTOP_ZOOM", "") or "").strip()
        if not self.zoom or self.zoom in ("1", "1.0"):
            raise MiddlewareNotUsed
        self._style = ("<style>html{zoom:%s}</style>" % self.zoom).encode("utf-8")

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
