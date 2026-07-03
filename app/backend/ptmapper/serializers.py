from __future__ import annotations

from rest_framework import serializers

from ptmapper.models import LookupProposal, PtFile, PtRow, ReviewItem


class PtRowSerializer(serializers.ModelSerializer):
    class Meta:
        model = PtRow
        fields = ["id", "line_no", "data", "blanks", "provenance", "raw"]


class ReviewItemSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ReviewItem
        fields = [
            "id",
            "dimension",
            "raw_value",
            "context",
            "status",
            "status_label",
            "resolved_value",
            "occurrences",
            "updated_at",
        ]


class LookupProposalSerializer(serializers.ModelSerializer):
    origin_label = serializers.CharField(source="get_origin_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    proposed_by_name = serializers.CharField(
        source="proposed_by.username", read_only=True, default=""
    )
    decided_by_name = serializers.CharField(
        source="decided_by.username", read_only=True, default=""
    )
    scope = serializers.SerializerMethodField()

    class Meta:
        model = LookupProposal
        fields = [
            "id",
            "dimension",
            "source_key",
            "target_value",
            "brand",
            "scope",
            "origin",
            "origin_label",
            "status",
            "status_label",
            "evidence",
            "validation",
            "proposed_by_name",
            "decided_by_name",
            "decided_at",
            "applied_at",
            "created_at",
        ]

    def get_scope(self, obj: LookupProposal) -> str:
        return obj.brand or "GLOBAL"


class PtFileListSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    stage = serializers.ReadOnlyField()
    stage_label = serializers.ReadOnlyField()
    inward_doc_number = serializers.SerializerMethodField()
    booking_number = serializers.CharField(source="booking.number", read_only=True, default="")
    grn_number = serializers.CharField(source="grn.doc_number", read_only=True, default="")

    class Meta:
        model = PtFile
        fields = [
            "id",
            "original_filename",
            "source",
            "brand_guess",
            "profile_code",
            "profile_name",
            "archetype",
            "status",
            "status_label",
            "stage",
            "stage_label",
            "manually_edited",
            "sent_at",
            "posted_at",
            "doc_number",
            "inward_doc_number",
            "booking",
            "booking_number",
            "grn",
            "grn_number",
            "row_count",
            "blank_cell_count",
            "unresolved_count",
            "error",
            "created_at",
        ]

    def get_inward_doc_number(self, obj: PtFile) -> str:
        return obj.doc_number or ""


class PtFileDetailSerializer(PtFileListSerializer):
    rows = PtRowSerializer(many=True, read_only=True)

    class Meta(PtFileListSerializer.Meta):
        fields = PtFileListSerializer.Meta.fields + ["meta", "rows"]
