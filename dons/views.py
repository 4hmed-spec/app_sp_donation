"""
Vues publiques (côté donateur, sans compte).

- formulaire_don : /don/<slug>/        le formulaire de l'épicerie (QR code)
- merci          : /merci/<jeton>/     la page de confirmation
- recu_pdf       : /recu/<jeton>.pdf   le PDF de l'accusé de réception

Les dons sont désignés par leur `jeton` (UUID imprévisible), jamais par leur id.
"""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from . import services
from .forms import DonateurForm, FinalisationForm, LigneDonFormSet
from .models import Don, Epicerie
from .pdf import generer_pdf_recu

# Préfixe des champs du formset dans le HTML (objets-0-categorie, objets-1-…)
PREFIXE_OBJETS = "objets"


def formulaire_don(request, slug):
    """Affiche et traite le formulaire de don d'une épicerie."""
    # Épicerie inconnue OU inactive -> erreur 404
    epicerie = get_object_or_404(Epicerie.objects.select_related("comite"), slug=slug, active=True)

    if request.method == "POST":
        form_donateur = DonateurForm(request.POST)
        formset_objets = LigneDonFormSet(request.POST, prefix=PREFIXE_OBJETS)
        form_final = FinalisationForm(request.POST)

        # On valide les 3 parties (et pas seulement la première) pour afficher
        # toutes les erreurs d'un coup.
        tout_est_valide = all(
            [form_donateur.is_valid(), formset_objets.is_valid(), form_final.is_valid()]
        )
        if tout_est_valide:
            lignes = [
                {
                    "categorie": f.cleaned_data["categorie"],
                    "description": f.cleaned_data["description"],
                    "quantite": f.cleaned_data["quantite"],
                    "etat": f.cleaned_data["etat"],
                }
                for f in formset_objets.forms
                if f.cleaned_data  # ignore un objet ajouté puis laissé vide
            ]
            don = services.enregistrer_don(
                epicerie=epicerie,
                donnees_donateur=form_donateur.cleaned_data,
                lignes=lignes,
                commentaire=form_final.cleaned_data["commentaire"],
                accepte_contact=form_final.cleaned_data["accepte_contact"],
            )
            # POST -> redirect -> GET : si le donateur rafraîchit la page de
            # confirmation, le formulaire n'est pas renvoyé une 2e fois.
            return redirect("dons:merci", jeton=don.jeton)
    else:
        form_donateur = DonateurForm()
        formset_objets = LigneDonFormSet(prefix=PREFIXE_OBJETS)
        form_final = FinalisationForm()

    return render(
        request,
        "formulaire.html",
        {
            "epicerie": epicerie,
            "form_donateur": form_donateur,
            "formset_objets": formset_objets,
            "form_final": form_final,
        },
    )


def _don_par_jeton(jeton):
    """Retrouve un don (avec son reçu) par son jeton, ou renvoie une 404."""
    return get_object_or_404(
        Don.objects.select_related("recu", "donateur", "epicerie__comite"), jeton=jeton
    )


def merci(request, jeton):
    """Page de confirmation affichée après l'envoi du formulaire."""
    don = _don_par_jeton(jeton)
    return render(request, "merci.html", {"don": don, "recu": don.recu})


def recu_pdf(request, jeton):
    """Renvoie le PDF de l'accusé de réception, régénéré depuis la base."""
    don = _don_par_jeton(jeton)
    recu = don.recu
    reponse = HttpResponse(generer_pdf_recu(recu), content_type="application/pdf")
    reponse["Content-Disposition"] = f'attachment; filename="{recu.numero}.pdf"'
    return reponse
