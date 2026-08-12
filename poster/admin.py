from django.contrib import admin

from .models import LinkedInAccount, GeneratedPost


@admin.register(LinkedInAccount)
class LinkedInAccountAdmin(admin.ModelAdmin):
    list_display = ("display_name", "owner", "topic", "posting_times", "frequency_days", "is_active", "is_connected")
    list_filter = ("is_active", "topic", "owner")
    readonly_fields = ("access_token_encrypted", "refresh_token_encrypted", "linkedin_client_secret_encrypted", "created_at", "updated_at")

    def is_connected(self, obj):
        return obj.is_connected
    is_connected.boolean = True


@admin.register(GeneratedPost)
class GeneratedPostAdmin(admin.ModelAdmin):
    list_display = ("account", "slot_time", "status", "scheduled_for", "posted_at")
    list_filter = ("status", "account")
    readonly_fields = ("created_at",)