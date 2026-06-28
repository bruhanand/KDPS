from __future__ import annotations

from django.contrib import admin

from masters.models import Brand, Gstin, LegalEntity, Season, Store


@admin.register(LegalEntity)
class LegalEntityAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "pan", "is_active"]
    search_fields = ["name", "code", "pan"]


@admin.register(Gstin)
class GstinAdmin(admin.ModelAdmin):
    list_display = ["gstin", "state_name", "state_code", "legal_entity", "is_active"]
    list_filter = ["state_name", "is_active"]
    search_fields = ["gstin", "state_name"]


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "store_type", "gstin", "city", "is_active"]
    list_filter = ["store_type", "gstin__state_name", "is_active"]
    search_fields = ["code", "name", "city"]


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "status", "sort_order"]
    list_filter = ["status"]


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "ownership", "return_terms", "commercial_label", "is_active"]
    list_filter = ["ownership", "return_terms", "is_active"]
    search_fields = ["name", "code"]
