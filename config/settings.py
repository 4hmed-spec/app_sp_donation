"""
Configuration du projet Dons SPF.

Toute la configuration sensible ou dépendante de l'environnement (clé secrète,
base de données, email, domaines autorisés…) est lue dans le fichier `.env`
grâce à django-environ. Rien de sensible ne doit être écrit en dur ici.

Pour passer de SQLite à PostgreSQL, il suffit de changer DATABASE_URL dans .env.
"""

from pathlib import Path

import environ

# Dossier racine du projet (celui qui contient manage.py)
BASE_DIR = Path(__file__).resolve().parent.parent

# --- Lecture du fichier .env -------------------------------------------------
# On déclare ici le type et la valeur par défaut de chaque variable.
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
    SITE_URL=(str, "http://127.0.0.1:8000"),
    EMAIL_USE_TLS=(bool, True),
    EMAIL_PORT=(int, 587),
    SECURE_SSL_REDIRECT=(bool, True),
)
environ.Env.read_env(BASE_DIR / ".env")

# --- Sécurité ---------------------------------------------------------------
SECRET_KEY = env("SECRET_KEY")  # obligatoire : plante au démarrage si absente
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

# URL publique du site, utilisée pour générer les QR codes (SITE_URL/don/<slug>/)
SITE_URL = env("SITE_URL").rstrip("/")

# --- Applications -----------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Notre application métier
    "dons",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Dossier templates/ à la racine du projet
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Base de données ----------------------------------------------------------
# Exemples de DATABASE_URL :
#   SQLite     : sqlite:///db.sqlite3
#   PostgreSQL : postgres://utilisateur:motdepasse@localhost:5432/dons_spf
DATABASES = {
    "default": env.db("DATABASE_URL", default="sqlite:///db.sqlite3"),
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Mots de passe ------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Langue et fuseau horaire -------------------------------------------------
LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

# --- Fichiers statiques (CSS, JS) ---------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"  # rempli par "collectstatic" en prod

# --- Emails -----------------------------------------------------------------
# En dev : EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
#          (les emails s'affichent dans le terminal, rien n'est envoyé).
# En prod : EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
#          + les identifiants SMTP de Brevo ou Mailjet.
EMAIL_BACKEND = env(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env("EMAIL_PORT")
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env("EMAIL_USE_TLS")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Secours populaire <no-reply@exemple.fr>")

# --- Journalisation (logs) ----------------------------------------------------
# Les erreurs (ex. échec d'envoi d'email) sont affichées dans la console,
# ce qui est aussi ce que lisent les hébergeurs type Scalingo / Clever Cloud.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "dons": {"handlers": ["console"], "level": "INFO"},
    },
}

# --- Réglages de sécurité supplémentaires en production -----------------------
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT")
    # Derrière le proxy HTTPS de l'hébergeur
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30  # 30 jours
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
