"""
Formulaires du parcours donateur, avec leur validation côté serveur.

Le formulaire public est découpé en 3 parties :
1. DonateurForm     : coordonnées du donateur
2. LigneDonFormSet  : les objets donnés (de 1 à 20), un sous-formulaire par objet
3. FinalisationForm : commentaire, recontact, consentement RGPD, champ piège

La validation se fait TOUJOURS côté serveur (ici), même si le navigateur
vérifie déjà certains champs : un robot ou un navigateur modifié peut
contourner les vérifications du navigateur.
"""

import re

from django import forms
from django.core.exceptions import ValidationError

from .models import QUANTITE_MAX, CategorieObjet, Donateur, LigneDon

# Nombre maximal d'objets (lignes) dans un même don
NB_OBJETS_MAX = 20


# =============================================================================
# 1. Coordonnées du donateur
# =============================================================================
class DonateurForm(forms.ModelForm):
    class Meta:
        model = Donateur
        fields = ["prenom", "nom", "email", "telephone", "adresse", "code_postal", "ville"]
        # Les attributs « autocomplete » et « inputmode » aident le téléphone :
        # remplissage automatique et bon clavier (chiffres, @…).
        widgets = {
            "prenom": forms.TextInput(attrs={"autocomplete": "given-name"}),
            "nom": forms.TextInput(attrs={"autocomplete": "family-name"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "telephone": forms.TextInput(
                attrs={"type": "tel", "autocomplete": "tel", "inputmode": "tel"}
            ),
            "adresse": forms.TextInput(attrs={"autocomplete": "street-address"}),
            "code_postal": forms.TextInput(
                attrs={
                    "autocomplete": "postal-code",
                    "inputmode": "numeric",
                    "maxlength": "5",
                    "pattern": "[0-9]{5}",
                }
            ),
            "ville": forms.TextInput(attrs={"autocomplete": "address-level2"}),
        }

    def clean_prenom(self):
        return self.cleaned_data["prenom"].strip()

    def clean_nom(self):
        return self.cleaned_data["nom"].strip()

    def clean_email(self):
        # Le format est déjà vérifié par EmailField ; on retire juste les espaces
        return self.cleaned_data["email"].strip()

    def clean_code_postal(self):
        # Tolère les espaces tapés par erreur (« 75 011 »), puis 5 chiffres exigés
        code = self.cleaned_data["code_postal"].replace(" ", "")
        if code and not re.fullmatch(r"\d{5}", code):
            raise ValidationError("Le code postal doit contenir exactement 5 chiffres.")
        return code

    def clean_telephone(self):
        """Téléphone facultatif mais plausible.

        Acceptés : numéro français à 10 chiffres (06 12 34 56 78, 01.23…),
        ou numéro international commençant par + (8 à 15 chiffres).
        On enregistre le numéro sans espaces, points ni tirets.
        """
        brut = self.cleaned_data["telephone"].strip()
        if not brut:
            return ""
        numero = re.sub(r"[\s.\-()]", "", brut)
        if numero.startswith("0033"):
            numero = "+33" + numero[4:]
        if re.fullmatch(r"0[1-9]\d{8}", numero) or re.fullmatch(r"\+[1-9]\d{7,14}", numero):
            return numero
        raise ValidationError("Numéro de téléphone invalide (ex. : 06 12 34 56 78).")


# =============================================================================
# 2. Objets donnés
# =============================================================================
class LigneDonForm(forms.ModelForm):
    class Meta:
        model = LigneDon
        fields = ["categorie", "description", "quantite", "etat"]
        labels = {"description": "Précisez l'objet"}
        widgets = {
            "description": forms.TextInput(attrs={"placeholder": "ex. : bureau gris"}),
            "quantite": forms.NumberInput(
                attrs={"min": 1, "max": QUANTITE_MAX, "inputmode": "numeric"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Seules les catégories actives sont proposées, dans l'ordre choisi par la fédé
        self.fields["categorie"].queryset = CategorieObjet.objects.filter(active=True)
        self.fields["categorie"].empty_label = "— Choisir —"
        # Sans ça, Django pré-sélectionnerait « Neuf » : on veut un choix conscient
        self.fields["etat"].choices = [("", "— Choisir —")] + list(LigneDon.Etat.choices)

    def clean_description(self):
        return self.cleaned_data["description"].strip()


# Un « formset » = une liste de LigneDonForm.
# - min_num=1 + validate_min : au moins 1 objet
# - max_num=20 + validate_max + absolute_max : au plus 20 objets, même si un
#   robot envoie plus de sous-formulaires
# - extra=0 : on affiche 1 seul objet au départ, le bouton « + Ajouter » en ajoute
LigneDonFormSet = forms.formset_factory(
    LigneDonForm,
    extra=0,
    min_num=1,
    validate_min=True,
    max_num=NB_OBJETS_MAX,
    validate_max=True,
    absolute_max=NB_OBJETS_MAX,
)


# =============================================================================
# 3. Finalisation : commentaire, consentements, champ piège anti-spam
# =============================================================================
class FinalisationForm(forms.Form):
    commentaire = forms.CharField(
        label="Un commentaire ?",
        required=False,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    accepte_contact = forms.BooleanField(
        label="J'accepte d'être recontacté(e) par le Secours populaire.",
        required=False,
    )
    # TODO (point ouvert) : texte RGPD définitif (responsable du traitement,
    # durée de conservation, contact pour exercer ses droits). Voir formulaire.html.
    consentement_rgpd = forms.BooleanField(
        label="J'accepte que mes données soient enregistrées pour le suivi de mon don.",
        required=True,
        error_messages={"required": "Votre accord est nécessaire pour enregistrer le don."},
    )
    # Champ piège (honeypot) : caché aux humains par le CSS, mais les robots
    # remplissent tous les champs. S'il est rempli, on refuse l'envoi.
    site_web = forms.CharField(
        label="Ne pas remplir ce champ",
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "off", "tabindex": "-1"}),
    )

    def clean_site_web(self):
        if self.cleaned_data["site_web"]:
            raise ValidationError("Envoi refusé.")
        return ""
