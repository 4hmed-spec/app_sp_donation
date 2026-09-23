"""
Table des adresses (URLs) du site.

- /admin/  : back-office de la fédé (admin Django)
- le reste : pages publiques de l'application dons (voir dons/urls.py)
"""

from django.contrib import admin
from django.urls import include, path

# Titres affichés dans l'admin
admin.site.site_header = "Dons SPF — Back-office"
admin.site.site_title = "Dons SPF"
admin.site.index_title = "Gestion des dons en nature"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("dons.urls")),
]
