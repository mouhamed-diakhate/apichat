"""
Tests unitaires pour la recherche sémantique vectorielle (FaqBase + VectorStore RAG)
et l'indexation des Conditions Générales de Vente (CGV).
"""
import json
from pathlib import Path
from app.intelligence.faq import FaqBase
from app.intelligence.pdf_loader import load_document_as_knowledge_entries


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_faq_vector_search_french(tmp_path):
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

    # Test avec formulation sémantique différente
    results = faq.search("Combien de temps dure la livraison ?")
    assert len(results) > 0
    assert results[0]["question"] == "Quels sont vos délais de livraison ?"
    assert "2 à 5 jours" in results[0]["reponse"]
    assert results[0]["source"]["source_type"] == "faq"
    assert results[0]["citation"].startswith("FAQ TexMiles")


def test_faq_cgv_rag_retrieval():
    """Le RAG privilégie les CGV primaires et garde leurs pages citables."""
    faq = FaqBase(PROJECT_ROOT / "data" / "faq.fr.json")

    # 1. Test délai de réclamation (Article 11: 48h)
    results = faq.search("Quel est le délai pour poser une réclamation ou plainte ?")
    assert len(results) > 0
    complaint_source = results[0]["source"]
    assert "48 heures" in results[0]["reponse"]
    assert complaint_source["filename"] == "conditions_Generales_de_vente.pdf"
    assert complaint_source["page"] == 6
    assert complaint_source["section"] == "Article 11"
    assert results[0]["citation"] == "Conditions générales de vente — Article 11 — p. 6"

    # 2. Test plafond indemnisation casse / perte (Article 6.2: 20 € / kg)
    results_casse = faq.search("Quel est le remboursement en cas de perte de colis ou avarie ?")
    assert len(results_casse) > 0
    indemnity_source = results_casse[0]["source"]
    assert "20 €" in results_casse[0]["reponse"]
    assert indemnity_source["page"] == 4
    assert indemnity_source["section"] == "Article 6.2"


def test_pdf_loader_never_merges_source_pages():
    """Un passage CGV sur la plainte doit toujours pointer vers la page 6 réelle."""
    entries = load_document_as_knowledge_entries(
        PROJECT_ROOT / "data" / "conditions_Generales_de_vente.pdf",
        source_root=PROJECT_ROOT / "data",
    )

    complaint_entries = [entry for entry in entries if "48 heures" in entry["reponse"]]
    assert len(complaint_entries) == 1
    source = complaint_entries[0]["source"]
    assert source["page"] == 6
    assert source["section"] == "Article 11"
    assert source["filename"] == "conditions_Generales_de_vente.pdf"


def test_faq_vector_search_empty_query(tmp_path):
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
    assert faq.search("Question sur des licornes interstellaires") == []
