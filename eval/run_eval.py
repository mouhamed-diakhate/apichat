"""
Harnais d'évaluation : fait passer tous les cas de test dans le VRAI pipeline et
affiche un rapport pass/échec.

Lancement (depuis apichat/) :
    py -m eval.run_eval

Chaque cas est un fichier JSON dans eval/cases/. Champs :
  - id, langue, input_client, comportement_attendu, doit_escalader, categorie_test
    (les champs demandés par le cahier des charges)
  - attendu_contient      : liste de textes qui DOIVENT apparaître dans la réponse
  - ne_doit_pas_contenir  : liste de textes qui NE doivent PAS apparaître
  - ticket_attendu        : true si une réclamation (ticket) doit être ouverte
Ces trois derniers champs sont optionnels : ils permettent une vérification
automatique et objective, en plus de l'escalade.
"""

import json
import sys
import unicodedata
from pathlib import Path

from app.intelligence.config import build_assistant

# La console Windows (cp1252) ne sait pas afficher certains caractères des réponses
# du modèle (accents, espaces insécables français...). On force l'UTF-8 pour éviter
# tout plantage d'affichage et garder les accents lisibles.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

DOSSIER_CAS = Path(__file__).resolve().parent / "cases"


def _normaliser(texte: str) -> str:
    texte = (texte or "").lower()
    texte = unicodedata.normalize("NFD", texte)
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    # Uniformise tous les espaces (y compris insécables/fines typographiques françaises)
    # en espaces simples, sinon "14 jours" écrit avec un espace fin ne matcherait pas.
    return " ".join(texte.split())


def _verifier(cas: dict, reply) -> list[str]:
    """Renvoie la liste des problèmes (vide = cas réussi)."""
    problemes = []
    reponse_norm = _normaliser(reply.texte)

    # 1) Escalade attendue ?
    if bool(cas.get("doit_escalader")) != bool(reply.escalade):
        problemes.append(
            f"escalade={reply.escalade}, attendu={cas.get('doit_escalader')}"
        )

    # 2) Textes qui doivent apparaître.
    for attendu in cas.get("attendu_contient", []):
        if _normaliser(attendu) not in reponse_norm:
            problemes.append(f"manque le texte : '{attendu}'")

    # 3) Textes interdits.
    for interdit in cas.get("ne_doit_pas_contenir", []):
        if _normaliser(interdit) in reponse_norm:
            problemes.append(f"contient un texte interdit : '{interdit}'")

    # 4) Ticket de réclamation attendu.
    if cas.get("ticket_attendu") and not reply.ticket_id:
        problemes.append("aucun ticket de réclamation ouvert alors qu'il était attendu")

    return problemes


def main():
    try:
        assistant = build_assistant()
    except RuntimeError as e:
        print(f"[Configuration] {e}")
        return

    fichiers = sorted(DOSSIER_CAS.glob("*.json"))
    if not fichiers:
        print("Aucun cas de test trouvé dans eval/cases/.")
        return

    total = 0
    reussis = 0
    print(f"Exécution de {len(fichiers)} cas de test...\n")

    for f in fichiers:
        cas = json.loads(f.read_text(encoding="utf-8"))
        total += 1
        reply = assistant.handle(cas["input_client"])
        problemes = _verifier(cas, reply)

        if not problemes:
            reussis += 1
            print(f"[OK]     {cas['id']} ({cas['categorie_test']})")
        else:
            print(f"[ECHEC]  {cas['id']} ({cas['categorie_test']})")
            print(f"         client   : {cas['input_client']}")
            print(f"         réponse  : {reply.texte}")
            for p in problemes:
                print(f"         -> {p}")
        print()

    print("=" * 50)
    print(f"Résultat : {reussis}/{total} cas réussis.")


if __name__ == "__main__":
    main()
