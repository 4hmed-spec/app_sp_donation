"""
Tests automatisés de l'application dons.

Lancer tous les tests :   python manage.py test
Lancer un seul groupe :   python manage.py test dons.tests.RefusFormulaireTests

Django crée une base de test vide et temporaire (la vraie base n'est jamais
touchée), exécute chaque test dans une transaction annulée à la fin, et les
emails sont capturés dans `mail.outbox` au lieu d'être envoyés.

Organisation :
- DonneesDeTestMixin      : création des données communes + formulaire valide
- ParcoursDonateurTests   : un don complet, confirmation, PDF, email
- RefusFormulaireTests    : chaque cas de refus -> rien en base
- EpicerieIntrouvableTests: 404
- NumerotationTests       : 1, 2, 3… par année
- TransactionTests        : tout ou rien
- ContraintesBaseTests    : les CHECK de la base lèvent IntegrityError
- DeduplicationTests      : réutilisation d'un donateur (email + nom)
- EmailTests              : échec d'envoi sans perte du don
- AdminTests              : pages admin, QR code, actions, export CSV
- CommandeInitialisationTests : initialiser_donnees idempotente
"""

import csv
import io
from io import StringIO

from django.contrib.auth.models import User
from django.core import mail
from django.core.mail.backends.base import BaseEmailBackend
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from . import services
from .models import (
    CategorieObjet,
    Comite,
    CompteurRecu,
    Don,
    Donateur,
    Epicerie,
    LigneDon,
    Recu,
)


class BackendEmailEnPanne(BaseEmailBackend):
    """Faux serveur d'email qui échoue toujours (pour simuler une panne SMTP)."""

    def send_messages(self, messages):
        raise ConnectionError("Serveur SMTP injoignable (simulation)")


def texte_du_pdf(contenu):
    """Extrait le texte d'un PDF (bytes) pour vérifier ce qu'il contient."""
    lecteur = PdfReader(io.BytesIO(contenu))
    return " ".join(page.extract_text() for page in lecteur.pages)


# =============================================================================
# Données communes
# =============================================================================
class DonneesDeTestMixin:
    """Crée un comité, une épicerie, deux catégories, et fournit un POST valide."""

    @classmethod
    def setUpTestData(cls):
        cls.comite = Comite.objects.create(nom="Comité de test")
        cls.epicerie = Epicerie.objects.create(
            nom="Épicerie test", comite=cls.comite, adresse="1 rue A",
            code_postal="59000", ville="Lille", slug="test",
        )
        cls.mobilier = CategorieObjet.objects.create(nom="Mobilier", ordre=1)
        cls.vetements = CategorieObjet.objects.create(nom="Vêtements", ordre=2)
        cls.url_formulaire = reverse("dons:formulaire", kwargs={"slug": "test"})

    def donnees_post(self, objets=None, **modifs):
        """Construit les données d'un formulaire VALIDE ; `modifs` en change certaines.

        `objets` : liste de dicts {categorie, description, quantite, etat}.
        """
        if objets is None:
            objets = [
                {"categorie": self.mobilier.pk, "description": "bureau gris",
                 "quantite": "1", "etat": "BON_ETAT"},
                {"categorie": self.vetements.pk, "description": "manteaux",
                 "quantite": "3", "etat": "NEUF"},
            ]
        donnees = {
            "prenom": "Jean", "nom": "Dupont", "email": "jean.dupont@exemple.fr",
            "telephone": "06 12 34 56 78", "adresse": "2 rue B",
            "code_postal": "59000", "ville": "Lille",
            "commentaire": "", "consentement_rgpd": "on", "site_web": "",
            # Champs de gestion du formset (voir formulaire.html)
            "objets-TOTAL_FORMS": str(len(objets)),
            "objets-INITIAL_FORMS": "0",
            "objets-MIN_NUM_FORMS": "1",
            "objets-MAX_NUM_FORMS": "20",
        }
        for i, objet in enumerate(objets):
            for champ, valeur in objet.items():
                donnees[f"objets-{i}-{champ}"] = valeur
        donnees.update(modifs)
        # Une valeur None = champ absent (ex. case non cochée)
        return {k: v for k, v in donnees.items() if v is not None}

    def envoyer(self, donnees):
        """POST du formulaire, en exécutant les actions « après commit » (l'email)."""
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.url_formulaire, donnees)

    def assertRienEnBase(self):
        self.assertEqual(Donateur.objects.count(), 0)
        self.assertEqual(Don.objects.count(), 0)
        self.assertEqual(LigneDon.objects.count(), 0)
        self.assertEqual(Recu.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)


# =============================================================================
# Parcours complet
# =============================================================================
class ParcoursDonateurTests(DonneesDeTestMixin, TestCase):
    def test_formulaire_s_affiche(self):
        reponse = self.client.get(self.url_formulaire)
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Épicerie test")

    def test_don_complet_cree_tout_et_envoie_l_email_avec_le_pdf(self):
        reponse = self.envoyer(self.donnees_post())

        # Base de données : 1 donateur, 1 don, 2 lignes, 1 reçu
        self.assertEqual(Donateur.objects.count(), 1)
        self.assertEqual(Don.objects.count(), 1)
        don = Don.objects.get()
        self.assertEqual(don.lignes.count(), 2)
        self.assertEqual(don.statut, Don.Statut.DECLARE)
        self.assertEqual(don.epicerie, self.epicerie)
        donateur = don.donateur
        self.assertTrue(donateur.consentement_rgpd)
        self.assertEqual(donateur.telephone, "0612345678")  # normalisé
        recu = don.recu
        annee = timezone.localdate().year
        self.assertEqual(recu.numero, f"SPF-{annee}-000001")

        # POST -> redirect -> GET vers la page de confirmation (par jeton, pas par id)
        self.assertRedirects(reponse, reverse("dons:merci", kwargs={"jeton": don.jeton}))

        # Email : 1 message, au donateur, avec le PDF en pièce jointe
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["jean.dupont@exemple.fr"])
        self.assertIn(recu.numero, email.subject)
        nom_fichier, contenu, type_mime = email.attachments[0]
        self.assertEqual(nom_fichier, f"{recu.numero}.pdf")
        self.assertEqual(type_mime, "application/pdf")
        self.assertTrue(contenu.startswith(b"%PDF"))
        recu.refresh_from_db()
        self.assertTrue(recu.email_envoye)

    def test_page_merci_et_pdf(self):
        self.envoyer(self.donnees_post())
        don = Don.objects.get()

        merci = self.client.get(reverse("dons:merci", kwargs={"jeton": don.jeton}))
        self.assertContains(merci, don.recu.numero)

        pdf = self.client.get(reverse("dons:recu_pdf", kwargs={"jeton": don.jeton}))
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        texte = texte_du_pdf(pdf.content)
        self.assertIn(don.recu.numero, texte)
        self.assertIn("Dupont", texte)
        self.assertIn("bureau gris", texte)
        self.assertIn("Comité de test", texte)
        self.assertIn("Il ne constitue pas un reçu fiscal", texte)

    def test_rafraichir_la_page_merci_ne_cree_pas_de_second_don(self):
        reponse = self.envoyer(self.donnees_post())
        for _ in range(3):
            self.client.get(reponse["Location"])
        self.assertEqual(Don.objects.count(), 1)

    def test_jeton_inconnu_renvoie_404(self):
        faux = "00000000-0000-0000-0000-000000000000"
        self.assertEqual(self.client.get(f"/merci/{faux}/").status_code, 404)
        self.assertEqual(self.client.get(f"/recu/{faux}.pdf").status_code, 404)
        # Les id numériques ne sont pas acceptés dans les URLs publiques
        self.assertEqual(self.client.get("/merci/1/").status_code, 404)

    def test_don_annule_affiche_annule_sur_le_pdf(self):
        self.envoyer(self.donnees_post())
        don = Don.objects.get()
        services.annuler_dons(Don.objects.all())
        pdf = self.client.get(reverse("dons:recu_pdf", kwargs={"jeton": don.jeton}))
        self.assertIn("ANNULÉ", texte_du_pdf(pdf.content))
        merci = self.client.get(reverse("dons:merci", kwargs={"jeton": don.jeton}))
        self.assertContains(merci, "annulé")


# =============================================================================
# Refus : le formulaire est réaffiché et RIEN n'est enregistré
# =============================================================================
class RefusFormulaireTests(DonneesDeTestMixin, TestCase):
    def verifier_refus(self, donnees):
        reponse = self.envoyer(donnees)
        self.assertEqual(reponse.status_code, 200)  # page réaffichée, pas de redirection
        self.assertRienEnBase()
        return reponse

    def test_sans_consentement_rgpd(self):
        self.verifier_refus(self.donnees_post(consentement_rgpd=None))

    def test_aucun_objet(self):
        self.verifier_refus(self.donnees_post(objets=[]))

    def test_objet_laisse_vide(self):
        vide = {"categorie": "", "description": "", "quantite": "", "etat": ""}
        self.verifier_refus(self.donnees_post(objets=[vide]))

    def test_plus_de_20_objets(self):
        objet = {"categorie": self.mobilier.pk, "description": "chaise",
                 "quantite": "1", "etat": "USAGE"}
        self.verifier_refus(self.donnees_post(objets=[objet] * 21))

    def test_email_invalide(self):
        self.verifier_refus(self.donnees_post(email="pas-un-email"))

    def test_code_postal_invalide(self):
        for code in ["123", "ABCDE", "590000"]:
            with self.subTest(code_postal=code):
                self.verifier_refus(self.donnees_post(code_postal=code))

    def test_telephone_invalide(self):
        for tel in ["12", "abcdefghij", "06 12 34"]:
            with self.subTest(telephone=tel):
                self.verifier_refus(self.donnees_post(telephone=tel))

    def test_champs_obligatoires_manquants(self):
        for champ in ["prenom", "nom", "email"]:
            with self.subTest(champ=champ):
                self.verifier_refus(self.donnees_post(**{champ: ""}))

    def test_quantite_zero(self):
        objet = {"categorie": self.mobilier.pk, "description": "table",
                 "quantite": "0", "etat": "NEUF"}
        self.verifier_refus(self.donnees_post(objets=[objet]))

    def test_quantite_superieure_a_99(self):
        objet = {"categorie": self.mobilier.pk, "description": "table",
                 "quantite": "100", "etat": "NEUF"}
        self.verifier_refus(self.donnees_post(objets=[objet]))

    def test_description_manquante(self):
        objet = {"categorie": self.mobilier.pk, "description": "",
                 "quantite": "1", "etat": "NEUF"}
        self.verifier_refus(self.donnees_post(objets=[objet]))

    def test_categorie_inactive(self):
        inactive = CategorieObjet.objects.create(nom="Ancienne", active=False)
        objet = {"categorie": inactive.pk, "description": "x",
                 "quantite": "1", "etat": "NEUF"}
        self.verifier_refus(self.donnees_post(objets=[objet]))

    def test_champ_piege_rempli(self):
        self.verifier_refus(self.donnees_post(site_web="http://spam.example"))

    def test_champs_facultatifs_vides_acceptes(self):
        # Contre-épreuve : sans téléphone ni adresse, le don passe
        self.envoyer(self.donnees_post(telephone="", adresse="", code_postal="", ville=""))
        self.assertEqual(Don.objects.count(), 1)


# =============================================================================
# Épicerie inconnue ou inactive
# =============================================================================
class EpicerieIntrouvableTests(DonneesDeTestMixin, TestCase):
    def test_epicerie_inconnue_renvoie_404(self):
        reponse = self.client.get(reverse("dons:formulaire", kwargs={"slug": "inconnue"}))
        self.assertEqual(reponse.status_code, 404)

    def test_epicerie_inactive_renvoie_404_en_get_et_en_post(self):
        Epicerie.objects.filter(pk=self.epicerie.pk).update(active=False)
        self.assertEqual(self.client.get(self.url_formulaire).status_code, 404)
        self.assertEqual(self.envoyer(self.donnees_post()).status_code, 404)
        self.assertRienEnBase()


# =============================================================================
# Numérotation des reçus
# =============================================================================
class NumerotationTests(DonneesDeTestMixin, TestCase):
    def test_numerotation_sequentielle(self):
        for i in range(3):
            self.envoyer(self.donnees_post(email=f"donateur{i}@exemple.fr"))
        annee = timezone.localdate().year
        self.assertEqual(
            list(Recu.objects.order_by("sequence").values_list("sequence", flat=True)),
            [1, 2, 3],
        )
        self.assertEqual(
            sorted(Recu.objects.values_list("numero", flat=True)),
            [f"SPF-{annee}-00000{i}" for i in (1, 2, 3)],
        )
        self.assertEqual(CompteurRecu.objects.get(annee=annee).dernier_numero, 3)

    def test_chaque_annee_repart_a_1(self):
        with transaction.atomic():
            self.assertEqual(services.attribuer_numero_recu(2030), 1)
            self.assertEqual(services.attribuer_numero_recu(2030), 2)
            self.assertEqual(services.attribuer_numero_recu(2031), 1)

    def test_format_du_numero(self):
        self.assertEqual(Recu.formater_numero(2026, 42), "SPF-2026-000042")


# =============================================================================
# Transaction tout-ou-rien
# =============================================================================
class TransactionTests(DonneesDeTestMixin, TestCase):
    def test_une_ligne_invalide_annule_tout(self):
        """Le service reçoit une 2e ligne invalide (quantité 0, refusée par la base) :
        donateur, don, 1re ligne, reçu et numéro de reçu sont tous annulés."""
        lignes = [
            {"categorie": self.mobilier, "description": "table", "quantite": 1, "etat": "NEUF"},
            {"categorie": self.mobilier, "description": "chaise", "quantite": 0, "etat": "NEUF"},
        ]
        coordonnees = {"nom": "Durand", "prenom": "Léa", "email": "lea@exemple.fr",
                       "telephone": "", "adresse": "", "code_postal": "", "ville": ""}
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(IntegrityError):
                services.enregistrer_don(self.epicerie, coordonnees, lignes)
        self.assertRienEnBase()
        self.assertFalse(CompteurRecu.objects.filter(dernier_numero__gt=0).exists())

    def test_une_ligne_invalide_dans_le_formulaire_n_enregistre_rien(self):
        objets = [
            {"categorie": self.mobilier.pk, "description": "table", "quantite": "1", "etat": "NEUF"},
            {"categorie": self.mobilier.pk, "description": "chaise", "quantite": "0", "etat": "NEUF"},
        ]
        reponse = self.envoyer(self.donnees_post(objets=objets))
        self.assertEqual(reponse.status_code, 200)
        self.assertRienEnBase()

    def test_le_numero_n_est_pas_consomme_par_un_echec(self):
        """Après un échec, le don suivant reçoit bien le n°1 (pas de trou)."""
        self.test_une_ligne_invalide_annule_tout()
        self.envoyer(self.donnees_post())
        self.assertEqual(Recu.objects.get().sequence, 1)

    def test_don_sans_objet_refuse_par_le_service(self):
        with self.assertRaises(ValueError):
            services.enregistrer_don(self.epicerie, {}, [])
        self.assertRienEnBase()


# =============================================================================
# Contraintes en base (CHECK / UNIQUE) : même en contournant les formulaires
# =============================================================================
class ContraintesBaseTests(DonneesDeTestMixin, TestCase):
    def setUp(self):
        self.donateur = Donateur.objects.create(
            nom="A", prenom="B", email="a@b.fr",
            consentement_rgpd=True, date_consentement=timezone.now(),
        )
        self.don = Don.objects.create(donateur=self.donateur, epicerie=self.epicerie)

    def assertRefuseParLaBase(self, fonction):
        # atomic() : l'erreur n'empêche pas la suite du test
        with self.assertRaises(IntegrityError), transaction.atomic():
            fonction()

    def test_donateur_sans_consentement(self):
        self.assertRefuseParLaBase(lambda: Donateur.objects.create(
            nom="X", prenom="Y", email="x@y.fr",
            consentement_rgpd=False, date_consentement=timezone.now(),
        ))

    def test_quantite_zero_et_superieure_a_99(self):
        for quantite in (0, 100):
            with self.subTest(quantite=quantite):
                self.assertRefuseParLaBase(lambda: LigneDon.objects.create(
                    don=self.don, categorie=self.mobilier, description="x",
                    quantite=quantite, etat="NEUF",
                ))

    def test_etat_inconnu(self):
        self.assertRefuseParLaBase(lambda: LigneDon.objects.create(
            don=self.don, categorie=self.mobilier, description="x", quantite=1, etat="CASSE",
        ))

    def test_statut_inconnu(self):
        self.assertRefuseParLaBase(
            lambda: Don.objects.filter(pk=self.don.pk).update(statut="PERDU")
        )

    def test_don_valide_sans_date_de_validation(self):
        self.assertRefuseParLaBase(
            lambda: Don.objects.filter(pk=self.don.pk).update(statut="VALIDE")
        )

    def test_recu_en_double_annee_sequence(self):
        Recu.objects.create(don=self.don, annee=2026, sequence=1)
        autre_don = Don.objects.create(donateur=self.donateur, epicerie=self.epicerie)
        self.assertRefuseParLaBase(
            lambda: Recu.objects.create(don=autre_don, annee=2026, sequence=1)
        )

    def test_deux_recus_pour_un_meme_don(self):
        Recu.objects.create(don=self.don, annee=2026, sequence=1)
        self.assertRefuseParLaBase(
            lambda: Recu.objects.create(don=self.don, annee=2026, sequence=2)
        )

    def test_nom_d_epicerie_en_double_dans_un_comite(self):
        self.assertRefuseParLaBase(lambda: Epicerie.objects.create(
            nom="Épicerie test", comite=self.comite, adresse="x",
            code_postal="59000", ville="Lille", slug="autre-slug",
        ))


# =============================================================================
# Déduplication des donateurs
# =============================================================================
class DeduplicationTests(DonneesDeTestMixin, TestCase):
    def test_meme_email_et_meme_nom_reutilise_la_fiche(self):
        self.envoyer(self.donnees_post())
        # Même personne, casse différente, nouveau téléphone, sans adresse
        self.envoyer(self.donnees_post(
            nom="DUPONT", email="Jean.Dupont@Exemple.fr",
            telephone="07 00 00 00 00", adresse="",
        ))
        self.assertEqual(Donateur.objects.count(), 1)
        self.assertEqual(Don.objects.count(), 2)
        donateur = Donateur.objects.get()
        self.assertEqual(donateur.telephone, "0700000000")  # remplacé par le plus récent
        self.assertEqual(donateur.adresse, "2 rue B")  # un champ vide n'efface pas

    def test_meme_email_mais_autre_nom_cree_une_nouvelle_fiche(self):
        self.envoyer(self.donnees_post())
        self.envoyer(self.donnees_post(nom="Martin"))
        self.assertEqual(Donateur.objects.count(), 2)
        # La fiche de Jean Dupont n'a pas été modifiée par l'inconnu
        self.assertTrue(Donateur.objects.filter(nom="Dupont").exists())


# =============================================================================
# Emails
# =============================================================================
class EmailTests(DonneesDeTestMixin, TestCase):
    @override_settings(EMAIL_BACKEND="dons.tests.BackendEmailEnPanne")
    def test_echec_d_envoi_ne_perd_pas_le_don(self):
        with self.assertLogs("dons.services", level="ERROR"):
            reponse = self.envoyer(self.donnees_post())
        don = Don.objects.get()
        self.assertRedirects(reponse, reverse("dons:merci", kwargs={"jeton": don.jeton}))
        self.assertFalse(don.recu.email_envoye)  # repérable dans l'admin
        # Le reçu reste téléchargeable
        pdf = self.client.get(reverse("dons:recu_pdf", kwargs={"jeton": don.jeton}))
        self.assertEqual(pdf.status_code, 200)

    def test_pas_d_email_si_la_transaction_echoue(self):
        lignes = [{"categorie": self.mobilier, "description": "x", "quantite": 0, "etat": "NEUF"}]
        coordonnees = {"nom": "A", "prenom": "B", "email": "a@b.fr", "telephone": "",
                       "adresse": "", "code_postal": "", "ville": ""}
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(IntegrityError):
                services.enregistrer_don(self.epicerie, coordonnees, lignes)
        self.assertEqual(len(callbacks), 0)
        self.assertEqual(len(mail.outbox), 0)


# =============================================================================
# Admin : pages, QR code, actions, export CSV
# =============================================================================
class AdminTests(DonneesDeTestMixin, TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "admin@exemple.fr", "mdp-test-123")
        # Deux dons : le 1er avec 2 objets, le 2e avec 1 objet
        self.envoyer(self.donnees_post())
        self.envoyer(self.donnees_post(
            nom="Martin", email="martin@exemple.fr",
            objets=[{"categorie": self.mobilier.pk, "description": "=1+1",
                     "quantite": "2", "etat": "USAGE"}],
        ))
        mail.outbox.clear()
        self.don1, self.don2 = Don.objects.order_by("recu__sequence")

    # --- QR code réservé aux admins ---------------------------------------
    def test_qrcode_reserve_au_staff(self):
        url = reverse("admin:dons_epicerie_qrcode", args=[self.epicerie.pk])

        # Anonyme -> page de connexion
        reponse = self.client.get(url)
        self.assertEqual(reponse.status_code, 302)
        self.assertIn(reverse("admin:login"), reponse["Location"])

        # Utilisateur connecté mais pas staff -> page de connexion aussi
        User.objects.create_user("benevole", password="mdp-test-123")
        self.client.login(username="benevole", password="mdp-test-123")
        self.assertEqual(self.client.get(url).status_code, 302)

        # Admin -> image PNG
        self.client.force_login(self.admin)
        reponse = self.client.get(url)
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse["Content-Type"], "image/png")
        self.assertTrue(reponse.content.startswith(b"\x89PNG"))

    # --- Toutes les pages admin répondent ---------------------------------
    def test_pages_admin_repondent(self):
        self.client.force_login(self.admin)
        recu = self.don1.recu
        pages = [
            reverse("admin:index"),
            reverse("admin:dons_comite_changelist"),
            reverse("admin:dons_epicerie_changelist"),
            reverse("admin:dons_epicerie_add"),
            reverse("admin:dons_epicerie_change", args=[self.epicerie.pk]),
            reverse("admin:dons_categorieobjet_changelist"),
            reverse("admin:dons_donateur_changelist"),
            reverse("admin:dons_donateur_change", args=[self.don1.donateur_id]),
            reverse("admin:dons_don_changelist"),
            reverse("admin:dons_don_changelist") + "?statut__exact=DECLARE",
            reverse("admin:dons_don_changelist") + f"?lignes__categorie__id__exact={self.mobilier.pk}",
            reverse("admin:dons_don_changelist") + f"?q={recu.numero}",
            reverse("admin:dons_don_change", args=[self.don1.pk]),
            reverse("admin:dons_recu_changelist"),
            reverse("admin:dons_recu_change", args=[recu.pk]),
            reverse("admin:dons_compteurrecu_changelist"),
        ]
        for url in pages:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_recherche_par_numero_de_recu(self):
        self.client.force_login(self.admin)
        url = reverse("admin:dons_don_changelist") + f"?q={self.don2.recu.numero}"
        self.assertEqual(self.client.get(url).context["cl"].result_count, 1)

    def test_filtre_categorie_sans_doublon_ni_total_faux(self):
        self.client.force_login(self.admin)
        url = reverse("admin:dons_don_changelist") + f"?lignes__categorie__id__exact={self.mobilier.pk}"
        resultats = self.client.get(url).context["cl"].result_list
        self.assertEqual(len(resultats), 2)
        totaux = {d.pk: d._nb_objets for d in resultats}
        self.assertEqual(totaux, {self.don1.pk: 4, self.don2.pk: 2})

    # --- Interdictions : pas de création/suppression de don, reçus en lecture seule
    def test_creation_et_suppression_interdites(self):
        self.client.force_login(self.admin)
        interdits = [
            reverse("admin:dons_don_add"),
            reverse("admin:dons_don_delete", args=[self.don1.pk]),
            reverse("admin:dons_recu_add"),
            reverse("admin:dons_recu_delete", args=[self.don1.recu.pk]),
            reverse("admin:dons_compteurrecu_add"),
            reverse("admin:dons_donateur_add"),
        ]
        for url in interdits:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_recu_non_modifiable(self):
        self.client.force_login(self.admin)
        recu = self.don1.recu
        url = reverse("admin:dons_recu_change", args=[recu.pk])
        self.client.post(url, {"numero": "SPF-1999-999999", "sequence": 999})
        recu.refresh_from_db()
        self.assertEqual(recu.sequence, 1)

    # --- Actions ------------------------------------------------------------
    def lancer_action(self, action, dons):
        return self.client.post(
            reverse("admin:dons_don_changelist"),
            {"action": action, "_selected_action": [d.pk for d in dons]},
        )

    def test_action_valider(self):
        self.client.force_login(self.admin)
        self.lancer_action("action_valider", [self.don1])
        self.don1.refresh_from_db()
        self.assertEqual(self.don1.statut, Don.Statut.VALIDE)
        self.assertEqual(self.don1.valide_par, self.admin)
        self.assertIsNotNone(self.don1.date_validation)

    def test_action_annuler_puis_valider_ne_revalide_pas(self):
        self.client.force_login(self.admin)
        self.lancer_action("action_annuler", [self.don1])
        self.lancer_action("action_valider", [self.don1])
        self.don1.refresh_from_db()
        self.assertEqual(self.don1.statut, Don.Statut.ANNULE)
        self.assertTrue(Recu.objects.filter(don=self.don1).exists())  # reçu conservé

    def test_action_renvoyer_email(self):
        self.client.force_login(self.admin)
        Recu.objects.update(email_envoye=False)
        self.client.post(
            reverse("admin:dons_recu_changelist"),
            {"action": "action_renvoyer_email", "_selected_action": [self.don1.recu.pk]},
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(Recu.objects.get(pk=self.don1.recu.pk).email_envoye)

    # --- Export CSV ---------------------------------------------------------
    def test_export_csv(self):
        self.client.force_login(self.admin)
        reponse = self.lancer_action("action_export_csv", [self.don1, self.don2])
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("text/csv", reponse["Content-Type"])
        self.assertIn("attachment", reponse["Content-Disposition"])

        contenu = reponse.content.decode("utf-8")
        self.assertTrue(contenu.startswith("﻿"))  # BOM pour Excel
        lignes = list(csv.reader(StringIO(contenu[1:]), delimiter=";"))

        self.assertEqual(lignes[0], services.COLONNES_CSV)  # en-tête
        self.assertEqual(len(lignes), 1 + 3)  # une ligne par objet (2 + 1)
        donnees = [dict(zip(lignes[0], ligne)) for ligne in lignes[1:]]
        self.assertEqual(donnees[0]["numero_recu"], self.don1.recu.numero)
        self.assertEqual(donnees[0]["description"], "bureau gris")
        self.assertEqual(donnees[0]["categorie"], "Mobilier")
        self.assertEqual(donnees[0]["comite"], "Comité de test")
        self.assertEqual(donnees[1]["quantite"], "3")
        self.assertEqual(donnees[1]["etat"], "Neuf")
        self.assertEqual(donnees[2]["donateur_nom"], "Martin")
        # Texte commençant par « = » neutralisé (pas de formule dans Excel)
        self.assertEqual(donnees[2]["description"], "'=1+1")

    def test_categories_editables_dans_la_liste(self):
        self.client.force_login(self.admin)
        url = reverse("admin:dons_categorieobjet_changelist")
        self.client.post(url, {
            "form-TOTAL_FORMS": "2", "form-INITIAL_FORMS": "2",
            "form-0-id": self.mobilier.pk, "form-0-ordre": "5", "form-0-active": "on",
            "form-1-id": self.vetements.pk, "form-1-ordre": "1",  # décochée -> inactive
            "_save": "Enregistrer",
        })
        self.vetements.refresh_from_db()
        self.mobilier.refresh_from_db()
        self.assertEqual(self.mobilier.ordre, 5)
        self.assertFalse(self.vetements.active)


# =============================================================================
# Commande d'initialisation
# =============================================================================
class CommandeInitialisationTests(TestCase):
    def test_idempotente(self):
        call_command("initialiser_donnees", "--demo", stdout=StringIO())
        call_command("initialiser_donnees", "--demo", stdout=StringIO())
        self.assertEqual(CategorieObjet.objects.count(), 13)
        self.assertEqual(Comite.objects.count(), 1)
        self.assertEqual(Epicerie.objects.filter(slug="demo").count(), 1)

    def test_ne_modifie_pas_les_reglages_de_la_fede(self):
        call_command("initialiser_donnees", stdout=StringIO())
        CategorieObjet.objects.filter(nom="Jouets").update(ordre=1, active=False)
        call_command("initialiser_donnees", stdout=StringIO())
        jouets = CategorieObjet.objects.get(nom="Jouets")
        self.assertEqual((jouets.ordre, jouets.active), (1, False))

    def test_sans_demo_ne_cree_pas_d_epicerie(self):
        call_command("initialiser_donnees", stdout=StringIO())
        self.assertEqual(Epicerie.objects.count(), 0)
