from __future__ import annotations

from django.urls import path

from approvals.views import ApprovalDecideView, ApprovalInboxView, ApprovalListView

urlpatterns = [
    path("approvals/inbox", ApprovalInboxView.as_view(), name="approval-inbox"),
    path("approvals", ApprovalListView.as_view(), name="approval-list"),
    path("approvals/<int:pk>/decide", ApprovalDecideView.as_view(), name="approval-decide"),
]
