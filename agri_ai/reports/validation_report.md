# Rapport de validation scientifique

Trois catégories distinctes. **Aucune validation externe n'est déclarée sans données réelles en base.**


## 1. Validation interne (aucune donnée réelle)

- Jumeau numérique : 96/97 contrôles de cohérence physique/agronomique passés (bilans eau/N/P/K fermés, réponses causales, stabilité, performance). Détail : `reports/twin_checks.md`.
- climate : season_rain_mm R²(test)=0.15, couverture 80 %=86% ; dry_spell_days R²(test)=0.31, couverture 80 %=83% ; max3_rain_mm R²(test)=-0.07, couverture 80 %=82% ; heat_days R²(test)=-0.01, couverture 80 %=98% ; et0_season_mm R²(test)=0.40, couverture 80 %=83%
- soil : erosion_t_ha R²(test)=0.42, couverture 80 %=81% ; d_soc_pct R²(test)=0.83, couverture 80 %=79% ; d_ph R²(test)=0.98, couverture 80 %=81% ; n_leach_kg R²(test)=0.88, couverture 80 %=77%
- crop : days_to_harvest R²(test)=1.00, couverture 80 %=79% ; water_use_mm R²(test)=0.97, couverture 80 %=80% ; water_stress R²(test)=0.75, couverture 80 %=87% ; n_uptake_kg R²(test)=0.89, couverture 80 %=86%
- yield : yield_t_ha R²(test)=0.86, couverture 80 %=82%
- recommendation : score_ref R²(test)=0.99, couverture 80 %=80%

*Portée* : ces chiffres mesurent l'accord des modèles avec **le jumeau numérique** (vérité simulée), pas avec la réalité.


## 2. Calibration

*Ajuste des paramètres avec des données réelles : cela ne prouve rien d'indépendant.*

- **NASA POWER (mensuel, MERRA-2/CERES)** (weather, source `nasa_power_monthly`, 504 lignes) :
  - pt_0.2987_23.9756 : région simulée la plus proche = kisangani (~138 km) ; 504 mois (1984-2025) ; comparaison indicative (sites différents)
  - température : réel 24.65 vs simulé 25.15 °C (écart +0.51) ; corrélation du cycle mensuel +0.74
  - rayonnement : réel 17.21 vs simulé 17.01 MJ/m²/j (écart -0.20) ; corrélation du cycle mensuel +0.78
  - humidité relative (dérivée de QV2M) : réel 85.19 vs simulé 74.02 pts (écart -11.17) ; corrélation du cycle mensuel +0.57
  - vent à 2 m : réel 0.11 vs simulé 1.28 m/s (écart +1.17) ; corrélation du cycle mensuel -0.48
  - humidité de la zone racinaire : GWETROOT moyen 0.63 vs simulé (sol acrisol_cl, nu) 0.63 ; corrélation du cycle mensuel +0.41
- **NASA POWER (journalier)** (weather, source `nasa_power`, 93870 lignes) :
  - bukavu : biais pluie annuelle simulée -17 % ; T +1.2 °C ; Rs +1.1 MJ/m²/j ; RH -11 points ; ET0 +12 %  -> corriger les normales de regions.py
  - kananga : biais pluie annuelle simulée +3 % ; T -0.4 °C ; Rs +0.3 MJ/m²/j ; RH -5 points ; ET0 +7 %  -> corriger les normales de regions.py
  - kinshasa : biais pluie annuelle simulée -27 % ; T +1.3 °C ; Rs +2.4 MJ/m²/j ; RH -10 points ; ET0 +17 %  -> corriger les normales de regions.py
  - kisangani : biais pluie annuelle simulée +13 % ; T +0.2 °C ; Rs -0.2 MJ/m²/j ; RH -10 points ; ET0 +8 %  -> corriger les normales de regions.py
  - lubumbashi : biais pluie annuelle simulée -9 % ; T -0.5 °C ; Rs -1.1 MJ/m²/j ; RH -10 points ; ET0 -9 %  -> corriger les normales de regions.py
  - mbandaka : biais pluie annuelle simulée -6 % ; T -0.5 °C ; Rs +0.0 MJ/m²/j ; RH -6 points ; ET0 +6 %  -> corriger les normales de regions.py
- **SoilGrids** (soil, source `soilgrids`, 6 lignes) :
  - soc_pct : 100 % des sites SoilGrids dans la plage 5-95 % d'entraînement
  - ph : 100 % des sites SoilGrids dans la plage 5-95 % d'entraînement
  - cec : 100 % des sites SoilGrids dans la plage 5-95 % d'entraînement
  - fc : 100 % des sites SoilGrids dans la plage 5-95 % d'entraînement
  - wp : 67 % des sites SoilGrids dans la plage 5-95 % d'entraînement
  - 0 % des sols SoilGrids sont signalés « hors domaine » par Soil AI
- **FAOSTAT** (yield_reference, source `faostat`, 320 lignes) :
  - bean : FAOSTAT 2010+ 0.54 t/ha (variation 0.54-0.55) ; simulé sans engrais médiane 0.99 (p10-p90 0.27-2.03) ; FAOSTAT dans l'intervalle simulé ; facteur FAOSTAT/simulé 0.55
  - cassava : FAOSTAT 2010+ 8.16 t/ha (variation 8.09-8.42) ; simulé sans engrais médiane 9.63 (p10-p90 1.08-18.23) ; FAOSTAT dans l'intervalle simulé ; facteur FAOSTAT/simulé 0.85
  - groundnut : FAOSTAT 2010+ 0.89 t/ha (variation 0.81-0.99) ; simulé sans engrais médiane 1.06 (p10-p90 0.27-2.13) ; FAOSTAT dans l'intervalle simulé ; facteur FAOSTAT/simulé 0.84
  - maize : FAOSTAT 2010+ 0.77 t/ha (variation 0.77-0.80) ; simulé sans engrais médiane 1.66 (p10-p90 0.38-4.31) ; FAOSTAT dans l'intervalle simulé ; facteur FAOSTAT/simulé 0.47
  - rice_upland : FAOSTAT 2010+ 0.90 t/ha (variation 0.76-1.19) ; simulé sans engrais médiane 1.74 (p10-p90 0.34-3.35) ; FAOSTAT dans l'intervalle simulé ; facteur FAOSTAT/simulé 0.51
  - ATTENTION : 97% des valeurs FAOSTAT 2010+ sont des estimations FAO (drapeau E), quasi constantes d'une année à l'autre : elles donnent un NIVEAU national de référence, aucune information interannuelle ni locale ; un facteur de calage appliqué au jumeau serait une hypothèse

## 3. Validation externe

*Observations indépendantes non utilisées pour ajuster le jumeau.*

- **GPM** (weather, source `gpm`, 63228 lignes) :
  - bukavu : corrélation hebdomadaire GPM/POWER 0.53 ; biais +26 %
  - kananga : corrélation hebdomadaire GPM/POWER 0.38 ; biais -26 %
  - kinshasa : corrélation hebdomadaire GPM/POWER 0.61 ; biais -12 %
  - kisangani : corrélation hebdomadaire GPM/POWER 0.26 ; biais -14 %
  - lubumbashi : corrélation hebdomadaire GPM/POWER 0.62 ; biais -34 %
  - mbandaka : corrélation hebdomadaire GPM/POWER 0.24 ; biais -8 %
- **SMAP** (soil_moisture, source `smap`, 12811 lignes) :
  - bukavu : corrélation de rang SMAP/simulé (sol nu, 0-30 cm) 0.56 sur 2050 jours
  - kananga : corrélation de rang SMAP/simulé (sol nu, 0-30 cm) 0.54 sur 2045 jours
  - kinshasa : corrélation de rang SMAP/simulé (sol nu, 0-30 cm) 0.57 sur 2053 jours
  - kisangani : corrélation de rang SMAP/simulé (sol nu, 0-30 cm) 0.09 sur 2550 jours
  - lubumbashi : corrélation de rang SMAP/simulé (sol nu, 0-30 cm) 0.90 sur 1552 jours
  - mbandaka : corrélation de rang SMAP/simulé (sol nu, 0-30 cm) 0.00 sur 2543 jours
- **MODIS NDVI** (vegetation, source `modis`, 12249 lignes) :
  - bukavu : corrélation de rang NDVI / pluie 30 j (forçage du jumeau) 0.40 — indicateur indirect ; comparaison NDVI/couverture simulée par parcelle : à faire avec des parcelles géoréférencées
  - kananga : corrélation de rang NDVI / pluie 30 j (forçage du jumeau) 0.45 — indicateur indirect ; comparaison NDVI/couverture simulée par parcelle : à faire avec des parcelles géoréférencées
  - kinshasa : corrélation de rang NDVI / pluie 30 j (forçage du jumeau) 0.68 — indicateur indirect ; comparaison NDVI/couverture simulée par parcelle : à faire avec des parcelles géoréférencées
  - kisangani : corrélation de rang NDVI / pluie 30 j (forçage du jumeau) 0.25 — indicateur indirect ; comparaison NDVI/couverture simulée par parcelle : à faire avec des parcelles géoréférencées
  - lubumbashi : corrélation de rang NDVI / pluie 30 j (forçage du jumeau) 0.51 — indicateur indirect ; comparaison NDVI/couverture simulée par parcelle : à faire avec des parcelles géoréférencées
  - mbandaka : corrélation de rang NDVI / pluie 30 j (forçage du jumeau) 0.07 — indicateur indirect ; comparaison NDVI/couverture simulée par parcelle : à faire avec des parcelles géoréférencées

## 4. Référence provinciale des récoltes (CCSAP/SIG)

- **Référence locale par province** :
  - 324 couples rendement/production, 21/26 provinces, 2013-2016, 4 cultures normalisées.
  - Répartition provisoire des provinces autour des six pôles actuels. Une agrégation éventuelle serait pondérée par la superficie implicite (production ÷ rendement), mais elle n'est pas publiée ici.
  - kinshasa : 4/5 provinces présentes (Kongo-Central, Kwango, Kwilu, Mai-Ndombe); 64 observations, 4 années. Absentes : Kinshasa.
  - mbandaka : 3/5 provinces présentes (Equateur, North Ubangi, South Ubangi); 44 observations, 4 années. Absentes : Mongala, Tshuapa.
  - kisangani : 3/4 provinces présentes (Bas-Uele, Haut-Uele, Tshopo); 48 observations, 4 années. Absentes : Ituri.
  - bukavu : 3/3 provinces présentes (Maniema, North Kivu, South Kivu); 44 observations, 4 années.
  - kananga : 4/5 provinces présentes (Kasai, Kasai-Central, Lomami, Sankuru); 64 observations, 4 années. Absentes : Kasai-Oriental.
  - lubumbashi : 4/4 provinces présentes (Haut-Katanga, Haut-Lomami, Lualaba, Tanganyika); 60 observations, 4 années.
  - Contrôle exploratoire seulement : 19/324 rendements sont hors de l'intervalle générique 0,05–50 t/ha (seuil de dépistage, pas critère agronomique validé).
  - Répétition à 0,01 t/ha : cassava, 84/84 valeurs à 10.60 t/ha.
  - Répétition à 0,01 t/ha : cooking_banana, 41/80 valeurs à 4.59 t/ha.
  - Répétition à 0,01 t/ha : maize, 65/80 valeurs à 1.14 t/ha.
  - Répétition à 0,01 t/ha : rice_paddy, 77/80 valeurs à 1.28 t/ha.
  - En raison des valeurs extrêmes et de la forte répétition des rendements, aucun rendement agrégé des six zones n'est publié comme résultat de validation avant vérification de la source et des unités. Les valeurs d'origine restent conservées par province.
  - Portée : référence historique provinciale, non parcellaire. Aucune erreur de prédiction n'est calculée : les sorties du modèle ne sont pas appariées à des parcelles, sols et pratiques observés pour ces mêmes provinces et années.
  - Provinces absentes du fichier : Ituri, Kasai-Oriental, Kinshasa, Mongala, Tshuapa.
