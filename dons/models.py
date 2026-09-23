"""
Modèles de données de l'application « Dons SPF ».

Chaque classe ci-dessous devient une table dans la base de données.
Les règles importantes sont posées EN BASE (NOT NULL, UNIQUE, CHECK, clés
étrangères) et pas seulement dans le code Python : même si quelqu'un écrit
dans la base par un autre moyen, les données restent cohérentes.

Schéma :
    Comite 1───n Epicerie 1───n Don n───1 Donateur
                                 ├──n LigneDon n───1 CategorieObjet
                                 └──1 Recu
    CompteurRecu : 1 ligne par année, pour la numérotation des reçus
"""

import uuid

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

# Validateur réutilisable : un code postal français = exactement 5 chiffres
valider_code_postal = RegexValidator(
    regex=r"^\d{5}$",
    message="Le code postal doit contenir exactement 5 chiffres.",
)


# =============================================================================
# Organisation du SPF : comités et épiceries solidaires
# =============================================================================
class Comite(models.Model):
    """Un comité local du Secours populaire (regroupe une ou plusieurs épiceries)."""

    nom = models.CharField("nom", max_length=150, unique=True)

    class Meta:
        verbose_name = "comité"
        verbose_name_plural = "comités"
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class Epicerie(models.Model):
    """Une épicerie solidaire. Chacune a son propre QR code (URL /don/<slug>/)."""

    nom = models.CharField("nom", max_length=150)
    # PROTECT : impossible de supprimer un comité qui a encore des épiceries
    comite = models.ForeignKey(
        Comite,
        on_delete=models.PROTECT,
        related_name="epiceries",
        verbose_name="comité",
    )
    adresse = models.CharField("adresse", max_length=255)
    code_postal = models.CharField(
        "code postal", max_length=5, validators=[valider_code_postal]
    )
    ville = models.CharField("ville", max_length=100)
    # Identifiant lisible utilisé dans l'URL du QR code, ex. « paris-11-oberkampf »
    slug = models.SlugField(
        "identifiant d'URL",
        max_length=80,
        unique=True,
        help_text="Utilisé dans l'adresse du formulaire : /don/<identifiant>/. "
        "Ne pas modifier une fois le QR code imprimé.",
    )
    # Une épicerie inactive renvoie une erreur 404 (le QR code ne marche plus)
    active = models.BooleanField("active", default=True)

    class Meta:
        verbose_name = "épicerie"
        verbose_name_plural = "épiceries"
        ordering = ["comite__nom", "nom"]
        constraints = [
            # Deux épiceries d'un même comité ne peuvent pas avoir le même nom
            models.UniqueConstraint(
                fields=["comite", "nom"], name="epicerie_nom_unique_par_comite"
            ),
        ]

    def __str__(self):
        return f"{self.nom} ({self.comite})"


# =============================================================================
# Catégories d'objets (liste fermée, gérée par la fédé)
# =============================================================================
class CategorieObjet(models.Model):
    """Catégorie d'objet donné (Mobilier, Vêtements…).

    TODO (point ouvert) : la liste définitive des catégories reste à valider
    par la fédé. Elle est créée par la commande `initialiser_donnees`.
    """

    nom = models.CharField("nom", max_length=100, unique=True)
    # Ordre d'affichage dans la liste déroulante du formulaire
    ordre = models.PositiveSmallIntegerField("ordre d'affichage", default=0)
    # Une catégorie inactive n'est plus proposée, mais les anciens dons la gardent
    active = models.BooleanField("active", default=True)

    class Meta:
        verbose_name = "catégorie d'objet"
        verbose_name_plural = "catégories d'objets"
        ordering = ["ordre", "nom"]

    def __str__(self):
        return self.nom


# =============================================================================
# Donateurs
# =============================================================================
class Donateur(models.Model):
    """Personne qui fait un don. Pas de compte : on stocke seulement ses coordonnées.

    Déduplication (faite dans services.py) : on réutilise une fiche existante
    uniquement si l'email ET le nom correspondent (sans tenir compte des
    majuscules). Sinon on crée une nouvelle fiche.
    """

    # --- Champs obligatoires ---
    nom = models.CharField("nom", max_length=100)
    prenom = models.CharField("prénom", max_length=100)
    email = models.EmailField("email", max_length=254, db_index=True)

    # --- Champs facultatifs (chaîne vide si non renseigné, jamais NULL) ---
    telephone = models.CharField("téléphone", max_length=20, blank=True)
    adresse = models.CharField("adresse", max_length=255, blank=True)
    code_postal = models.CharField(
        "code postal", max_length=5, blank=True, validators=[valider_code_postal]
    )
    ville = models.CharField("ville", max_length=100, blank=True)

    # --- RGPD ---
    # TODO (point ouvert) : texte RGPD définitif (responsable du traitement,
    # durée de conservation, contact pour exercer ses droits).
    consentement_rgpd = models.BooleanField("consentement RGPD", default=False)
    date_consentement = models.DateTimeField("date du consentement")
    accepte_contact = models.BooleanField("accepte d'être recontacté", default=False)

    # --- Traçabilité ---
    date_creation = models.DateTimeField("créé le", auto_now_add=True)
    date_modification = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        verbose_name = "donateur"
        verbose_name_plural = "donateurs"
        ordering = ["nom", "prenom"]
        constraints = [
            # Contrainte CHECK en base : impossible d'enregistrer un donateur
            # qui n'a pas donné son consentement RGPD.
            models.CheckConstraint(
                condition=Q(consentement_rgpd=True),
                name="donateur_consentement_rgpd_obligatoire",
            ),
        ]

    def __str__(self):
        return f"{self.prenom} {self.nom} <{self.email}>"


# =============================================================================
# Dons et lignes de don
# =============================================================================
class Don(models.Model):
    """Un dépôt d'objets par un donateur dans une épicerie, à une date donnée."""

    class Statut(models.TextChoices):
        # valeur stockée en base / libellé affiché
        DECLARE = "DECLARE", "Déclaré"
        VALIDE = "VALIDE", "Validé"
        ANNULE = "ANNULE", "Annulé"

    # Identifiant public, imprévisible : utilisé dans les URLs /merci/<jeton>/
    # et /recu/<jeton>.pdf. On n'expose JAMAIS l'id numérique (1, 2, 3…).
    jeton = models.UUIDField(
        "jeton public", default=uuid.uuid4, unique=True, editable=False
    )
    donateur = models.ForeignKey(
        Donateur, on_delete=models.PROTECT, related_name="dons", verbose_name="donateur"
    )
    epicerie = models.ForeignKey(
        Epicerie, on_delete=models.PROTECT, related_name="dons", verbose_name="épicerie"
    )
    date_don = models.DateTimeField("date du don", default=timezone.now, db_index=True)
    commentaire = models.TextField("commentaire", blank=True)
    statut = models.CharField(
        "statut", max_length=10, choices=Statut.choices, default=Statut.DECLARE
    )

    class Meta:
        verbose_name = "don"
        verbose_name_plural = "dons"
        ordering = ["-date_don"]
        constraints = [
            # Le statut ne peut prendre que l'une des 3 valeurs prévues
            models.CheckConstraint(
                condition=Q(statut__in=["DECLARE", "VALIDE", "ANNULE"]),
                name="don_statut_valide",
            ),
        ]

    def __str__(self):
        return f"Don du {self.date_don:%d/%m/%Y} — {self.donateur} — {self.epicerie.nom}"


class LigneDon(models.Model):
    """Un objet (ou lot d'objets identiques) au sein d'un don."""

    class Etat(models.TextChoices):
        NEUF = "NEUF", "Neuf"
        BON_ETAT = "BON_ETAT", "Bon état"
        USAGE = "USAGE", "Usagé"
        A_REPARER = "A_REPARER", "À réparer"

    # CASCADE : si un don était supprimé, ses lignes le seraient aussi
    don = models.ForeignKey(
        Don, on_delete=models.CASCADE, related_name="lignes", verbose_name="don"
    )
    categorie = models.ForeignKey(
        CategorieObjet,
        on_delete=models.PROTECT,
        related_name="lignes",
        verbose_name="catégorie",
    )
    description = models.CharField("description", max_length=200, blank=True)
    quantite = models.PositiveSmallIntegerField(
        "quantité", default=1, validators=[MinValueValidator(1)]
    )
    etat = models.CharField("état", max_length=10, choices=Etat.choices)

    class Meta:
        verbose_name = "objet donné"
        verbose_name_plural = "objets donnés"
        ordering = ["id"]
        constraints = [
            # Contrainte CHECK en base : au moins 1 objet par ligne
            models.CheckConstraint(
                condition=Q(quantite__gte=1), name="lignedon_quantite_min_1"
            ),
            models.CheckConstraint(
                condition=Q(etat__in=["NEUF", "BON_ETAT", "USAGE", "A_REPARER"]),
                name="lignedon_etat_valide",
            ),
        ]

    def __str__(self):
        return f"{self.quantite} × {self.categorie}" + (
            f" — {self.description}" if self.description else ""
        )


# =============================================================================
# Reçus (accusés de réception) et numérotation
# =============================================================================
class Recu(models.Model):
    """Accusé de réception d'un don (PAS un reçu fiscal).

    Le PDF n'est pas stocké : il est régénéré à la demande à partir de ces
    données, il est donc toujours cohérent avec la base.
    Numéro au format SPF-AAAA-000001, attribué par services.py grâce à
    CompteurRecu (sans trou ni doublon).
    """

    # PROTECT : impossible de supprimer un don qui a un reçu
    don = models.OneToOneField(
        Don, on_delete=models.PROTECT, related_name="recu", verbose_name="don"
    )
    annee = models.PositiveSmallIntegerField("année")
    sequence = models.PositiveIntegerField("numéro dans l'année")
    numero = models.CharField("numéro de reçu", max_length=20, unique=True)
    date_emission = models.DateTimeField("émis le", default=timezone.now)
    # Reste à False si l'envoi de l'email a échoué : permet de repérer les échecs
    email_envoye = models.BooleanField("email envoyé", default=False)

    class Meta:
        verbose_name = "reçu"
        verbose_name_plural = "reçus"
        ordering = ["-annee", "-sequence"]
        constraints = [
            # Pas deux reçus avec le même numéro dans la même année
            models.UniqueConstraint(
                fields=["annee", "sequence"], name="recu_annee_sequence_unique"
            ),
            models.CheckConstraint(
                condition=Q(sequence__gte=1), name="recu_sequence_min_1"
            ),
        ]

    @staticmethod
    def formater_numero(annee, sequence):
        """Construit le numéro lisible, ex. (2026, 42) -> 'SPF-2026-000042'."""
        return f"SPF-{annee}-{sequence:06d}"

    def save(self, *args, **kwargs):
        # Le numéro est toujours déduit de (annee, sequence) : pas d'incohérence possible
        self.numero = self.formater_numero(self.annee, self.sequence)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.numero


class CompteurRecu(models.Model):
    """Compteur de numérotation des reçus : une ligne par année.

    Pour attribuer un numéro, services.py verrouille la ligne de l'année
    (select_for_update), lit dernier_numero, l'incrémente et l'enregistre.
    Deux envois simultanés attendent donc leur tour : ni trou, ni doublon.
    """

    annee = models.PositiveSmallIntegerField("année", primary_key=True)
    dernier_numero = models.PositiveIntegerField("dernier numéro attribué", default=0)

    class Meta:
        verbose_name = "compteur de reçus"
        verbose_name_plural = "compteurs de reçus"
        ordering = ["-annee"]

    def __str__(self):
        return f"{self.annee} : {self.dernier_numero}"
