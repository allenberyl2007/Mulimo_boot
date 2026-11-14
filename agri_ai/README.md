# Aide à la décision agricole — RDC (NASA Space Apps)

Système local et hors ligne : **un jumeau numérique, une seule base SQLite (`data/simulation.db`), cinq modèles IA, un point d'entrée CLI (`main.py`) et une interface de démonstration (`app.py`)**.
L'interface lance un petit serveur local limité à `127.0.0.1`; aucun serveur distant, service cloud ou API externe n'est nécessaire pour faire une recommandation avec les données déjà présentes.

```
python main.py --region kananga --soil ferralsol_scl --slope 8 --prev bean --demo
```
Sortie (exemple de format) : *Culture recommandée / Pourquoi ? / Récolte attendue / Confiance / Alternative*.

## Interface locale de démonstration
Avec la base et les modèles déjà préparés, double-cliquer sur `Lancer_la_demo.bat` sous Windows. Le script vérifie l'environnement, démarre le serveur et `app.py` ouvre automatiquement `http://127.0.0.1:8000`.
La fenêtre de console doit rester ouverte pendant la démonstration; appuyer sur `Ctrl+C` pour arrêter le serveur. En ligne de commande, `python app.py` reste également disponible.
Si le port 8000 est déjà utilisé par une ancienne démonstration, l'application choisit automatiquement un autre port local libre et ouvre la bonne adresse dans le navigateur; la démonstration existante n'est pas arrêtée.
Seule l'interface destinée aux utilisateurs est en anglais pour le jury; la documentation et le CLI restent en français. Elle ne charge aucune bibliothèque, carte ou police depuis Internet.
Après préparation, le serveur local lit les bases SQLite et modèles ONNX du projet sans connexion Internet, et n'envoie pas de données à un service externe. Les bases téléchargées doivent être copiées dans `data/simulation.db` avant la démonstration hors ligne.
L'interface utilisateur est en anglais et utilise les six villes comme **points de référence**, pas comme six macro-régions ni comme mesures de parcelles.
Les rendements restent des estimations de modèles entraînés sur des simulations : cette interface est un prototype de hackathon et ne constitue pas un conseil agricole validé.

## Mise à jour trimestrielle des données (Windows)
La démonstration continue à utiliser sa base locale sans Internet. Pour actualiser les données lorsqu'une connexion est disponible, double-cliquer une fois sur `Installer_maj_trimestrielle.bat`. La tâche Windows vérifie chaque jour à 09:00 si 90 jours se sont écoulés depuis la dernière mise à jour complète; elle reprend aussi une exécution manquée lorsque l'ordinateur était éteint ou hors ligne, et réessaie les échecs.
Chaque actualisation complète met à jour NASA POWER, SoilGrids, SMAP, MODIS NDVI et GPM pour les six villes, ainsi que FAOSTAT. Les données météo sont récupérées sur dix ans au premier téléchargement; les observations satellitaires sur trois ans; les actualisations suivantes reprennent une fenêtre récente pour corriger les dernières valeurs sans supprimer l'historique. GPM, MODIS et SMAP sont téléchargés avec le script Earth Engine déjà présent dans le compte Windows (`.copilot/chats/.../donnees_satellites/telecharger_donnees_satellites.py`) et son jeton Google Earth Engine mémorisé. Le projet Cloud utilisé est `braided-facet-513415-e8`; aucune variable ni aucun mot de passe Earthdata n'est demandé. Si le script est déplacé, `EARTH_ENGINE_DOWNLOADER` peut pointer vers son nouvel emplacement. Le package `earthengine-api` doit être installé dans l'environnement du projet.
Après chaque mise à jour complète, les cinq modèles sont réentraînés en mode supervisé (pas de renforcement / RL), dans des fichiers candidats. Le candidat est comparé au modèle actuel sur le jeu test fixe; il ne le remplace que si aucune cible ne régresse en erreur MAE, R² ou couverture d'intervalle et si au moins une mesure s'améliore. Sinon, le modèle actuel est conservé. Chaque décision est inscrite dans `data/update.log`.
**Limite importante :** les jeux `ds_main` et `ds_climate` restent des simulations; les nouvelles observations SMAP, MODIS et GPM servent au contrôle externe et ne sont pas des étiquettes d'entraînement. Le réentraînement protège donc les performances mesurées sur le test simulé, mais ne prouve pas une amélioration sur les rendements réels. Pour apprendre des résultats réels, il faudra intégrer des observations appariées de parcelles (culture, récolte, sol et pratiques).
Avant chaque tentative, une copie vérifiée de `data/simulation.db` est conservée dans `data/backups/` (quatre copies au maximum). Les détails et erreurs sont dans `data/update.log`. Un échec ne valide pas le cycle trimestriel et n'empêche pas la démo d'utiliser les données existantes. Pour lancer une actualisation immédiatement, double-cliquer sur `Mettre_a_jour.bat`; pour supprimer la tâche, exécuter `Unregister-ScheduledTask -TaskName MulimoAgriAiQuarterlyDatabaseUpdate`.
La tâche s'exécute sous le compte Windows courant quand la session est ouverte. Préparer d'abord le projet et sa base; les mises à jour elles-mêmes nécessitent Internet.

## Comparateur de rotations
La démonstration propose aussi une comparaison séparée entre la pratique récente déclarée, une alternance maïs-légumineuse et une rotation diversifiée maïs-légumineuse-manioc. Le nouvel endpoint local `/api/rotations` appelle `core/rotation_model.py`, qui utilise le jumeau numérique existant, la météo journalière NASA POWER hors ligne et le profil de sol local disponible (SoilGrids lorsqu'il existe, sinon archétype).

Le calcul simule trois saisons principales annuelles à partir de trois années météo complètes, avec les mêmes conditions et pratiques par défaut pour chaque stratégie. Une période météo supplémentaire est conservée pour permettre la récolte de la dernière culture, notamment le manioc. Trois répétitions avec graines de ravageurs différentes affichent une plage de sensibilité du simulateur; ce n'est ni un intervalle de confiance statistique ni une validation. Le classement 0–100 est relatif aux trois options évaluées et pondéré selon cinq priorités paysannes réglables : carbone organique, réduction de l'érosion, fixation de l'azote, utilisation de l'eau et énergie alimentaire; il ne représente pas une probabilité de réussite.

La pratique de référence dépend de la dernière culture et, si elle est connue, de l'avant-dernière culture saisies; l'hypothèse est affichée dans le résultat. Les explications détaillent la contribution des scores sol/eau/alimentation et les différences simulées par rapport à la référence. La page affiche aussi les anomalies annuelles de pluie et de température des années simulées par rapport à la moyenne annuelle du point NASA POWER sur 1991–2020. Cette comparaison porte sur un seul point et trois années; elle ne constitue ni une tendance climatique, ni une prévision, ni une observation de parcelle.

NASA POWER journalier et le profil de sol utilisé alimentent le jumeau. GPM, SMAP et MODIS disponibles dans la base peuvent apparaître comme contexte satellite, mais ne changent pas le classement. La fiche de résultat précise le rôle de chaque source ainsi que la formule de classement. Sans rendements, rotations et analyses de parcelles observés en RDC, le résultat reste une simulation exploratoire. Aucun DEM/SRTM n'est utilisé : les coordonnées des villes ne décrivent pas la pente d'une parcelle. Les prix, l'accès au marché, les variétés, la disponibilité des intrants et les calendriers propres aux exploitations ne sont pas modélisés. Le proxy calories par récolte ne mesure ni nutrition, ni revenus, ni sécurité alimentaire.

Vérifications hors ligne ciblées depuis `agri_ai/` :
```
python -m unittest discover -s tests -p test_webapp.py
python -m unittest discover -s tests -p test_rotation_model.py
python tests/test_adapters.py
```

## Structure
```
main.py                      point d'entrée : Climate AI -> Soil AI -> Crop AI -> Yield AI -> Recommendation AI (appels successifs)
app.py                       serveur HTTP local et API de démonstration (bibliothèque standard Python)
web/index.html               interface responsive en anglais pour les utilisateurs et le jury
core/                        jumeau numérique (twin, climate, crops, regions, events, features, schema) + comparateur de rotations + db + mlkit (+ policy, decide, explain)
models/<modèle>/             climate, soil, crop, yield, recommendation : UNIQUEMENT train.py, predict.py, model.onnx
adapters/                    adaptateurs des sources : power, earth_engine, smap, gpm, modis, soilgrids, faostat
data/make_datasets.py        le jumeau numérique génère les datasets (tables ds_* de simulation.db)
scripts/                     create_db.py, download_all.py, update_db.py, install_update_task.ps1, train_all.sh
audit/                       audit.py (audit automatique), audit_twin.py (jumeau), validate.py (validation scientifique)
tests/test_adapters.py       tests des adaptateurs sur charges fictives
reports/                     audit_report.md, validation_report.md, twin_checks.md
```

## Base SQLite unique
Tables : `weather`, `soil`, `soil_moisture`, `vegetation`, `yield_reference`, `crop`, `recommendation` — chacune a une colonne `source`
(`sim`, `archetype`, `nasa_power`, `gpm`, `gpm_gee`, `smap`, `smap_gee`, `modis`, `modis_gee`, `soilgrids`, `faostat`, `literature`).
Les datasets d'entraînement produits par le jumeau (`ds_main`, `ds_climate`) sont rangés dans la **même** base (interprétation de « une seule base »).
Le dossier de chaque modèle ne contient que 3 fichiers : les métadonnées (variables, diagnostics, calibration, référence hors-domaine) sont **embarquées dans `model.onnx`**.

## Reconstruire de zéro
```
python scripts/create_db.py                         # base + archétypes de sols + paramètres des cultures
python data/make_datasets.py                        # le jumeau génère les datasets (~6 min, 1 cœur)
bash scripts/train_all.sh                           # 5 modèles (train.py indépendants)
python audit/audit_twin.py && python audit/audit.py # audits -> reports/
```

## Passer aux données réelles (sans changer l'architecture)
1. `python scripts/download_all.py kananga 2015-01-01 2024-12-31` (Internet; les capteurs satellitaires utilisent le compte Earth Engine déjà authentifié et son projet Cloud) remplit la base pour Kananga. Le script satellitaire récupère les six villes, mais seule la région choisie est enregistrée par cette commande.
2. `python audit/validate.py` produit calibration et validation externe (« NON RÉALISÉE » tant que les lignes réelles manquent).
3. Ajuster `core/regions.py` (normales) selon le rapport de calibration, relancer `make_datasets.py` puis `train_all.sh`.
4. `python main.py --mode real ...` lit en priorité `nasa_power` / `soilgrids`, puis le simulé.

## Importer des fichiers téléchargés à la main (sans API)
```
python scripts/import_csv.py power pt_0.2987_23.9756 POWER_Point_Monthly_....csv   # POWER mensuel : calibration seulement (pas lu par le jumeau)
python scripts/import_csv.py power kananga POWER_Daily_....csv                     # POWER journalier : 7 paramètres exigés (PRECTOTCORR, T2M, T2M_MAX, T2M_MIN, ALLSKY_SFC_SW_DWN, RH2M, WS2M)
python scripts/import_csv.py faostat FAOSTAT_data_en_....csv                       # export FAOSTAT (kg/ha ou hg/ha), drapeaux de qualité conservés
python scripts/import_provincial_yields.py chemin/vers/crop_data.csv                # CCSAP/SIG : récoltes par province
```
Le jumeau ne lit que la météo **journalière** (sources `nasa_power`, `sim`). Les fichiers mensuels servent à la calibration (rapport de validation).
Les observations CCSAP/SIG restent séparées de FAOSTAT dans `yield_provincial_reference` : le CSV contient des rendements et quantités produits par province pour 2013–2016, mais pas des mesures de parcelles. Les provinces sont rattachées provisoirement aux six pôles Kinshasa, Mbandaka, Kisangani, Bukavu, Kananga et Lubumbashi; ce regroupement indicatif ne constitue pas un découpage administratif ou agroécologique officiel. Le rapport indique la couverture et les anomalies à vérifier. Les rendements sont très répétitifs et 19 valeurs sont hors d'un large seuil exploratoire; les agrégats des six zones ne sont donc pas présentés comme résultats tant que la source et les unités ne sont pas contrôlées. Aucune erreur prédictive n'est calculée sans sorties de modèle appariées aux observations.

## Incertitude et confiance
Chaque modèle renvoie, pour chaque cible : prédiction (`_mid`), intervalle à 80 % (`_lo`, `_hi`, calibré par prédiction conforme), incertitude (`_unc`), confiance (`_conf`),
et signale `ood_flag` / `unseen_features` (données jamais vues / hors domaine). Plus l'intervalle est large ou la situation inhabituelle, plus la confiance baisse.
Confiance finale = min des confiances des modèles × probabilité que la 1re culture batte la 2e ; plafonnée à 85 % tant qu'aucune donnée réelle n'a servi (95 % au maximum ensuite).

## Limites à connaître
- Tous les modèles sont entraînés sur des **simulations** : leurs scores mesurent l'accord avec le jumeau, pas avec la réalité.
- Le comparateur de rotations est une simulation transparente séparée, pas un modèle appris sur des rotations ou des récoltes observées en RDC.
- La règle de valeur d'une culture (`core/policy.py` : calories/ha/100 jours, pénalités sol et eau) est un choix de conception modifiable ; aucun prix de marché n'est utilisé.
- Les adaptateurs n'ont **jamais été testés contre les services réels** (réseau désactivé à la construction) ; leurs `parse()` sont testés sur des charges fictives.
- Voir `reports/audit_report.md` et `reports/validation_report.md` pour les mesures et les points d'attention.
