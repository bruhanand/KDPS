from __future__ import annotations

from django.urls import path

from vendors.views import (
    BookingDetailView,
    BookingDraftView,
    BookingListCreateView,
    VendorListCreateView,
)

urlpatterns = [
    path("vendors", VendorListCreateView.as_view(), name="vendor-list"),
    path("bookings", BookingListCreateView.as_view(), name="booking-list"),
    path("bookings/draft", BookingDraftView.as_view(), name="booking-draft"),
    path("bookings/<int:pk>", BookingDetailView.as_view(), name="booking-detail"),
]
