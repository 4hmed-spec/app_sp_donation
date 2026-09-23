"""Déclaration de l'application « dons » auprès de Django."""

from django.apps import AppConfig


class DonsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dons"
    verbose_name = "Dons en nature"
