"""
Tests unitaires pour le parcours interactif (Choix de la langue -> Mode Écrire/Appel -> Menu Principal -> Agent IA).
"""

from app.services.session_manager import (
    process_interactive_step,
    get_or_create_session,
    SessionState
)


def test_session_flow_french():
    session_id = "test_user_fr_001"
    session = get_or_create_session(session_id)
    session.reset()

    # 1. Message initial -> Choix de la langue
    res, s = process_interactive_step(session_id, user_input="Bonjour")
    assert s.state == SessionState.AWAITING_LANG
    assert "Tannal sa lakk" in res["text"]
    assert len(res["buttons"]) == 3

    # 2. Choix de la langue Français (bouton "lang_fr") -> Choix du mode (Écrire / Appel)
    res, s = process_interactive_step(session_id, user_input="", action_id="lang_fr")
    assert s.state == SessionState.AWAITING_MODE
    assert s.language == "fr"
    assert "Comment souhaitez-vous échanger avec nous" in res["text"]
    assert len(res["buttons"]) == 2

    # 3. Choix d'écrire un message (bouton "mode_write") -> Menu Principal
    res, s = process_interactive_step(session_id, user_input="", action_id="mode_write")
    assert s.state == SessionState.AWAITING_MENU
    assert "Menu Principal" in res["text"]
    assert len(res["buttons"]) == 3

    # 4. Choix du service "Suivi de colis" (bouton "service_tracking")
    res, s = process_interactive_step(session_id, user_input="", action_id="service_tracking")
    assert s.state == SessionState.AGENT_ACTIVE
    assert s.selected_service == "tracking"
    assert "Suivi de colis" in res["text"]

    # 5. Envoi du numéro de commande -> Fallthrough vers l'Agent IA
    res, s = process_interactive_step(session_id, user_input="CMD-1001")
    assert res is None  # Passé à l'Agent IA


def test_session_receptionist_call():
    session_id = "test_user_call_001"
    session = get_or_create_session(session_id)
    session.reset()

    # 1. Sélection Langue FR
    process_interactive_step(session_id, user_input="1")
    assert session.state == SessionState.AWAITING_MODE

    # 2. Sélection Appel Réceptionniste (option "2")
    res, s = process_interactive_step(session_id, user_input="2")
    assert s.state == SessionState.AWAITING_MODE
    assert s.selected_mode == "call"
    assert "+221 33 800 00 00" in res["text"]
    assert "Réceptionniste" in res["text"]

    # 3. Transition vers écriture depuis la fiche appel
    res, s = process_interactive_step(session_id, user_input="", action_id="mode_write")
    assert s.state == SessionState.AWAITING_MENU
    assert "Menu Principal" in res["text"]


def test_session_flow_wolof():
    session_id = "test_user_wo_001"
    session = get_or_create_session(session_id)
    session.reset()

    # 1. Sélection Wolof via texte "2" -> Choix du mode
    res, s = process_interactive_step(session_id, user_input="2")
    assert s.state == SessionState.AWAITING_MODE
    assert s.language == "wo"
    assert "Naka nga bëggée waxtaan" in res["text"]

    # 2. Sélection Écrire un message via texte "1" -> Menu Wolof
    res, s = process_interactive_step(session_id, user_input="1")
    assert s.state == SessionState.AWAITING_MENU
    assert "Dalal ak jamm" in res["text"]

    # 3. Sélection Réclamation via texte "2"
    res, s = process_interactive_step(session_id, user_input="2")
    assert s.state == SessionState.AGENT_ACTIVE
    assert s.selected_service == "claim"
    assert "Ñaxtu / Dimbal" in res["text"]


def test_session_flow_english():
    session_id = "test_user_en_001"
    session = get_or_create_session(session_id)
    session.reset()

    # 1. Sélection Anglais via texte "3" -> Choix du mode
    res, s = process_interactive_step(session_id, user_input="3")
    assert s.state == SessionState.AWAITING_MODE
    assert s.language == "en"
    assert "How would you like to communicate" in res["text"]

    # 2. Sélection Écrire via bouton "mode_write" -> Main Menu
    res, s = process_interactive_step(session_id, user_input="", action_id="mode_write")
    assert s.state == SessionState.AWAITING_MENU
    assert "Main Menu" in res["text"]

    # 3. Sélection Order Tracking via bouton "service_tracking"
    res, s = process_interactive_step(session_id, user_input="", action_id="service_tracking")
    assert s.state == SessionState.AGENT_ACTIVE
    assert s.selected_service == "tracking"
    assert "Order Tracking" in res["text"]


def test_session_reset():
    session_id = "test_user_reset_001"
    session = get_or_create_session(session_id)
    session.language = "fr"
    session.state = SessionState.AGENT_ACTIVE

    res, s = process_interactive_step(session_id, user_input="reset")
    assert s.state == SessionState.AWAITING_LANG
    assert s.language is None

