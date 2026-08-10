from django.contrib import admin

from ptmapper.models import (
    ControlledValue,
    ItemTaxonomy,
    Lookup,
    PtFile,
    PtRow,
    ReviewItem,
    TaxonomyRule,
)

# admin.ModelAdmin isn't Generic at runtime in this Django version (no django-stubs-ext
# monkeypatch installed) — `ModelAdmin[Model]` raises TypeError on import. Left
# unparameterised below; each `type: ignore[type-arg]` is that, not a missing annotation.


@admin.register(ControlledValue)
class ControlledValueAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("dimension", "value")
    list_filter = ("dimension",)
    search_fields = ("value",)


@admin.register(Lookup)
class LookupAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("dimension", "source_key", "target_value")
    list_filter = ("dimension",)
    search_fields = ("source_key", "target_value")


@admin.register(TaxonomyRule)
class TaxonomyRuleAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("pattern", "item", "type", "sub_category", "priority")
    search_fields = ("pattern", "item")


@admin.register(ItemTaxonomy)
class ItemTaxonomyAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("item", "sub_category", "type")
    search_fields = ("item",)


@admin.register(PtFile)
class PtFileAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("original_filename", "profile_code", "status", "row_count", "unresolved_count")
    list_filter = ("status", "archetype")


@admin.register(ReviewItem)
class ReviewItemAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("dimension", "raw_value", "status", "resolved_value", "occurrences")
    list_filter = ("status", "dimension")
    search_fields = ("raw_value",)


admin.site.register(PtRow)
