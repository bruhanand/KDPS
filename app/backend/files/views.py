from __future__ import annotations

import re

from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from files.models import StoredFile


def _sanitize_filename(name: str) -> str:
    """Strip path separators and control characters so the name is safe for
    Content-Disposition. Falls back to 'download' if nothing printable remains."""
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)
    safe = safe.strip(". ")
    return safe or "download"


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def download(request: Request, pk: int) -> HttpResponse:
    f = StoredFile.objects.filter(pk=pk).first()
    if f is None:
        return Response({"detail": "Not found."}, status=404)
    # Scope check: only the uploader or a superuser may download.
    if not (request.user.is_superuser or f.uploaded_by_id == request.user.pk):
        return Response({"detail": "You do not have access to this file."}, status=403)
    safe_name = _sanitize_filename(f.filename)
    resp = HttpResponse(bytes(f.content), content_type=f.content_type)
    resp["Content-Disposition"] = f'inline; filename="{safe_name}"'
    return resp
