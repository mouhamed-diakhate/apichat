"""
Tests du parcours interactif : Langue -> Mode -> Menu (3 services) -> parcours guidé.
Menu : Suivi d'opération, Demande d'opération, Demande de cotation.
"""

from app.services.session_manager import (
    process_interactive_step,
    get_or_create_session,
    SessionState,
)


def test_session_flow_french():
    sid = "test_user_fr_001"
    get_or_create_session(sid).reset()

    # 1. Message initial -> choix de la langue (4 boutons)
    res, s = process_interactive_step(sid, user_input="Bonjour")
    assert s.state == SessionState.AWAITING_LANG
    assert "Tannal sa lakk" in res["text"]
    assert len(res["buttons"]) == 4

    # 2. Français -> choix du mode (2 boutons)
    res, s = process_interactive_step(sid, user_input="", action_id="lang_fr")
    assert s.state == SessionState.AWAITING_MODE
    assert s.language == "fr"
    assert "Comment souhaitez-vous échanger avec nous" in res["text"]
    assert len(res["buttons"]) == 2

    # 3. Écrire -> menu principal (3 services)
    res, s = process_interactive_step(sid, user_input="", action_id="mode_write")
    assert s.state == SessionState.AWAITING_MENU
    assert "Menu principal" in res["text"]
    assert len(res["buttons"]) == 3

    # 4. Suivi d'opération -> agent IA
    res, s = process_interactive_step(sid, user_input="", action_id="service_tracking")
    assert s.state == SessionState.AGENT_ACTIVE
    assert s.selected_service == "tracking"
    assert "Suivi d'opération" in res["text"]

    # 5. Numéro de commande -> passe à l'agent IA (réponse None)
    res, s = process_interactive_step(sid, user_input="CMD1002")
    assert res is None


def test_demande_operation_guidee():
    """Demande d'opération : provenance -> destination -> transport -> pickup."""
    sid = "test_op_001"
    get_or_create_session(sid).reset()
    process_interactive_step(sid, "", "lang_fr")
    process_interactive_step(sid, "", "mode_write")

    res, s = process_interactive_step(sid, "", "service_operation")
    assert s.state == SessionState.COLLECT_ORIGIN
    assert "provenance" in res["text"].lower()

    res, s = process_interactive_step(sid, "Dakar")
    assert s.state == SessionState.COLLECT_DEST

    res, s = process_interactive_step(sid, "Abidjan")
    assert s.state == SessionState.COLLECT_TRANSPORT
    # boutons de transport
    ids = [b["id"] for b in res["buttons"]]
    assert ids == ["transport_routier", "transport_maritime", "transport_air"]

    res, s = process_interactive_step(sid, "", "transport_air")
    assert s.state == SessionState.COLLECT_PICKUP

    res, s = process_interactive_step(sid, "Rue 10, mardi 9h")
    assert res["intent"] == "operation"
    assert res["reference"].startswith("OP-")
    assert res.get("persist") is True
    assert "Abidjan" in res["text"]


def test_demande_cotation_puis_non():
    """Cotation : estimation de prix enregistrée, puis on garde le devis (pas d'opération)."""
    sid = "test_cot_001"
    get_or_create_session(sid).reset()
    process_interactive_step(sid, "", "lang_fr")
    process_interactive_step(sid, "", "mode_write")

    process_interactive_step(sid, "", "service_quotation")
    process_interactive_step(sid, "Dakar")
    res, s = process_interactive_step(sid, "Bamako")
    assert s.state == SessionState.COLLECT_TRANSPORT

    res, s = process_interactive_step(sid, "", "transport_routier")
    assert s.state == SessionState.COT_WANT_OP
    assert "FCFA" in res["text"]
    assert res["intent"] == "quotation"
    assert res["reference"].startswith("COT-")
    # boutons Oui / Non
    ids = [b["id"] for b in res["buttons"]]
    assert ids == ["op_yes", "op_no"]

    res, s = process_interactive_step(sid, "", "op_no")
    assert s.state == SessionState.AWAITING_MENU
    assert res["intent"] == "quotation"
    assert "devis" in res["text"].lower()


def test_cotation_puis_oui_devient_operation():
    sid = "test_cot_002"
    get_or_create_session(sid).reset()
    process_interactive_step(sid, "", "lang_fr")
    process_interactive_step(sid, "", "mode_write")
    process_interactive_step(sid, "", "service_quotation")
    process_interactive_step(sid, "Dakar")
    process_interactive_step(sid, "Paris")
    process_interactive_step(sid, "", "transport_maritime")

    res, s = process_interactive_step(sid, "", "op_yes")
    assert s.state == SessionState.COLLECT_PICKUP

    res, s = process_interactive_step(sid, "12 Rue de la Paix, vendredi")
    assert res["intent"] == "operation"
    assert res["reference"].startswith("OP-")
    assert "Devis lié" in res["text"]  # l'opération référence la cotation


def test_session_receptionist_call():
    sid = "test_user_call_001"
    get_or_create_session(sid).reset()
    process_interactive_step(sid, user_input="1")  # FR

    res, s = process_interactive_step(sid, user_input="2")  # appel
    assert s.selected_mode == "call"
    assert "+221 33 800 00 00" in res["text"]
    assert "Réceptionniste" in res["text"]

    res, s = process_interactive_step(sid, user_input="", action_id="mode_write")
    assert s.state == SessionState.AWAITING_MENU
    assert "Menu principal" in res["text"]


def test_session_flow_wolof():
    sid = "test_user_wo_001"
    get_or_create_session(sid).reset()

    res, s = process_interactive_step(sid, user_input="2")  # Wolof
    assert s.state == SessionState.AWAITING_MODE
    assert s.language == "wo"
    assert "Naka nga bëggée waxtaan" in res["text"]

    res, s = process_interactive_step(sid, user_input="1")  # Écrire -> menu
    assert s.state == SessionState.AWAITING_MENU
    assert "Lu nga bëgg def" in res["text"]

    # Demande d'opération (option 2) -> parcours guidé
    res, s = process_interactive_step(sid, user_input="2")
    assert s.state == SessionState.COLLECT_ORIGIN
    assert s.selected_service == "operation"


def test_session_flow_english():
    sid = "test_user_en_001"
    get_or_create_session(sid).reset()

    res, s = process_interactive_step(sid, user_input="3")  # English
    assert s.state == SessionState.AWAITING_MODE
    assert s.language == "en"
    assert "How would you like to communicate" in res["text"]

    res, s = process_interactive_step(sid, user_input="", action_id="mode_write")
    assert s.state == SessionState.AWAITING_MENU
    assert "Main Menu" in res["text"]

    res, s = process_interactive_step(sid, user_input="", action_id="service_tracking")
    assert s.state == SessionState.AGENT_ACTIVE
    assert s.selected_service == "tracking"
    assert "tracking" in res["text"].lower()


def test_session_flow_arabic():
    sid = "test_user_ar_001"
    get_or_create_session(sid).reset()

    res, s = process_interactive_step(sid, user_input="4")  # Arabe
    assert s.state == SessionState.AWAITING_MODE
    assert s.language == "ar"

    res, s = process_interactive_step(sid, user_input="", action_id="mode_write")
    assert s.state == SessionState.AWAITING_MENU
    assert "القائمة الرئيسية" in res["text"]

    # Demande de cotation -> parcours guidé (pas directement l'agent IA)
    res, s = process_interactive_step(sid, user_input="", action_id="service_quotation")
    assert s.state == SessionState.COLLECT_ORIGIN
    assert s.selected_service == "quotation"


def test_reclamation_libre_escalade_humain():
    """Une réclamation tapée au menu -> prise en compte + escalade vers un humain."""
    sid = "test_claim_001"
    get_or_create_session(sid).reset()
    process_interactive_step(sid, "", "lang_fr")
    process_interactive_step(sid, "", "mode_write")  # -> menu

    res, s = process_interactive_step(sid, "Mon colis est arrivé endommagé, c'est inadmissible")
    assert s.selected_service == "claim"
    assert res["intent"] == "claim"
    assert res["escalade"] is True
    assert res["reference"].startswith("REC-")
    assert res.get("persist") is True
    assert "humain" in res["text"].lower()


def test_reclamation_pendant_conversation():
    """Une plainte pendant une conversation agent est aussi escaladée."""
    sid = "test_claim_002"
    get_or_create_session(sid).reset()
    process_interactive_step(sid, "", "lang_fr")
    process_interactive_step(sid, "", "mode_write")
    process_interactive_step(sid, "", "service_tracking")  # -> AGENT_ACTIVE

    res, s = process_interactive_step(sid, "je veux un remboursement, colis perdu")
    assert res["intent"] == "claim"
    assert res["escalade"] is True


def test_question_normale_pas_reclamation():
    """Une question FAQ normale n'est PAS traitée comme une réclamation (va à l'agent IA)."""
    sid = "test_faq_001"
    get_or_create_session(sid).reset()
    process_interactive_step(sid, "", "lang_fr")
    process_interactive_step(sid, "", "mode_write")

    res, s = process_interactive_step(sid, "Quels sont vos délais de livraison ?")
    assert res is None  # -> agent IA (FAQ)


def test_session_reset():
    sid = "test_user_reset_001"
    s = get_or_create_session(sid)
    s.language = "fr"
    s.state = SessionState.AGENT_ACTIVE

    res, s = process_interactive_step(sid, user_input="reset")
    assert s.state == SessionState.AWAITING_LANG
    assert s.language is None
