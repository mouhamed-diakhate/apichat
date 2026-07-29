"""
Tests unitaires pour la recherche sémantique TF-IDF (FaqBase).
"""
import json
from pathlib import Path
from app.intelligence.faq import FaqBase


def test_faq_tfidf_search_french(tmp_path):
    faq_data = {
        "entrees": [
            {
                "id": "delais",
                "question": "Quels sont vos délais de livraison ?",
                "mots_cles": ["délai", "délais", "temps", "durée"],
                "reponse": "La livraison prend 2 à 5 jours ouvrés à Dakar."
            },
            {
                "id": "horaires",
                "question": "Quels sont vos horaires d'ouverture ?",
                "mots_cles": ["horaires", "heures", "ouvert"],
                "reponse": "Du lundi au samedi de 8h à 20h."
            }
        ]
    }
    faq_file = tmp_path / "faq.json"
    faq_file.write_text(json.dumps(faq_data, ensure_ascii=False), encoding="utf-8")

    faq = FaqBase(str(faq_file))

    # Test avec synonymes / mots clés dérivés
    results = faq.search("Combien de temps dure la livraison ?")
    assert len(results) > 0
    assert results[0]["question"] == "Quels sont vos délais de livraison ?"
    assert "2 à 5 jours" in results[0]["reponse"]


def test_faq_tfidf_search_empty_query(tmp_path):
    faq_data = {
        "entrees": [
            {"question": "Test ?", "mots_cles": ["test"], "reponse": "Réponse test"}
        ]
    }
    faq_file = tmp_path / "faq.json"
    faq_file.write_text(json.dumps(faq_data, ensure_ascii=False), encoding="utf-8")

    faq = FaqBase(str(faq_file))

    assert faq.search("") == []
    assert faq.search("   ") == []
