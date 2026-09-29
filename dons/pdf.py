"""
Génération du PDF de l'accusé de réception, avec xhtml2pdf.

Le PDF n'est jamais stocké : on le fabrique à la demande à partir du template
HTML `templates/recu_pdf.html` et des données en base. Il est donc toujours à
jour (ex. si une faute dans le nom du donateur est corrigée dans l'admin).
"""

from io import BytesIO

from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from xhtml2pdf import pisa

MENTION_NON_FISCAL = (
    "Ce document est un accusé de réception de don en nature. "
    "Il ne constitue pas un reçu fiscal."
)


def generer_pdf_recu(recu):
    """Retourne le contenu du PDF (bytes) pour le reçu donné."""
    don = recu.don
    contexte = {
        "recu": recu,
        "don": don,
        "donateur": don.donateur,
        "epicerie": don.epicerie,
        "comite": don.epicerie.comite,
        "lignes": don.lignes.select_related("categorie").all(),
        "mention_non_fiscal": MENTION_NON_FISCAL,
        # xhtml2pdf lit les images sur le disque : on lui donne le chemin complet du logo
        # (None si le fichier est absent : le PDF est alors généré sans logo)
        "chemin_logo": finders.find("img/logo.png"),
        # Police de la charte (Barlow Semi Condensed, en TTF car xhtml2pdf ne lit pas le woff2)
        "police_normale": finders.find("fonts/barlow/ttf/BarlowSemiCondensed-Regular.ttf"),
        "police_grasse": finders.find("fonts/barlow/ttf/BarlowSemiCondensed-Bold.ttf"),
        "nb_objets": sum(ligne.quantite for ligne in don.lignes.all()),
    }
    html = render_to_string("recu_pdf.html", contexte)

    tampon = BytesIO()
    resultat = pisa.CreatePDF(html, dest=tampon, encoding="utf-8")
    if resultat.err:
        raise RuntimeError(f"Erreur lors de la génération du PDF du reçu {recu.numero}")
    return tampon.getvalue()
