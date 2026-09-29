# Dons SPF

Application de centralisation des **dons en nature** (meubles, vêtements,
électroménager…) déposés dans les épiceries solidaires du Secours populaire
français.

1. Le donateur dépose ses objets dans une épicerie solidaire.
2. Il scanne le **QR code** de l'épicerie avec son téléphone.
3. Il remplit le formulaire, sans créer de compte : ses coordonnées, puis ses objets.
4. Il reçoit tout de suite un **accusé de réception PDF**, téléchargeable et envoyé par email.
5. La fédé consulte, valide et exporte les dons dans le **back-office** (`/admin/`).
6. Plus tard, **Power BI** se branchera directement sur la base PostgreSQL.

> L'accusé de réception n'est **pas un reçu fiscal**. Aucun objet n'est valorisé en euros.

**Technologies :** Python 3.11+, Django 5.2 LTS, SQLite en développement et
PostgreSQL en test et en production, xhtml2pdf (PDF), qrcode (QR codes),
django-environ (configuration).

---

## Sommaire

1. [Installation sous Windows (PowerShell)](#1-installation-sous-windows-powershell)
2. [Utilisation au quotidien](#2-utilisation-au-quotidien)
3. [Tester depuis un téléphone (même Wi-Fi)](#3-tester-depuis-un-téléphone-même-wi-fi)
4. [Passer à PostgreSQL (Docker)](#4-passer-à-postgresql-docker)
5. [Tests automatisés](#5-tests-automatisés)
6. [Règles de travail](#6-règles-de-travail)
7. [Organisation du code](#7-organisation-du-code)
8. [Base de données et Power BI](#8-base-de-données-et-power-bi)
9. [Mise en production](#9-mise-en-production)
10. [Points encore ouverts (TODO)](#10-points-encore-ouverts-todo)

---

## 1. Installation sous Windows (PowerShell)

Prérequis : **Python 3.11 ou plus récent** et **Git**.

```powershell
py --version      # doit afficher Python 3.11 ou plus
git --version
```

Si `py` n'est pas reconnu, installez Python depuis https://www.python.org/downloads/
en cochant **« Add python.exe to PATH »**, puis rouvrez PowerShell.

### 1.1 Récupérer le code

```powershell
cd C:\Users\<vous>
git clone https://github.com/4hmed-spec/app_sp_donation.git
cd app_sp_donation
```

> Évitez de travailler dans `Téléchargements` ou dans un dossier synchronisé
> (OneDrive) : cela peut bloquer des fichiers.

### 1.2 Créer et activer l'environnement virtuel

L'environnement virtuel (`.venv`) isole les bibliothèques du projet de celles
de votre PC.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Si PowerShell répond « l'exécution de scripts est désactivée sur ce
système »**, autorisez les scripts locaux pour votre compte (à faire une seule
fois), puis relancez l'activation :

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
```

Une fois le venv activé, `(.venv)` s'affiche au début de la ligne. **Il faut
l'activer dans chaque nouveau terminal.**

### 1.3 Installer les dépendances

```powershell
pip install -r requirements.txt
```

### 1.4 Créer le fichier de configuration `.env`

```powershell
Copy-Item .env.example .env
```

Les valeurs par défaut conviennent au développement : base SQLite, emails
affichés dans le terminal. Le fichier `.env` contient des secrets en
production : **il n'est jamais commité** (il est listé dans `.gitignore`).

### 1.5 Créer la base et les données de départ

```powershell
python manage.py migrate                       # crée les tables (fichier db.sqlite3)
python manage.py initialiser_donnees --demo    # catégories + comité et épicerie de démo
python manage.py createsuperuser               # votre compte pour le back-office
```

- `initialiser_donnees` sans `--demo` crée seulement les catégories. On peut la
  relancer sans risque : elle ne crée que ce qui manque.
- `createsuperuser` : le mot de passe ne s'affiche pas pendant la frappe, c'est
  normal. Pour un mot de passe de test trop simple, répondez `y` à la question
  « Bypass password validation ».

### 1.6 Lancer le serveur

```powershell
python manage.py runserver
```

Laissez ce terminal ouvert, puis ouvrez dans le navigateur :

| Page | Adresse |
|---|---|
| Formulaire de l'épicerie de démo | http://127.0.0.1:8000/don/demo/ |
| Back-office | http://127.0.0.1:8000/admin/ |

En développement, les emails **ne partent pas** : ils s'affichent dans le
terminal du serveur. `Ctrl + C` arrête le serveur.

---

## 2. Utilisation au quotidien

À chaque nouvelle session de travail :

```powershell
cd C:\Users\<vous>\app_sp_donation
.\.venv\Scripts\Activate.ps1
git pull                          # récupérer les dernières modifications
pip install -r requirements.txt   # au cas où une dépendance a été ajoutée
python manage.py migrate          # au cas où une migration a été ajoutée
python manage.py runserver
```

### Dans le back-office (`/admin/`)

| Écran | Ce qu'on y fait |
|---|---|
| **Épiceries** | Créer une épicerie. Liens **« ouvrir le formulaire »** et **« télécharger le QR code »** (PNG à imprimer). L'identifiant d'URL (slug) ne se modifie plus après la création, pour ne pas casser les QR codes déjà imprimés. |
| **Dons** | Liste, recherche (n° de reçu, nom, email), filtres (statut, comité, épicerie, date, catégorie), fiche avec les objets, lien PDF. Actions : **Marquer comme validé**, **Marquer comme annulé**, **Exporter en CSV**. |
| **Donateurs** | Consultation et correction des coordonnées. |
| **Reçus** | Lecture seule. Le filtre **« email envoyé : Non »** montre les envois ratés, et l'action **« Renvoyer l'email »** permet de réessayer. |
| **Catégories** | Ordre d'affichage et activation, modifiables directement dans la liste. |

Pour lancer une action : cochez les dons, choisissez l'action dans la liste
**« Action »** au-dessus du tableau, puis cliquez sur **Envoyer**.

**Statuts d'un don :**

- **Déclaré** : le donateur a rempli le formulaire.
- **Validé** : un bénévole a vu les objets. La date et l'auteur de la validation sont enregistrés.
- **Annulé** : doublon, objets jamais déposés ou refusés, test… Le don et son
  numéro de reçu sont **conservés** (jamais supprimés), et le PDF porte un bandeau « ANNULÉ ».

**Export CSV :** une ligne par objet, séparateur `;`, encodé en UTF-8 avec BOM.
Il s'ouvre directement dans Excel, avec les bons accents.

---

## 3. Tester depuis un téléphone (même Wi-Fi)

Le PC et le téléphone doivent être connectés au **même réseau Wi-Fi**.

1. **Trouver l'adresse IP du PC :**
   ```powershell
   ipconfig
   ```
   Relevez l'**Adresse IPv4** de la carte Wi-Fi, par exemple `192.168.1.20`.

2. **Autoriser cette adresse dans `.env`** (remplacez `192.168.1.20` par la vôtre) :
   ```ini
   ALLOWED_HOSTS=127.0.0.1,localhost,192.168.1.20
   CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000,http://192.168.1.20:8000
   SITE_URL=http://192.168.1.20:8000
   ```
   `SITE_URL` est l'adresse encodée dans les QR codes : avec cette valeur, le QR
   code téléchargé depuis l'admin s'ouvre directement sur le téléphone.

3. **Lancer le serveur sur toutes les interfaces réseau :**
   ```powershell
   python manage.py runserver 0.0.0.0:8000
   ```
   Si le pare-feu Windows affiche une alerte, autorisez Python sur les
   **réseaux privés**.

4. **Sur le téléphone**, ouvrez `http://192.168.1.20:8000/don/demo/`, ou
   scannez le QR code de l'épicerie téléchargé depuis l'admin.

Si la page ne s'ouvre pas :

- vérifiez que le réseau Wi-Fi est en profil **« Privé »** dans Windows (Paramètres → Réseau) ;
- certains réseaux (université, entreprise, Wi-Fi public) isolent les
  appareils entre eux. Utilisez alors le partage de connexion du téléphone.

Pensez à remettre les valeurs par défaut dans `.env` une fois le test terminé.

---

## 4. Passer à PostgreSQL (Docker)

En test et en production, la base est PostgreSQL. **Seule la variable
`DATABASE_URL` du fichier `.env` change** : le code reste le même.

1. Installez **Docker Desktop** (https://www.docker.com/products/docker-desktop/) et lancez-le.

2. Démarrez un serveur PostgreSQL 16 dans un conteneur :
   ```powershell
   docker run --name dons-postgres `
     -e POSTGRES_USER=dons_spf `
     -e POSTGRES_PASSWORD=motdepasse_local `
     -e POSTGRES_DB=dons_spf `
     -p 5432:5432 `
     -v dons_spf_data:/var/lib/postgresql/data `
     -d postgres:16
   ```
   Le volume `dons_spf_data` conserve les données même si le conteneur est supprimé.

3. Dans `.env`, remplacez la ligne `DATABASE_URL` par :
   ```ini
   DATABASE_URL=postgres://dons_spf:motdepasse_local@localhost:5432/dons_spf
   ```

4. Créez les tables et les données dans cette nouvelle base (elle est vide) :
   ```powershell
   python manage.py migrate
   python manage.py initialiser_donnees --demo
   python manage.py createsuperuser
   python manage.py runserver
   ```

Commandes utiles :

```powershell
docker stop dons-postgres        # arrêter
docker start dons-postgres       # redémarrer (après un redémarrage du PC)
docker exec -it dons-postgres psql -U dons_spf -d dons_spf   # console SQL
```

Pour revenir à SQLite, remettez `DATABASE_URL=sqlite:///db.sqlite3`.

> Les données ne sont pas copiées d'une base à l'autre. SQLite sert seulement
> au développement : on repart d'une base vide sous PostgreSQL.

---

## 5. Tests automatisés

```powershell
python manage.py test
```

Résultat attendu : `Ran 55 tests … OK`. Les tests utilisent une **base
temporaire** créée puis détruite : vos données ne sont jamais touchées. Ils
fonctionnent sous SQLite comme sous PostgreSQL.

Pour lancer un seul groupe de tests :

```powershell
python manage.py test dons.tests.RefusFormulaireTests
```

Les tests couvrent notamment :

- le parcours complet : don, reçu, email avec PDF joint ;
- tous les cas de refus du formulaire, sans rien enregistrer ;
- les épiceries inconnues ou inactives (404) ;
- la numérotation 1, 2, 3 sans trou ;
- la transaction tout-ou-rien ;
- les contraintes CHECK de la base ;
- la déduplication des donateurs ;
- les échecs d'envoi d'email ;
- l'admin (QR code réservé au staff, actions, export CSV) ;
- la commande d'initialisation.

---

## 6. Règles de travail

1. **Jamais de modification manuelle de la base.** Pas d'`UPDATE` ou de `DELETE`
   à la main, que ce soit dans DB Browser, psql ou Power BI. Tout passe par
   l'application ou l'admin, qui garantissent les règles : numérotation,
   traçabilité, reçus. La base peut être **lue** librement (Power BI, requêtes
   `SELECT`).

2. **Toute modification de `models.py` passe par une migration, qui est
   commitée :**
   ```powershell
   python manage.py makemigrations
   python manage.py migrate
   git add dons/migrations
   ```
   Ne modifiez ni ne supprimez jamais une migration déjà commitée : créez-en une nouvelle.

3. **Tests avant chaque commit :**
   ```powershell
   python manage.py test
   git add -A
   git commit -m "Message clair : ce qui change et pourquoi"
   git push
   ```
   Un test rouge signifie qu'il ne faut pas commiter : corrigez d'abord.

4. **Aucun secret dans le code.** Mots de passe, clés et identifiants SMTP vont
   dans `.env`. Si vous ajoutez une variable, documentez-la dans `.env.example`.

5. **On n'efface pas, on désactive ou on annule.** Une épicerie ou une catégorie
   se désactive, un don s'annule. L'admin empêche d'ailleurs ces suppressions.

---

## 7. Organisation du code

```
app_sp_donation/
├── manage.py                 point d'entrée des commandes Django
├── requirements.txt          dépendances Python
├── .env.example              modèle de configuration (à copier en .env)
├── .gitignore                fichiers à ne jamais commiter (.env, .venv, db.sqlite3…)
├── config/
│   ├── settings.py           configuration, lue dans .env
│   └── urls.py               adresses du site (/admin/ + pages publiques)
├── dons/                     l'application métier
│   ├── models.py             tables et contraintes de la base
│   ├── migrations/           historique des modifications du schéma (commité)
│   ├── forms.py              formulaires et validation côté serveur
│   ├── views.py              pages publiques : formulaire, merci, PDF
│   ├── urls.py               /don/<slug>/, /merci/<jeton>/, /recu/<jeton>.pdf
│   ├── services.py           logique métier : enregistrement, numérotation, email, CSV, QR
│   ├── pdf.py                génération du PDF (xhtml2pdf)
│   ├── admin.py              back-office personnalisé
│   ├── tests.py              tests automatisés
│   └── management/commands/initialiser_donnees.py
├── templates/                pages HTML, gabarit du PDF, texte de l'email
└── static/                   css/style.css (mobile d'abord), js/formulaire.js
```

**Garanties de robustesse**

| Garantie | Où |
|---|---|
| Donateur, don, objets et reçu créés dans **une seule transaction** | `services.enregistrer_don` |
| Numéros de reçu **sans trou ni doublon**, même avec des envois simultanés (verrou `select_for_update`) | `services.attribuer_numero_recu` |
| Email envoyé **après** le commit ; un échec est loggé sans perdre le don (`email_envoye` reste à False) | `services.envoyer_recu_par_email` |
| Contraintes **en base** : NOT NULL, UNIQUE, CHECK, clés étrangères PROTECT | `models.py` |
| Validation côté serveur, 1 à 20 objets, quantité de 1 à 99, champ piège anti-robots | `forms.py` |
| POST → redirect → GET (pas de double envoi en rafraîchissant la page) | `views.formulaire_don` |
| URLs publiques par **jeton UUID**, jamais par id | `views.py`, `urls.py` |
| PDF régénéré à la demande depuis la base (jamais stocké) | `pdf.py` |
| Reçus et compteurs en lecture seule, dons non supprimables | `admin.py` |

---

## 8. Base de données et Power BI

- **En développement**, la base est le fichier `db.sqlite3` à la racine du
  projet. On peut la consulter avec l'extension VS Code « SQLite Viewer » ou
  avec DB Browser for SQLite, **en lecture seule**. Pour repartir de zéro :
  arrêter le serveur, supprimer `db.sqlite3`, puis relancer `migrate`.
- **En production**, c'est un serveur PostgreSQL. Power BI s'y connecte avec
  *Obtenir des données → Base de données PostgreSQL*. Utilisez de préférence un
  **compte PostgreSQL en lecture seule** dédié à Power BI.

Tables utiles (toutes préfixées par `dons_`) :

| Table | Contenu | Liens |
|---|---|---|
| `dons_comite` | comités | |
| `dons_epicerie` | épiceries | `comite_id` → comité |
| `dons_donateur` | donateurs | |
| `dons_don` | dons (`statut` : `DECLARE`, `VALIDE` ou `ANNULE`) | `donateur_id`, `epicerie_id`, `valide_par_id` |
| `dons_lignedon` | objets donnés (quantité, état) | `don_id`, `categorie_id` |
| `dons_categorieobjet` | catégories | |
| `dons_recu` | reçus (`numero`, `email_envoye`) | `don_id` |

Pour les indicateurs, **excluez les dons annulés** (`statut <> 'ANNULE'`).
Exemple de requête :

```sql
SELECT c.nom AS comite, e.nom AS epicerie, cat.nom AS categorie,
       SUM(l.quantite) AS nb_objets
FROM dons_lignedon l
JOIN dons_don d              ON d.id = l.don_id
JOIN dons_epicerie e         ON e.id = d.epicerie_id
JOIN dons_comite c           ON c.id = e.comite_id
JOIN dons_categorieobjet cat ON cat.id = l.categorie_id
WHERE d.statut <> 'ANNULE'
GROUP BY c.nom, e.nom, cat.nom
ORDER BY nb_objets DESC;
```

---

## 9. Mise en production

L'hébergeur (en France ou dans l'UE : Scalingo, Clever Cloud…) n'est pas
encore choisi. Dans tous les cas, il faudra définir ces variables
d'environnement, à la place du fichier `.env` :

| Variable | Valeur en production |
|---|---|
| `DEBUG` | `False` (**obligatoire**) |
| `SECRET_KEY` | une clé longue et aléatoire : `python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"` |
| `ALLOWED_HOSTS` | `dons.exemple.fr` |
| `CSRF_TRUSTED_ORIGINS` | `https://dons.exemple.fr` |
| `SITE_URL` | `https://dons.exemple.fr` (adresse encodée dans les QR codes) |
| `DATABASE_URL` | fournie par l'hébergeur (PostgreSQL) |
| `EMAIL_BACKEND` | `django.core.mail.backends.smtp.EmailBackend` |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | identifiants SMTP de Brevo ou Mailjet |

Quand `DEBUG=False`, les réglages de sécurité s'activent automatiquement :
cookies sécurisés, redirection vers HTTPS, HSTS.

Pour vérifier la configuration avant une mise en ligne :

```powershell
python manage.py check --deploy
```

**Important : générez les QR codes à imprimer uniquement une fois `SITE_URL`
défini sur l'adresse de production.** Un QR code généré en local pointe vers
`127.0.0.1` et ne fonctionnera pas dans l'épicerie.

TODO (selon l'hébergeur choisi) : ajouter un serveur d'application (`gunicorn`)
et le service des fichiers statiques (`whitenoise`), plus le fichier de
lancement propre à l'hébergeur (`Procfile`…).

---

## 10. Points encore ouverts (TODO)

Ils sont repérés dans le code par des commentaires `TODO (point ouvert)`.

- [ ] **Texte RGPD définitif** : responsable du traitement, durée de
      conservation, contact pour exercer ses droits (`templates/formulaire.html`,
      `dons/forms.py`).
- [ ] **Logo et mentions officielles du SPF** : déposer le logo dans
      `static/img/logo.png` (il s'affiche automatiquement dans l'en-tête), et
      reporter les couleurs de la charte dans le bloc `:root` de `static/css/style.css`.
- [ ] **Liste définitive des catégories** (`dons/management/commands/initialiser_donnees.py`).
- [ ] **Rôles dans le back-office** : qui valide les dons ? Un bénévole ne
      voit-il que les dons de son épicerie ? (voir l'en-tête de `dons/admin.py`).
- [ ] **Hébergeur et service d'email** (voir [Mise en production](#9-mise-en-production)).
