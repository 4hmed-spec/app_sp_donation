"""
Back-office de la fédé : l'admin Django, personnalisé.

Accessible sur /admin/ aux comptes « staff ». Pour chaque table, une classe
« …Admin » décrit les colonnes affichées, les filtres, la recherche, les
champs modifiables et les actions possibles.

Règles de sécurité appliquées ici :
- on ne crée pas de don depuis l'admin (un don vient toujours du formulaire,
  avec son reçu : jamais de don sans reçu) ;
- on ne supprime jamais un don ni un reçu (numérotation sans trou) ;
- reçus et compteurs sont en lecture seule.

TODO (point ouvert) : rôles dans le back-office. Si un bénévole ne doit voir
que les dons de son épicerie, il faudra relier chaque compte à une épicerie
puis filtrer `get_queryset()` dans DonAdmin (et les autres) selon l'utilisateur.
"""

from django.contrib import admin, messages
from django.db.models import Count, OuterRef, Subquery, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from . import services
from .models import CategorieObjet, Comite, CompteurRecu, Don, Donateur, Epicerie, LigneDon, Recu


# =============================================================================
# Comités
# =============================================================================
@admin.register(Comite)
class ComiteAdmin(admin.ModelAdmin):
    list_display = ["nom", "nb_epiceries"]
    search_fields = ["nom"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_nb_epiceries=Count("epiceries"))

    @admin.display(description="épiceries", ordering="_nb_epiceries")
    def nb_epiceries(self, obj):
        return obj._nb_epiceries


# =============================================================================
# Épiceries : liens vers le formulaire et le QR code
# =============================================================================
@admin.register(Epicerie)
class EpicerieAdmin(admin.ModelAdmin):
    list_display = ["nom", "comite", "ville", "active", "lien_formulaire", "lien_qrcode"]
    list_filter = ["active", "comite"]
    search_fields = ["nom", "ville", "slug"]
    list_select_related = ["comite"]
    # À la création, l'identifiant d'URL est proposé automatiquement à partir du nom
    prepopulated_fields = {"slug": ["nom"]}

    def get_readonly_fields(self, request, obj=None):
        # Une fois l'épicerie créée, le slug est figé : le modifier casserait
        # les QR codes déjà imprimés et affichés dans l'épicerie.
        return ["slug"] if obj else []

    def get_prepopulated_fields(self, request, obj=None):
        return {} if obj else self.prepopulated_fields

    @admin.display(description="formulaire")
    def lien_formulaire(self, obj):
        url = reverse("dons:formulaire", kwargs={"slug": obj.slug})
        return format_html('<a href="{}" target="_blank">ouvrir le formulaire</a>', url)

    @admin.display(description="QR code")
    def lien_qrcode(self, obj):
        url = reverse("admin:dons_epicerie_qrcode", args=[obj.pk])
        return format_html('<a href="{}">télécharger le QR code</a>', url)

    def get_urls(self):
        # Ajoute l'adresse /admin/dons/epicerie/<id>/qrcode/ ; admin_view() la
        # réserve aux comptes staff connectés (les autres vont sur la page de connexion).
        urls_perso = [
            path(
                "<int:pk>/qrcode/",
                self.admin_site.admin_view(self.vue_qrcode),
                name="dons_epicerie_qrcode",
            ),
        ]
        return urls_perso + super().get_urls()

    def vue_qrcode(self, request, pk):
        """Renvoie le QR code (PNG) pointant vers SITE_URL/don/<slug>/."""
        epicerie = get_object_or_404(Epicerie, pk=pk)
        reponse = HttpResponse(services.generer_qrcode_png(epicerie), content_type="image/png")
        reponse["Content-Disposition"] = f'attachment; filename="qrcode-{epicerie.slug}.png"'
        return reponse


# =============================================================================
# Catégories : ordre et activation modifiables directement dans la liste
# =============================================================================
@admin.register(CategorieObjet)
class CategorieObjetAdmin(admin.ModelAdmin):
    list_display = ["nom", "icone", "ordre", "active"]
    list_editable = ["icone", "ordre", "active"]
    search_fields = ["nom"]

    def has_delete_permission(self, request, obj=None):
        # On désactive une catégorie, on ne la supprime pas (les anciens dons l'utilisent)
        return False


# =============================================================================
# Donateurs
# =============================================================================
@admin.register(Donateur)
class DonateurAdmin(admin.ModelAdmin):
    list_display = ["nom", "prenom", "email", "telephone", "ville", "accepte_contact", "lien_dons"]
    list_filter = ["accepte_contact"]
    search_fields = ["nom", "prenom", "email", "telephone"]
    readonly_fields = ["consentement_rgpd", "date_consentement", "date_creation", "date_modification"]
    fieldsets = [
        ("Identité", {"fields": ["prenom", "nom", "email", "telephone"]}),
        ("Adresse", {"fields": ["adresse", "code_postal", "ville"]}),
        ("RGPD et contact", {"fields": ["consentement_rgpd", "date_consentement", "accepte_contact"]}),
        ("Traçabilité", {"fields": ["date_creation", "date_modification"]}),
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_nb_dons=Count("dons"))

    def has_add_permission(self, request):
        # Un donateur est créé par le formulaire public, avec son consentement
        return False

    @admin.display(description="dons", ordering="_nb_dons")
    def lien_dons(self, obj):
        url = reverse("admin:dons_don_changelist") + f"?donateur__id__exact={obj.pk}"
        return format_html('<a href="{}">{} don(s)</a>', url, obj._nb_dons)


# =============================================================================
# Dons
# =============================================================================
class LigneDonInline(admin.TabularInline):
    """Les objets du don, affichés dans la fiche du don (corrigeables si besoin)."""

    model = LigneDon
    extra = 0
    min_num = 1  # au moins 1 objet
    max_num = 20  # au plus 20 objets
    fields = ["categorie", "description", "quantite", "etat"]


@admin.register(Don)
class DonAdmin(admin.ModelAdmin):
    inlines = [LigneDonInline]
    list_display = [
        "numero_recu", "date_don", "nom_donateur", "nom_epicerie",
        "nb_objets", "statut", "email_envoye", "lien_pdf",
    ]
    list_filter = [
        "statut",
        ("epicerie__comite", admin.RelatedOnlyFieldListFilter),
        ("epicerie", admin.RelatedOnlyFieldListFilter),
        "date_don",
        ("lignes__categorie", admin.RelatedOnlyFieldListFilter),
    ]
    search_fields = ["recu__numero", "donateur__nom", "donateur__prenom", "donateur__email"]
    date_hierarchy = "date_don"
    list_select_related = ["recu", "donateur", "epicerie"]
    actions = ["action_valider", "action_annuler", "action_export_csv"]

    # Le statut ne se change QUE par les actions « valider » / « annuler »,
    # qui enregistrent aussi qui a validé et quand.
    readonly_fields = [
        "numero_recu", "lien_pdf", "jeton", "donateur", "date_don",
        "statut", "date_validation", "valide_par",
    ]
    fieldsets = [
        (None, {"fields": ["numero_recu", "lien_pdf", "statut", "date_validation", "valide_par"]}),
        ("Don", {"fields": ["donateur", "epicerie", "date_don", "commentaire"]}),
        ("Technique", {"fields": ["jeton"], "classes": ["collapse"]}),
    ]

    def get_queryset(self, request):
        # Total des quantités calculé par une sous-requête : il reste juste même
        # quand un filtre (ex. par catégorie) ajoute une jointure sur les lignes.
        total_objets = (
            LigneDon.objects.filter(don=OuterRef("pk"))
            .values("don")
            .annotate(total=Sum("quantite"))
            .values("total")
        )
        return super().get_queryset(request).annotate(_nb_objets=Subquery(total_objets))

    # --- Interdictions -------------------------------------------------------
    def has_add_permission(self, request):
        # Un don vient toujours du formulaire public (avec son reçu)
        return False

    def has_delete_permission(self, request, obj=None):
        # On annule un don, on ne le supprime jamais
        return False

    # --- Colonnes calculées ------------------------------------------------
    @admin.display(description="n° de reçu", ordering="recu__numero")
    def numero_recu(self, obj):
        return obj.recu.numero

    @admin.display(description="donateur", ordering="donateur__nom")
    def nom_donateur(self, obj):
        return f"{obj.donateur.prenom} {obj.donateur.nom}"

    @admin.display(description="épicerie", ordering="epicerie__nom")
    def nom_epicerie(self, obj):
        return obj.epicerie.nom

    @admin.display(description="objets", ordering="_nb_objets")
    def nb_objets(self, obj):
        return getattr(obj, "_nb_objets", None)

    @admin.display(description="email envoyé", boolean=True)
    def email_envoye(self, obj):
        return obj.recu.email_envoye

    @admin.display(description="reçu PDF")
    def lien_pdf(self, obj):
        url = reverse("dons:recu_pdf", kwargs={"jeton": obj.jeton})
        return format_html('<a href="{}">PDF</a>', url)

    # --- Actions (menu déroulant au-dessus de la liste) ---------------------
    @admin.action(description="Marquer comme validé")
    def action_valider(self, request, queryset):
        nb = services.valider_dons(queryset, request.user)
        ignores = queryset.count() - nb
        self.message_user(request, f"{nb} don(s) validé(s).", messages.SUCCESS)
        if ignores:
            self.message_user(
                request,
                f"{ignores} don(s) ignoré(s) : seuls les dons « Déclaré » peuvent être validés.",
                messages.WARNING,
            )

    @admin.action(description="Marquer comme annulé")
    def action_annuler(self, request, queryset):
        nb = services.annuler_dons(queryset)
        self.message_user(request, f"{nb} don(s) annulé(s).", messages.SUCCESS)

    @admin.action(description="Exporter en CSV (une ligne par objet)")
    def action_export_csv(self, request, queryset):
        horodatage = timezone.localtime().strftime("%Y%m%d-%H%M")
        reponse = HttpResponse(content_type="text/csv; charset=utf-8")
        reponse["Content-Disposition"] = f'attachment; filename="dons-{horodatage}.csv"'
        services.exporter_dons_csv(queryset, reponse)
        return reponse


# =============================================================================
# Reçus et compteurs : lecture seule
# =============================================================================
class LectureSeuleMixin:
    """Interdit l'ajout, la modification et la suppression (consultation uniquement)."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Recu)
class RecuAdmin(LectureSeuleMixin, admin.ModelAdmin):
    list_display = ["numero", "date_emission", "donateur", "epicerie", "email_envoye", "lien_pdf"]
    list_filter = ["email_envoye", "annee"]
    search_fields = ["numero", "don__donateur__nom", "don__donateur__email"]
    list_select_related = ["don__donateur", "don__epicerie"]
    actions = ["action_renvoyer_email"]

    @admin.display(description="donateur")
    def donateur(self, obj):
        return obj.don.donateur

    @admin.display(description="épicerie")
    def epicerie(self, obj):
        return obj.don.epicerie.nom

    @admin.display(description="reçu PDF")
    def lien_pdf(self, obj):
        url = reverse("dons:recu_pdf", kwargs={"jeton": obj.don.jeton})
        return format_html('<a href="{}">PDF</a>', url)

    @admin.action(description="Renvoyer l'email avec le reçu")
    def action_renvoyer_email(self, request, queryset):
        # Utile pour les reçus dont l'envoi a échoué (filtre « email envoyé : Non »)
        ok = sum(services.envoyer_recu_par_email(recu.pk) for recu in queryset)
        echecs = queryset.count() - ok
        self.message_user(request, f"{ok} email(s) envoyé(s).", messages.SUCCESS)
        if echecs:
            self.message_user(request, f"{echecs} échec(s) : voir les logs.", messages.ERROR)


@admin.register(CompteurRecu)
class CompteurRecuAdmin(LectureSeuleMixin, admin.ModelAdmin):
    list_display = ["annee", "dernier_numero"]
