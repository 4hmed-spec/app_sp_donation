"""Adresses (URLs) publiques de l'application dons."""

from django.urls import path

from . import views

app_name = "dons"

urlpatterns = [
    # URL encodée dans le QR code de chaque épicerie
    path("don/<slug:slug>/", views.formulaire_don, name="formulaire"),
    path("merci/<uuid:jeton>/", views.merci, name="merci"),
    path("recu/<uuid:jeton>.pdf", views.recu_pdf, name="recu_pdf"),
]
