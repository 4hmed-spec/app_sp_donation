"""
Logique métier de l'application (ce qui se passe quand un don est envoyé).

Les vues (views.py) s'occupent seulement du web : lire le formulaire, afficher
les pages. Tout ce qui touche à la base de données et aux règles du SPF est ici,
ce qui permet de le tester et de le réutiliser (admin, commandes…).

Fonctions principales :
- enregistrer_don()           : crée donateur + don + lignes + reçu, tout ou rien
- attribuer_numero_recu()     : numérotation sans trou ni doublon
- envoyer_recu_par_email()    : envoi du PDF, appelé APRÈS le commit
"""

import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.utils import timezone

from .models import CompteurRecu, Don, Donateur, LigneDon, Recu
from .pdf import generer_pdf_recu

logger = logging.getLogger(__name__)


# =============================================================================
# Donateur : réutilisation d'une fiche existante ou création
# =============================================================================
def trouver_ou_creer_donateur(donnees, accepte_contact):
    """Retourne le donateur correspondant, en le créant si besoin.

    `donnees` : dictionnaire des coordonnées (nom, prenom, email, telephone,
    adresse, code_postal, ville), déjà validées par le formulaire.

    On réutilise une fiche existante SEULEMENT si l'email ET le nom
    correspondent (insensible à la casse). Un inconnu qui taperait l'email de
    quelqu'un d'autre avec un autre nom obtient donc une nouvelle fiche.
    """
    maintenant = timezone.now()
    donateur = (
        Donateur.objects.filter(email__iexact=donnees["email"], nom__iexact=donnees["nom"])
        .order_by("id")
        .first()
    )

    if donateur is None:
        return Donateur.objects.create(
            **donnees,
            consentement_rgpd=True,
            date_consentement=maintenant,
            accepte_contact=accepte_contact,
        )

    # Fiche existante : on complète les coordonnées avec les nouvelles valeurs
    # renseignées (on n'efface jamais une info existante par un champ vide),
    # et on enregistre le consentement et le choix de contact les plus récents.
    for champ, valeur in donnees.items():
        if valeur:
            setattr(donateur, champ, valeur)
    donateur.consentement_rgpd = True
    donateur.date_consentement = maintenant
    donateur.accepte_contact = accepte_contact
    donateur.save()
    return donateur


# =============================================================================
# Numérotation des reçus
# =============================================================================
def attribuer_numero_recu(annee):
    """Retourne le prochain numéro de séquence pour `annee` (1, 2, 3…).

    DOIT être appelée à l'intérieur d'une transaction (transaction.atomic).

    select_for_update() pose un verrou sur la ligne du compteur de l'année
    jusqu'à la fin de la transaction : si deux donateurs envoient le
    formulaire au même moment, le second attend que le premier ait terminé.
    Résultat : ni doublon, ni trou (si la transaction échoue, l'incrément est
    annulé avec elle).
    """
    # 1) S'assurer que la ligne de l'année existe (premier don de l'année).
    #    Si deux requêtes la créent en même temps, l'une obtient une
    #    IntegrityError : on l'ignore, la ligne existe alors bien.
    try:
        with transaction.atomic():  # « point de sauvegarde » : l'erreur n'annule pas tout
            CompteurRecu.objects.get_or_create(annee=annee)
    except IntegrityError:
        pass

    # 2) Verrouiller la ligne, incrémenter, enregistrer.
    compteur = CompteurRecu.objects.select_for_update().get(annee=annee)
    compteur.dernier_numero += 1
    compteur.save(update_fields=["dernier_numero"])
    return compteur.dernier_numero


# =============================================================================
# Enregistrement complet d'un don
# =============================================================================
def enregistrer_don(epicerie, donnees_donateur, lignes, commentaire="", accepte_contact=False):
    """Enregistre un don complet et retourne l'objet Don créé.

    - epicerie         : l'Epicerie où le don est déposé
    - donnees_donateur : dict des coordonnées (voir trouver_ou_creer_donateur)
    - lignes           : liste de dicts {categorie, description, quantite, etat}

    Tout est fait dans UNE transaction : si une seule étape échoue (ligne
    invalide, erreur de base…), RIEN n'est enregistré. Il ne peut donc jamais
    exister de don sans reçu.
    """
    if not lignes:
        raise ValueError("Un don doit contenir au moins un objet.")

    with transaction.atomic():
        donateur = trouver_ou_creer_donateur(donnees_donateur, accepte_contact)

        don = Don.objects.create(
            donateur=donateur,
            epicerie=epicerie,
            commentaire=commentaire,
        )

        for ligne in lignes:
            LigneDon.objects.create(don=don, **ligne)

        annee = timezone.localdate(don.date_don).year
        recu = Recu.objects.create(
            don=don,
            annee=annee,
            sequence=attribuer_numero_recu(annee),
            date_emission=don.date_don,
        )

        # L'email ne part qu'une fois la transaction validée (commit).
        # Si la transaction échoue, aucun email n'est envoyé.
        transaction.on_commit(lambda: envoyer_recu_par_email(recu.pk))

    return don


# =============================================================================
# Envoi de l'accusé de réception par email
# =============================================================================
def envoyer_recu_par_email(recu_id):
    """Envoie l'accusé de réception (PDF en pièce jointe) au donateur.

    Un échec d'envoi est journalisé mais ne lève pas d'erreur : le don reste
    enregistré, le reçu reste téléchargeable, et `email_envoye` reste à False
    pour que la fédé repère les envois ratés dans l'admin.
    Retourne True si l'email est parti, False sinon.
    """
    try:
        recu = Recu.objects.select_related(
            "don__donateur", "don__epicerie__comite"
        ).get(pk=recu_id)
        don = recu.don

        corps = render_to_string("email_recu.txt", {"recu": recu, "don": don})
        message = EmailMessage(
            subject=f"Accusé de réception de votre don — {recu.numero}",
            body=corps,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[don.donateur.email],
        )
        message.attach(f"{recu.numero}.pdf", generer_pdf_recu(recu), "application/pdf")
        message.send(fail_silently=False)
    except Exception:
        # logger.exception écrit l'erreur complète dans les logs
        logger.exception("Échec de l'envoi de l'email pour le reçu id=%s", recu_id)
        return False

    # update() plutôt que save() : on ne touche qu'à ce champ
    Recu.objects.filter(pk=recu_id).update(email_envoye=True)
    return True
