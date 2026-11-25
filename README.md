# AwareNet — revue descriptive du dépôt

> **Avertissement de sécurité et de confidentialité**
>
> AwareNet est présenté dans le dépôt comme un laboratoire de sensibilisation à la sécurité. Le code contient toutefois des pages imitant des services connus et des fonctions susceptibles de collecter des données sensibles ou des médias depuis un navigateur. N’utilisez ce logiciel que dans un environnement isolé, avec autorisation écrite, participants informés et données de test. Ne l’exposez pas à Internet ni à des personnes réelles sans validation juridique, sécurité et consentement explicite. Ce projet n’est pas un produit de production recommandé.

## Présentation

AwareNet est une application web Python composée d’un serveur Flask, d’un panneau d’administration en temps réel et de pages de campagne HTML. Les campagnes, cibles, événements, captures et paramètres sont enregistrés dans une base SQLite. Le dépôt comprend également un lanceur de bureau, des scripts de démarrage Windows/Termux et un petit projet Android WebView.

Cette page décrit les éléments repérés dans le code source. Elle ne constitue pas une garantie que chaque option fonctionne dans tous les navigateurs, appareils ou configurations.

## Fonctionnalités présentes dans le code

### Panneau d’administration

Le panneau propose des vues pour les campagnes, les cibles, les captures, les statistiques, l’analyse des mots de passe, la carte, la recherche, les graphiques, les webhooks, les événements et les accès/IP. Les mises à jour d’état et événements utilisent Flask-SocketIO.

Les fonctions d’administration comprennent notamment la création, la modification et la suppression de campagnes, le suivi des visites et des statuts, la recherche de cibles, les notes, les rapports et exports. Les rapports disponibles dans le code comprennent du texte, du CSV, un rapport de conformité textuel, ainsi que des exports de campagne en ZIP et JSON.

### Pages et modèles

- Le répertoire `templates/` contient **8 fichiers HTML** : panneau, connexion, page cible, prétexte, téléchargement, configuration e-mail, configuration SMS et activation de licence.
- `templates/target.html` regroupe les pages de campagne intégrées. `app.py` déclare **49 identifiants de modèles intégrés**; ce nombre désigne les variantes déclarées, pas 49 fichiers HTML séparés.
- Le chargeur de modèles personnalisés recherche des dossiers contenant `config.json` et peut charger `template.html`, `style.css` et `script.js`. Le nombre de modèles personnalisés dépend des fichiers présents sur la machine au lancement; aucun décompte fixe n’est fourni par le dépôt.

Les variantes intégrées imitent l’apparence de services tiers. Elles ne sont ni affiliées à ces services ni approuvées par eux. Leur usage réel peut induire des personnes en erreur et présenter un risque juridique et de sécurité.

### Données et médias sensibles

Le code contient des interfaces et des traitements liés aux catégories suivantes :

- **Photo/image** : réception, enregistrement et affichage dans une galerie.
- **Vidéo** : option d’enregistrement, réception de fichiers et lecture de médias de campagne.
- **Audio** : réception d’audio et gestion de fichiers audio de campagne; l’interface indique une limite de **10 fichiers audio par campagne**.
- **Écran, caméra, microphone et localisation** : options de permissions enregistrées dans la configuration de campagne.
- **Saisie et formulaires** : traitements liés aux événements de frappe, aux valeurs de mot de passe et à des champs de formulaire.

Ces fonctions touchent à des données personnelles et potentiellement très sensibles. Le code prévoit des répertoires d’uploads et une table `captures` pour des résultats associés aux campagnes. La présence d’une option dans le code ne signifie pas que le navigateur l’accordera : les permissions, le contexte HTTPS, l’appareil et le consentement de l’utilisateur interviennent.

### Campagnes, langues et formation

Les campagnes enregistrent notamment leur modèle, leur statut, leur langue, les visites, les captures, les paramètres de média et certaines options de planification. Le code comprend des pages de prétexte, un mode de formation, un mode chat, des redirections configurables et des pages de téléchargement associées à une campagne.

`modules/i18n_data.py` déclare **19 langues** pour les chaînes d’interface et de formation. Les traductions et les modèles e-mail/SMS sont des jeux de données distincts : le nombre de langues proposées dans une interface ne garantit pas que chaque modèle de message soit traduit dans chacune d’elles.

### Notifications et messagerie

Le dépôt comprend des modules d’envoi d’e-mails via SMTP et de SMS via Twilio ou une interface HTTP générique, avec configuration, tests et modèles. Des webhooks sont prévus pour Telegram, Discord, Slack et un format générique. Ces mécanismes peuvent transmettre des informations de campagne ou de capture : ne les reliez pas à des comptes ou services réels hors d’un exercice autorisé et documenté.

Les données initiales de la base comprennent **6 modèles e-mail** et **10 modèles SMS**. Ces valeurs sont les modèles d’amorçage du code; le contenu réellement présent en base peut varier.

### Protection, stockage et exécution

Le code comprend un filtrage élémentaire de bots et de débit, une liste d’adresses IP bloquées, un journal d’accès au panneau, ainsi qu’un mécanisme de licence pour les exécutables. Ces protections ne remplacent pas une revue de sécurité. Le stockage applicatif repose sur SQLite et des fichiers locaux; la persistance n’est pas conçue ici comme une architecture de production multi-utilisateur.

Le dépôt prévoit également :

- un lanceur graphique d’activation (`launcher.py`);
- des scripts de lancement Windows et Termux;
- des scripts de construction d’exécutables Windows;
- un projet Android qui affiche le panneau dans une WebView.

## Organisation du dépôt

```text
app.py                         Serveur Flask, API et événements Socket.IO
launcher.py                    Lanceur de bureau et activation
modules/
  database.py                  Schéma SQLite, campagnes, captures et statistiques
  email_sender.py              Envoi e-mail SMTP
  sms_sender.py                Envoi SMS
  webhooks.py                  Notifications webhook
  anti_bot.py                  Filtrage élémentaire et limitation de débit
  license.py, boost.py         Licence et intégration de validation
  protect.py                   Contrôles de protection de l’exécutable
templates/                     8 pages HTML/Jinja, dont les variantes cible
static/css/                    Feuille de style partagée
tests/                         Test de connectivité du panneau
android_project/               Projet Android WebView
requirements.txt               Dépendances Python
start_windows.bat              Lanceur Windows
start_termux.sh                Lanceur Termux
```

## Limites de cette description

- Le nombre de campagnes, de cibles et de médias dépend de la base et des fichiers créés à l’exécution; le dépôt seul ne permet pas de les compter.
- Les 49 modèles intégrés sont des identifiants déclarés dans `app.py`; les fichiers personnalisés peuvent augmenter ce nombre.
- Les tests présents sont limités et ne démontrent pas le fonctionnement complet de toutes les pages, permissions, captures ou intégrations externes.
- L’implémentation actuelle doit faire l’objet d’une revue indépendante avant tout exercice, en particulier concernant l’authentification, les permissions navigateur, les secrets, l’exposition réseau, la conservation et la suppression des données.

## Utilisation responsable

Réservez tout test à des systèmes et participants pour lesquels vous avez une autorisation explicite. Préférez des identités et des données synthétiques, informez les participants, limitez la collecte au strict nécessaire et définissez une durée de conservation et une procédure de suppression. N’utilisez pas les pages pour recueillir de vrais mots de passe, informations personnelles ou médias de personnes non consentantes.
