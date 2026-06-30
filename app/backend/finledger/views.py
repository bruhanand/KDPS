"""Vendor & cash ledger API — paginated reads + posting actions (finance/owner only)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import generics
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.money import paise_to_rupees_str
from finledger.models import CashLedgerEntry, VendorLedgerEntry
from finledger.posting import (
    post_cash_movement,
    post_vendor_bill,
    post_vendor_payment,
    reverse_cash_entry,
    reverse_vendor_entry,
    rupees_to_paise,
)
from finledger.serializers import CashLedgerEntrySerializer, VendorLedgerEntrySerializer
from vendors.models import Vendor

FINANCE_ROLES = {"accounts", "owner", "it_admin"}


def _is_finance(user: Any) -> bool:
    return getattr(getattr(user, "role", None), "code", "") in FINANCE_ROLES


class IsFinance(BasePermission):
    """Vendor/cash payables, balances and ageing are finance-only data (ADR-0003)."""

    message = "Finance role required."

    def has_permission(self, request: Request, view: Any) -> bool:
        return bool(request.user and request.user.is_authenticated and _is_finance(request.user))


class LedgerPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500


# --- Vendor ledger ---------------------------------------------------------

class VendorEntriesView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsFinance]
    serializer_class = VendorLedgerEntrySerializer
    pagination_class = LedgerPagination

    def get_queryset(self) -> Any:
        qs = VendorLedgerEntry.objects.select_related("vendor")
        vendor = self.request.query_params.get("vendor")
        if vendor:
            qs = qs.filter(vendor_id=vendor)
        return qs


class VendorBalancesView(APIView):
    permission_classes = [IsAuthenticated, IsFinance]

    def get(self, request: Request) -> Response:
        rows = (
            VendorLedgerEntry.objects.values("vendor_id", "vendor__code", "vendor__name")
            .annotate(outstanding=Sum("amount"), entries=Count("id"))
            .order_by("-outstanding")
        )
        total = 0
        out = []
        for r in rows:
            bal = r["outstanding"] or 0
            total += bal
            if bal != 0:
                out.append({
                    "vendor_id": r["vendor_id"],
                    "vendor_code": r["vendor__code"],
                    "vendor_name": r["vendor__name"],
                    "outstanding_paise": bal,
                    "outstanding_rupees": paise_to_rupees_str(bal),
                    "entries": r["entries"],
                })
        return Response({
            "total_payable_paise": total,
            "total_payable_rupees": paise_to_rupees_str(total),
            "vendors_with_dues": len(out),
            "rows": out,
        })


def _bucket_for_days(days: int) -> str:
    if days <= 30:
        return "bucket_0_30"
    if days <= 60:
        return "bucket_31_60"
    return "bucket_60_plus"


def _open_vendor_lots(entries: list[VendorLedgerEntry]) -> list[dict[str, Any]]:
    lots: list[dict[str, Any]] = []
    for entry in entries:
        amount = int(entry.amount or 0)
        if amount > 0:
            lots.append({
                "amount": amount,
                "created_at": entry.created_at,
                "doc_number": entry.doc_number,
                "reference": entry.reference,
            })
            continue
        remaining = abs(amount)
        while remaining > 0 and lots:
            if lots[0]["amount"] <= remaining:
                remaining -= lots[0]["amount"]
                lots.pop(0)
            else:
                lots[0]["amount"] -= remaining
                remaining = 0
    return lots


class VendorAgeingView(APIView):
    permission_classes = [IsAuthenticated, IsFinance]

    def get(self, request: Request) -> Response:
        grouped: dict[int, list[VendorLedgerEntry]] = defaultdict(list)
        entries = VendorLedgerEntry.objects.select_related("vendor").order_by(
            "vendor_id", "created_at", "id"
        )
        for entry in entries:
            grouped[entry.vendor_id].append(entry)

        today = timezone.localdate()
        totals = {"bucket_0_30": 0, "bucket_31_60": 0, "bucket_60_plus": 0}
        rows = []
        for vendor_id, vendor_entries in grouped.items():
            first = vendor_entries[0]
            buckets = {"bucket_0_30": 0, "bucket_31_60": 0, "bucket_60_plus": 0}
            oldest_days = 0
            open_lots = _open_vendor_lots(vendor_entries)
            for lot in open_lots:
                local_date = timezone.localtime(lot["created_at"]).date()
                age_days = max((today - local_date).days, 0)
                oldest_days = max(oldest_days, age_days)
                bucket = _bucket_for_days(age_days)
                buckets[bucket] += lot["amount"]
                totals[bucket] += lot["amount"]
            total_due = sum(buckets.values())
            if total_due <= 0:
                continue
            rows.append({
                "vendor_id": vendor_id,
                "vendor_code": first.vendor.code,
                "vendor_name": first.vendor.name,
                "payment_terms": first.vendor.payment_terms,
                "oldest_days": oldest_days,
                "bucket_0_30_paise": buckets["bucket_0_30"],
                "bucket_0_30_rupees": paise_to_rupees_str(buckets["bucket_0_30"]),
                "bucket_31_60_paise": buckets["bucket_31_60"],
                "bucket_31_60_rupees": paise_to_rupees_str(buckets["bucket_31_60"]),
                "bucket_60_plus_paise": buckets["bucket_60_plus"],
                "bucket_60_plus_rupees": paise_to_rupees_str(buckets["bucket_60_plus"]),
                "total_due_paise": total_due,
                "total_due_rupees": paise_to_rupees_str(total_due),
                "open_bill_count": len(open_lots),
            })

        rows.sort(key=lambda r: (r["bucket_60_plus_paise"], r["total_due_paise"]), reverse=True)
        total_due = sum(totals.values())
        return Response({
            "as_of": today.isoformat(),
            "total_due_paise": total_due,
            "total_due_rupees": paise_to_rupees_str(total_due),
            "bucket_0_30_rupees": paise_to_rupees_str(totals["bucket_0_30"]),
            "bucket_31_60_rupees": paise_to_rupees_str(totals["bucket_31_60"]),
            "bucket_60_plus_rupees": paise_to_rupees_str(totals["bucket_60_plus"]),
            "rows": rows,
        })


class VendorBillView(APIView):
    permission_classes = [IsAuthenticated, IsFinance]

    def post(self, request: Request) -> Response:
        if not _is_finance(request.user):
            return Response({"detail": "Not permitted."}, status=403)
        vendor = Vendor.objects.filter(pk=request.data.get("vendor_id")).first()
        if not vendor:
            return Response({"detail": "vendor_id is required / invalid."}, status=400)
        amount = rupees_to_paise(request.data.get("amount"))
        if amount <= 0:
            return Response({"detail": "A positive amount is required."}, status=400)
        entry = post_vendor_bill(
            vendor, amount, request.data.get("description", ""), request.user,
            reference=request.data.get("reference", ""),
        )
        return Response(VendorLedgerEntrySerializer(entry).data, status=201)


class VendorPaymentView(APIView):
    permission_classes = [IsAuthenticated, IsFinance]

    def post(self, request: Request) -> Response:
        if not _is_finance(request.user):
            return Response({"detail": "Not permitted."}, status=403)
        vendor = Vendor.objects.filter(pk=request.data.get("vendor_id")).first()
        if not vendor:
            return Response({"detail": "vendor_id is required / invalid."}, status=400)
        amount = rupees_to_paise(request.data.get("amount"))
        if amount <= 0:
            return Response({"detail": "A positive amount is required."}, status=400)
        entry = post_vendor_payment(
            vendor, amount, request.data.get("description", ""), request.user,
            mode=request.data.get("mode", "cash"),
            account=request.data.get("account", "CASH"),
            also_cash=request.data.get("also_cash", True),
        )
        return Response(VendorLedgerEntrySerializer(entry).data, status=201)


class VendorReverseView(APIView):
    permission_classes = [IsAuthenticated, IsFinance]

    def post(self, request: Request, pk: int) -> Response:
        if not _is_finance(request.user):
            return Response({"detail": "Not permitted."}, status=403)
        entry = VendorLedgerEntry.objects.filter(pk=pk).first()
        if not entry:
            return Response({"detail": "Not found."}, status=404)
        if entry.kind == VendorLedgerEntry.Kind.REVERSAL:
            return Response({"detail": "A reversal cannot be reversed."}, status=409)
        rev = reverse_vendor_entry(entry, request.user)
        return Response(VendorLedgerEntrySerializer(rev).data, status=201)


# --- Cash ledger -----------------------------------------------------------

class CashEntriesView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsFinance]
    serializer_class = CashLedgerEntrySerializer
    pagination_class = LedgerPagination

    def get_queryset(self) -> Any:
        qs = CashLedgerEntry.objects.select_related("vendor")
        account = self.request.query_params.get("account")
        if account:
            qs = qs.filter(account=account)
        return qs


class CashSummaryView(APIView):
    permission_classes = [IsAuthenticated, IsFinance]

    def get(self, request: Request) -> Response:
        rows = (
            CashLedgerEntry.objects.values("account")
            .annotate(balance=Sum("amount"), entries=Count("id"))
            .order_by("account")
        )
        total = 0
        out = []
        for r in rows:
            bal = r["balance"] or 0
            total += bal
            out.append({
                "account": r["account"],
                "balance_paise": bal,
                "balance_rupees": paise_to_rupees_str(bal),
                "entries": r["entries"],
            })
        return Response({
            "total_paise": total,
            "total_rupees": paise_to_rupees_str(total),
            "accounts": out,
        })


class CashMovementView(APIView):
    permission_classes = [IsAuthenticated, IsFinance]

    def post(self, request: Request) -> Response:
        if not _is_finance(request.user):
            return Response({"detail": "Not permitted."}, status=403)
        direction = request.data.get("direction")
        if direction not in ("in", "out"):
            return Response({"detail": "direction must be 'in' or 'out'."}, status=400)
        amount = rupees_to_paise(request.data.get("amount"))
        if amount <= 0:
            return Response({"detail": "A positive amount is required."}, status=400)
        entry = post_cash_movement(
            direction, amount, request.data.get("description", ""), request.user,
            account=request.data.get("account", "CASH"),
            mode=request.data.get("mode", ""),
        )
        return Response(CashLedgerEntrySerializer(entry).data, status=201)


class CashReverseView(APIView):
    permission_classes = [IsAuthenticated, IsFinance]

    def post(self, request: Request, pk: int) -> Response:
        if not _is_finance(request.user):
            return Response({"detail": "Not permitted."}, status=403)
        entry = CashLedgerEntry.objects.filter(pk=pk).first()
        if not entry:
            return Response({"detail": "Not found."}, status=404)
        if entry.kind == CashLedgerEntry.Kind.REVERSAL:
            return Response({"detail": "A reversal cannot be reversed."}, status=409)
        rev = reverse_cash_entry(entry, request.user)
        return Response(CashLedgerEntrySerializer(rev).data, status=201)
