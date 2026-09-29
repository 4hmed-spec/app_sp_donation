"""
Commande d'initialisation des données de référence.

Utilisation :
    python manage.py initialiser_donnees          -> crée les catégories d'objets
    python manage.py initialiser_donnees --demo   -> + un comité et une épicerie de test

Idempotente : on peut la relancer autant de fois qu'on veut, elle ne crée que
ce qui manque et ne modifie jamais ce qui existe déjà (par exemple l'ordre ou
l'activation d'une catégorie changés par la fédé dans l'admin).
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from dons.models import CategorieObjet, Comite, Epicerie

# TODO (point ouvert) : liste définitive des catégories à valider par la fédé.
# L'ordre de cette liste = ordre d'affichage dans le formulaire.
CATEGORIES = [
    "Mobilier",
    "Électroménager",
    "Vêtements",
    "Chaussures",
    "Linge de maison",
    "Vaisselle",
    "Jouets",
    "Livres",
    "Puériculture",
    "Informatique",
    "Hygiène",
    "Alimentaire",
    "Autre",
]


class Command(BaseCommand):
    help = "Crée les catégories d'objets (et, avec --demo, un comité et une épicerie de test)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--demo",
            action="store_true",
            help="Crée aussi un comité et une épicerie de démonstration (slug « demo »).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        # --- Catégories ---
        nb_crees = 0
        for position, nom in enumerate(CATEGORIES, start=1):
            _, cree = CategorieObjet.objects.get_or_create(
                nom=nom, defaults={"ordre": position * 10, "active": True}
            )
            nb_crees += cree
        self.stdout.write(
            f"Catégories : {nb_crees} créée(s), {len(CATEGORIES) - nb_crees} déjà présente(s)."
        )

        # --- Données de démonstration ---
        if options["demo"]:
            comite, _ = Comite.objects.get_or_create(nom="Comité de démonstration")
            epicerie, cree = Epicerie.objects.get_or_create(
                slug="demo",
                defaults={
                    "nom": "Épicerie de démonstration",
                    "comite": comite,
                    "adresse": "1 rue de la Solidarité",
                    "code_postal": "75011",
                    "ville": "Paris",
                },
            )
            etat = "créée" if cree else "déjà présente"
            self.stdout.write(f"Épicerie de démonstration {etat} : /don/{epicerie.slug}/")

        self.stdout.write(self.style.SUCCESS("Initialisation terminée."))
