from __future__ import annotations

from django.urls import path

from ptmapper.views import (
    ControlledValuesView,
    LookupProposalDecideView,
    LookupProposalListView,
    PtFileDetailView,
    PtFileExportView,
    PtFileExportXlsxView,
    PtFileFromGrnView,
    PtFileListCreateView,
    PtFilePostView,
    PtFilePriceView,
    PtFileRecallView,
    PtFileRerunView,
    PtFileReverseView,
    PtFileSendView,
    PtRowsUpdateView,
    ReviewListView,
    ReviewResolveView,
    SuggestView,
)

urlpatterns = [
    path("files", PtFileListCreateView.as_view(), name="pt-file-list"),
    path("files/from-grn/<int:grn_id>", PtFileFromGrnView.as_view(), name="pt-file-from-grn"),
    path("files/<int:pk>", PtFileDetailView.as_view(), name="pt-file-detail"),
    path("files/<int:pk>/price", PtFilePriceView.as_view(), name="pt-file-price"),
    path("files/<int:pk>/rerun", PtFileRerunView.as_view(), name="pt-file-rerun"),
    path("files/<int:pk>/rows", PtRowsUpdateView.as_view(), name="pt-file-rows"),
    path("files/<int:pk>/send", PtFileSendView.as_view(), name="pt-file-send"),
    path("files/<int:pk>/recall", PtFileRecallView.as_view(), name="pt-file-recall"),
    path("files/<int:pk>/post", PtFilePostView.as_view(), name="pt-file-post"),
    path("files/<int:pk>/reverse", PtFileReverseView.as_view(), name="pt-file-reverse"),
    path("files/<int:pk>/export", PtFileExportView.as_view(), name="pt-file-export"),
    path("files/<int:pk>/export.xlsx", PtFileExportXlsxView.as_view(), name="pt-file-export-xlsx"),
    path("review", ReviewListView.as_view(), name="pt-review-list"),
    path("review/<int:pk>/resolve", ReviewResolveView.as_view(), name="pt-review-resolve"),
    path("proposals", LookupProposalListView.as_view(), name="pt-proposal-list"),
    path(
        "proposals/<int:pk>/decide",
        LookupProposalDecideView.as_view(),
        name="pt-proposal-decide",
    ),
    path("suggest", SuggestView.as_view(), name="pt-suggest"),
    path("controlled", ControlledValuesView.as_view(), name="pt-controlled"),
]
