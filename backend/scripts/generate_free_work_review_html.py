#!/usr/bin/env python3
import json
import argparse
import sys
from pathlib import Path

from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = REPOSITORY_ROOT
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = BACKEND_ROOT / "data"
RAW_DATA_ROOT = DATA_ROOT / "raw"
PROCESSED_DATA_ROOT = DATA_ROOT / "processed"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>ObservIA Emploi - Revue Humaine Free-Work vs France Travail</title>
    <style>
        :root {
            --primary: #2563eb;
            --primary-hover: #1d4ed8;
            --bg-main: #f8fafc;
            --bg-card: #ffffff;
            --text-main: #1e293b;
            --text-muted: #64748b;
            --border: #e2e8f0;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
            --info: #3b82f6;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: var(--bg-main);
            color: var(--text-main);
            margin: 0;
            padding: 0;
            display: flex;
            flex-direction: column;
            height: 100vh;
        }

        header {
            background-color: var(--bg-card);
            border-bottom: 1px solid var(--border);
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        h1 {
            font-size: 1.25rem;
            margin: 0;
            color: var(--primary);
        }

        .container {
            display: flex;
            flex: 1;
            overflow: hidden;
        }

        .sidebar {
            width: 320px;
            background-color: var(--bg-card);
            border-right: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            overflow-y: auto;
        }

        .filters {
            padding: 1rem;
            border-bottom: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }

        .filter-group {
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
        }

        .filter-group label {
            font-size: 0.75rem;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
        }

        .filter-group select, .filter-group input {
            padding: 0.5rem;
            border: 1px solid var(--border);
            border-radius: 4px;
            font-size: 0.875rem;
            outline: none;
        }

        .filter-group select:focus, .filter-group input:focus {
            border-color: var(--primary);
        }

        .queue-list {
            flex: 1;
            overflow-y: auto;
        }

        .queue-item {
            padding: 1rem;
            border-bottom: 1px solid var(--border);
            cursor: pointer;
            transition: background-color 0.2s;
        }

        .queue-item:hover {
            background-color: #f1f5f9;
        }

        .queue-item.active {
            background-color: #e2e8f0;
            border-left: 4px solid var(--primary);
        }

        .item-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.25rem;
        }

        .badge {
            font-size: 0.7rem;
            font-weight: 700;
            padding: 0.2rem 0.5rem;
            border-radius: 9999px;
            text-transform: uppercase;
        }

        .badge-high { background-color: #fee2e2; color: var(--danger); }
        .badge-medium { background-color: #fef3c7; color: var(--warning); }
        .badge-low { background-color: #e0f2fe; color: var(--info); }

        .score-badge {
            font-size: 0.85rem;
            font-weight: 600;
            color: var(--primary);
        }

        .item-title {
            font-size: 0.9rem;
            font-weight: 600;
            margin: 0 0 0.25rem 0;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .item-meta {
            font-size: 0.75rem;
            color: var(--text-muted);
            display: flex;
            justify-content: space-between;
        }

        .main-content {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            background-color: var(--bg-main);
        }

        .details-wrapper {
            flex: 1;
            padding: 1.5rem;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
        }

        .comparison-cards {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
        }

        .card {
            background-color: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1.25rem;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
        }

        .card-title {
            font-size: 1rem;
            font-weight: 700;
            border-bottom: 2px solid var(--border);
            padding-bottom: 0.5rem;
            margin-top: 0;
            margin-bottom: 1rem;
            color: var(--primary);
        }

        .field-group {
            margin-bottom: 0.75rem;
        }

        .field-label {
            font-size: 0.75rem;
            font-weight: 600;
            color: var(--text-muted);
        }

        .field-value {
            font-size: 0.9rem;
            margin-top: 0.1rem;
        }

        .field-value-skills {
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem;
            margin-top: 0.25rem;
        }

        .skill-tag {
            background-color: #f1f5f9;
            border: 1px solid var(--border);
            border-radius: 4px;
            padding: 0.15rem 0.4rem;
            font-size: 0.75rem;
        }

        .desc-box {
            background-color: #f8fafc;
            border: 1px solid var(--border);
            border-radius: 4px;
            padding: 0.75rem;
            font-size: 0.85rem;
            max-height: 200px;
            overflow-y: auto;
            white-space: pre-wrap;
        }

        .synthesis-card {
            background-color: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1.25rem;
        }

        .synthesis-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
        }

        .comparison-status-badge {
            font-size: 0.75rem;
            font-weight: 700;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            display: inline-block;
            margin-top: 0.25rem;
        }
        
        .comp-match { background-color: #d1fae5; color: #065f46; }
        .comp-partial { background-color: #fef3c7; color: #92400e; }
        .comp-diff { background-color: #fee2e2; color: #991b1b; }
        .comp-unknown { background-color: #f3f4f6; color: #374151; }

        .no-selection {
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--text-muted);
            font-size: 1.1rem;
        }

        .human-form {
            background-color: var(--bg-card);
            border-top: 1px solid var(--border);
            padding: 1rem 2rem;
            display: flex;
            gap: 1rem;
            align-items: center;
        }

        .form-select, .form-input {
            padding: 0.5rem;
            border: 1px solid var(--border);
            border-radius: 4px;
            font-size: 0.875rem;
        }

        .form-input {
            flex: 1;
        }

        .btn {
            background-color: var(--primary);
            color: white;
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 4px;
            font-weight: 600;
            cursor: pointer;
        }

        .btn:hover {
            background-color: var(--primary-hover);
        }
    </style>
</head>
<body>
    <header>
        <div>
            <h1>ObservIA Emploi - Revue Humaine Free-Work vs France Travail</h1>
            <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.25rem;" id="stats-summary">
                Chargement des données...
            </div>
        </div>
        <div>
            <span style="font-size: 0.85rem; font-weight: 600; color: var(--text-muted);">Mode Triage Hors-ligne</span>
        </div>
    </header>

    <div class="container">
        <div class="sidebar">
            <div class="filters">
                <div class="filter-group">
                    <label for="search-input">Rechercher</label>
                    <input type="text" id="search-input" placeholder="Titre, entreprise, id...">
                </div>
                <div class="filter-group">
                    <label for="filter-priority">Priorité</label>
                    <select id="filter-priority">
                        <option value="ALL">Toutes les priorités</option>
                        <option value="HAUTE">Haute</option>
                        <option value="MOYENNE">Moyenne</option>
                        <option value="FAIBLE">Faible</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label for="filter-score">Score minimal</label>
                    <select id="filter-score">
                        <option value="0">Tous les scores</option>
                        <option value="50">>= 50/100</option>
                        <option value="60">>= 60/100</option>
                        <option value="70">>= 70/100</option>
                    </select>
                </div>
            </div>
            <div class="queue-list" id="list-container">
                <!-- Chargé dynamiquement -->
            </div>
        </div>

        <div class="main-content" id="detail-view">
            <div class="no-selection" id="no-selection-msg">
                Sélectionnez une offre dans la liste pour commencer la revue humaine.
            </div>
            
            <div class="details-wrapper" id="details-panel" style="display: none;">
                <!-- Synthèse de comparaison -->
                <div class="synthesis-card">
                    <h2 class="card-title" style="border-bottom: none; margin-bottom: 0.5rem;">Synthèse de l'Incertitude (Triage V2)</h2>
                    <div style="font-size: 0.9rem; margin-bottom: 1rem; font-weight: 600;" id="synth-overall">
                        -
                    </div>
                    <div class="synthesis-grid">
                        <div>
                            <div class="field-group">
                                <span class="field-label">Motifs d'incertitude</span>
                                <div class="field-value" id="synth-reasons" style="font-family: monospace; color: var(--danger); font-weight: 600;">-</div>
                            </div>
                            <div class="field-group">
                                <span class="field-label">Éléments concordants</span>
                                <div class="field-value" id="synth-concordants" style="color: var(--success); font-weight: 500;">-</div>
                            </div>
                        </div>
                        <div>
                            <div class="field-group">
                                <span class="field-label">Points de vigilance</span>
                                <div class="field-value" id="synth-vigilance" style="color: var(--warning); font-weight: 500;">-</div>
                            </div>
                            <div class="field-group">
                                <span class="field-label">Action recommandée</span>
                                <div class="field-value" id="synth-action" style="font-weight: 600;">-</div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Comparaison côte à côte -->
                <div class="comparison-cards">
                    <!-- Carte Free-Work -->
                    <div class="card">
                        <h2 class="card-title">Offre Free-Work (Source 3)</h2>
                        <div class="field-group">
                            <span class="field-label">ID Source</span>
                            <div class="field-value" id="fw-id">-</div>
                        </div>
                        <div class="field-group">
                            <span class="field-label">Intitulé du poste</span>
                            <div class="field-value" id="fw-title" style="font-weight: 700;">-</div>
                        </div>
                        <div class="field-group">
                            <span class="field-label">Entreprise</span>
                            <div class="field-value" id="fw-company">-</div>
                        </div>
                        <div class="field-group">
                            <span class="field-label">Localisation</span>
                            <div class="field-value" id="fw-location">-</div>
                        </div>
                        <div class="field-group">
                            <span class="field-label">Compétences clés</span>
                            <div class="field-value-skills" id="fw-skills">-</div>
                        </div>
                        <div class="field-group">
                            <span class="field-label">Soft Skills</span>
                            <div class="field-value-skills" id="fw-soft-skills">-</div>
                        </div>
                        <div class="field-group">
                            <span class="field-label">Extrait de la description</span>
                            <div class="desc-box" id="fw-desc">-</div>
                        </div>
                        <div class="field-group" id="fw-url-container">
                            <span class="field-label">Lien original</span>
                            <div class="field-value"><a id="fw-url" href="#" target="_blank">Ouvrir l'offre</a></div>
                        </div>
                    </div>

                    <!-- Carte France Travail -->
                    <div class="card">
                        <h2 class="card-title">Meilleur Candidat France Travail</h2>
                        <div class="field-group">
                            <span class="field-label">ID France Travail</span>
                            <div class="field-value" id="ft-id">-</div>
                        </div>
                        <div class="field-group">
                            <span class="field-label">Intitulé du poste</span>
                            <div class="field-value" id="ft-title" style="font-weight: 700;">-</div>
                        </div>
                        <div class="field-group">
                            <span class="field-label">Entreprise</span>
                            <div class="field-value" id="ft-company">-</div>
                        </div>
                        <div class="field-group">
                            <span class="field-label">Localisation</span>
                            <div class="field-value" id="ft-location">-</div>
                        </div>
                        <div class="field-group">
                            <span class="field-label">Code ROME</span>
                            <div class="field-value" id="ft-rome">-</div>
                        </div>
                        
                        <!-- Indicateurs de proximité détaillés -->
                        <h3 style="font-size: 0.9rem; margin-top: 1.5rem; margin-bottom: 0.75rem; border-top: 1px solid var(--border); padding-top: 0.75rem; color: var(--text-muted);">Indicateurs de Proximité</h3>
                        
                        <div class="field-group">
                            <span class="field-label">Score Global</span>
                            <div class="field-value" id="comp-score" style="font-weight: 700;">-</div>
                        </div>
                        <div class="field-group">
                            <span class="field-label">Similarité Titre</span>
                            <div id="comp-title-badge" class="comparison-status-badge">-</div>
                        </div>
                        <div class="field-group">
                            <span class="field-label">Comparaison Entreprise</span>
                            <div id="comp-company-badge" class="comparison-status-badge">-</div>
                        </div>
                        <div class="field-group">
                            <span class="field-label">Comparaison Géographique</span>
                            <div id="comp-geo-badge" class="comparison-status-badge">-</div>
                        </div>
                        <div class="field-group">
                            <span class="field-label">Proximité Description</span>
                            <div id="comp-desc-badge" class="comparison-status-badge">-</div>
                        </div>
                        <div class="field-group">
                            <span class="field-label">Validation ROME</span>
                            <div id="comp-rome-badge" class="comparison-status-badge">-</div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Formulaire de saisie humaine factice (interactif localement) -->
            <div class="human-form" id="input-form" style="display: none;">
                <div class="filter-group" style="width: 250px;">
                    <label>Décision Humaine</label>
                    <select id="review-decision" class="form-select">
                        <option value="">Sélectionner...</option>
                        <option value="MEME_OFFRE">MEME_OFFRE (Doublon avéré)</option>
                        <option value="OFFRES_DIFFERENTES">OFFRES_DIFFERENTES (Nouvelle offre)</option>
                        <option value="IMPOSSIBLE_A_DETERMINER">IMPOSSIBLE_A_DETERMINER</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label>ID France Travail sélectionné</label>
                    <input type="text" id="review-ft-id" class="form-input" placeholder="Optionnel (si MEME_OFFRE)">
                </div>
                <div class="filter-group" style="flex: 2;">
                    <label>Commentaire de revue</label>
                    <input type="text" id="review-comment" class="form-input" placeholder="Pourquoi cette décision ?">
                </div>
                <button type="button" class="btn" onclick="saveLocalReview()">Valider la décision</button>
            </div>
        </div>
    </div>

    <script>
        // Injection dynamique des données
        const DATA = %DATA_PLACEHOLDER%;
        
        let filteredData = [];
        let currentItem = null;
        const localReviews = {};

        // Badges CSS Helper
        function getBadgeClass(priority) {
            if (priority === 'HAUTE') return 'badge-high';
            if (priority === 'MOYENNE') return 'badge-medium';
            return 'badge-low';
        }

        function getCompClass(text) {
            const t = text.toLowerCase();
            if (t.includes('identique') || t.includes('compatible') || t.includes('même') || t.includes('concordant')) {
                return 'comp-match';
            }
            if (t.includes('partiel') || t.includes('intermédiaire')) {
                return 'comp-partial';
            }
            if (t.includes('différent') || t.includes('écart')) {
                return 'comp-diff';
            }
            return 'comp-unknown';
        }

        // Rendu de la liste
        function renderList() {
            const search = document.getElementById('search-input').value.toLowerCase();
            const priority = document.getElementById('filter-priority').value;
            const minScore = parseFloat(document.getElementById('filter-score').value);

            filteredData = DATA.filter(d => {
                const fw = d.free_work_offer;
                const matchesSearch = 
                    fw.title.toLowerCase().includes(search) ||
                    (fw.company && fw.company.toLowerCase().includes(search)) ||
                    fw.source_id.includes(search);
                
                const matchesPriority = priority === 'ALL' || d.human_review_priority === priority;
                
                const score = d.comparison.score_global || 0;
                const matchesScore = score >= minScore;

                return matchesSearch && matchesPriority && matchesScore;
            });

            // Tri par priorité et score décroissant
            const prioVals = { 'HAUTE': 0, 'MOYENNE': 1, 'FAIBLE': 2, 'HORS_REVUE': 3 };
            filteredData.sort((a, b) => {
                const pA = prioVals[a.human_review_priority] ?? 3;
                const pB = prioVals[b.human_review_priority] ?? 3;
                if (pA !== pB) return pA - pB;
                return (b.comparison.score_global ?? 0) - (a.comparison.score_global ?? 0);
            });

            const container = document.getElementById('list-container');
            container.innerHTML = '';

            filteredData.forEach(item => {
                const div = document.createElement('div');
                div.className = `queue-item ${currentItem && currentItem.free_work_offer.source_id === item.free_work_offer.source_id ? 'active' : ''}`;
                
                // Indicateur de décision locale validée
                const isReviewed = localReviews[item.free_work_offer.source_id];
                const reviewedIndicator = isReviewed ? ' ✓' : '';

                div.innerHTML = `
                    <div class="item-header">
                        <span class="badge ${getBadgeClass(item.human_review_priority)}">${item.human_review_priority}</span>
                        <span class="score-badge">${item.comparison.score_global ? Math.round(item.comparison.score_global) + '/100' : 'N/A'}</span>
                    </div>
                    <h3 class="item-title">${item.free_work_offer.title}</h3>
                    <div class="item-meta">
                        <span>${item.free_work_offer.company || 'Sans entreprise'}</span>
                        <span style="font-weight: bold; color: var(--success);">${reviewedIndicator}</span>
                    </div>
                `;
                div.onclick = () => selectItem(item);
                container.appendChild(div);
            });

            // Mise à jour du bandeau statistiques
            const reviewedCount = Object.keys(localReviews).length;
            document.getElementById('stats-summary').textContent = 
                `${filteredData.length} cas filtrés sur ${DATA.length} cas incertains au total. Décisions arbitrées : ${reviewedCount}/${filteredData.length}`;
        }

        // Sélection d'une fiche
        function selectItem(item) {
            currentItem = item;
            
            // Mettre en évidence dans la liste
            document.querySelectorAll('.queue-item').forEach(el => el.classList.remove('active'));
            renderList();

            document.getElementById('no-selection-msg').style.display = 'none';
            document.getElementById('details-panel').style.display = 'flex';
            document.getElementById('input-form').style.display = 'flex';

            const fw = item.free_work_offer;
            const ft = item.france_travail_candidate || {};
            const comp = item.comparison;
            const synth = item.human_review_synthesis;

            // Remplir Free-Work
            document.getElementById('fw-id').textContent = fw.source_id;
            document.getElementById('fw-title').textContent = fw.title;
            document.getElementById('fw-company').textContent = fw.company || 'Non renseigné';
            document.getElementById('fw-location').textContent = fw.location ? `${fw.location.locality || ''} (${fw.location.postal_code || ''})` : 'Inconnu';
            
            const skillsDiv = document.getElementById('fw-skills');
            skillsDiv.innerHTML = '';
            if (fw.skills && fw.skills.length > 0) {
                fw.skills.forEach(s => {
                    const span = document.createElement('span');
                    span.className = 'skill-tag';
                    span.textContent = s.name;
                    skillsDiv.appendChild(span);
                });
            } else {
                skillsDiv.textContent = 'Aucune compétence déclarée';
            }

            const softSkillsDiv = document.getElementById('fw-soft-skills');
            softSkillsDiv.innerHTML = '';
            if (fw.soft_skills && fw.soft_skills.length > 0) {
                fw.soft_skills.forEach(s => {
                    const span = document.createElement('span');
                    span.className = 'skill-tag';
                    span.style.backgroundColor = '#fef3c7';
                    span.textContent = s.name;
                    softSkillsDiv.appendChild(span);
                });
            } else {
                softSkillsDiv.textContent = 'Aucun soft skill déclaré';
            }

            document.getElementById('fw-desc').textContent = fw.description_excerpt;
            
            if (fw.url) {
                document.getElementById('fw-url-container').style.display = 'block';
                document.getElementById('fw-url').href = fw.url;
            } else {
                document.getElementById('fw-url-container').style.display = 'none';
            }

            // Remplir France Travail
            document.getElementById('ft-id').textContent = ft.france_travail_id || 'Aucun';
            document.getElementById('ft-title').textContent = ft.title || '-';
            document.getElementById('ft-company').textContent = ft.company_name || 'Non renseigné';
            document.getElementById('ft-location').textContent = ft.postal_code || '-';
            document.getElementById('ft-rome').textContent = ft.rome_code || '-';

            // Remplir comparaison
            document.getElementById('comp-score').textContent = comp.score_global ? `${Math.round(comp.score_global)}/100` : 'N/A';
            
            const badges = [
                { id: 'comp-title-badge', val: comp.title_human },
                { id: 'comp-company-badge', val: comp.company_human },
                { id: 'comp-geo-badge', val: comp.location_human },
                { id: 'comp-desc-badge', val: comp.description_human },
                { id: 'comp-rome-badge', val: comp.rome_human }
            ];

            badges.forEach(b => {
                const el = document.getElementById(b.id);
                el.textContent = b.val;
                el.className = `comparison-status-badge ${getCompClass(b.val)}`;
            });

            // Remplir synthèse
            document.getElementById('synth-overall').textContent = synth.resume_decision;
            document.getElementById('synth-reasons').textContent = item.deterministic_reasons.join(' ; ');
            document.getElementById('synth-concordants').textContent = synth.elements_concordants;
            document.getElementById('synth-vigilance').textContent = synth.points_de_vigilance;
            document.getElementById('synth-action').textContent = synth.action_recommandee;

            // Charger les éventuels arbitrages locaux enregistrés dans cette session
            const local = localReviews[fw.source_id] || {};
            document.getElementById('review-decision').value = local.decision || '';
            document.getElementById('review-ft-id').value = local.selected_ft_id || (local.decision === 'MEME_OFFRE' ? (ft.france_travail_id || '') : '');
            document.getElementById('review-comment').value = local.comment || '';
        }

        // Sauvegarde d'un arbitrage local (dans la mémoire de la page)
        function saveLocalReview() {
            if (!currentItem) return;
            const sourceId = currentItem.free_work_offer.source_id;
            const decision = document.getElementById('review-decision').value;
            const selectedFtId = document.getElementById('review-ft-id').value;
            const comment = document.getElementById('review-comment').value;

            if (!decision) {
                alert('Veuillez sélectionner une décision humaine.');
                return;
            }

            localReviews[sourceId] = {
                decision,
                selected_ft_id: selectedFtId,
                comment,
                timestamp: new Date().toISOString()
            };

            alert(`Décision "${decision}" enregistrée localement pour l'offre ${sourceId}.`);
            renderList();
        }

        // Initialisation de la recherche et filtres
        document.getElementById('search-input').oninput = renderList;
        document.getElementById('filter-priority').onchange = renderList;
        document.getElementById('filter-score').onchange = renderList;

        // Démarrage
        renderList();
    </script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Générateur de la vue HTML de revue humaine.")
    parser.add_argument("--run-id", default="run_triage_v2_candidate_20260624", help="Identifiant du run")
    args = parser.parse_args()

    run_dir = PROCESSED_DATA_ROOT / "matching" / "free_work_vs_france_travail" / args.run_id
    decisions_path = run_dir / "triage_decisions.jsonl"

    if not decisions_path.exists():
        print(f"Erreur : Le fichier de triage {decisions_path} n'existe pas.", file=sys.stderr)
        sys.exit(1)

    print(f"Chargement des cas incertains depuis {decisions_path}...")
    uncertain_records = []
    
    with decisions_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("decision") == "UNCERTAIN" and "comparison_dossier" in record:
                uncertain_records.append(record["comparison_dossier"])

    print(f"Trouvé {len(uncertain_records)} cas UNCERTAIN.")

    # Remplacement du placeholder par les données JSON injectées
    json_data = json.dumps(uncertain_records, ensure_ascii=False)
    html_content = HTML_TEMPLATE.replace("%DATA_PLACEHOLDER%", json_data)

    output_path = run_dir / "review_queue.html"
    output_path.write_text(html_content, encoding="utf-8")
    print(f"Vue HTML de revue générée avec succès : {output_path}")


if __name__ == "__main__":
    main()
