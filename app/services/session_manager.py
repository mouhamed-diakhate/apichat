"""
Gestionnaire de session conversationnelle :
Gère l'état de la conversation (Langue -> Menu -> Agent IA) indépendamment du canal (Web Chat ou WhatsApp Webhook).
"""

from typing import Any, Dict, Optional, Tuple


class SessionState:
    AWAITING_LANG = "AWAITING_LANG"
    AWAITING_MODE = "AWAITING_MODE"
    AWAITING_MENU = "AWAITING_MENU"
    AGENT_ACTIVE = "AGENT_ACTIVE"


class UserSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.state: str = SessionState.AWAITING_LANG
        self.language: Optional[str] = None  # "fr", "wo" ou "en"
        self.selected_mode: Optional[str] = None  # "write" ou "call"
        self.selected_service: Optional[str] = None  # "tracking", "claim", "faq", "general"
        self.history: list[dict] = []

    def reset(self):
        self.state = SessionState.AWAITING_LANG
        self.language = None
        self.selected_mode = None
        self.selected_service = None
        self.history = []


# Dictionnaire en mémoire des sessions (pouvant être remplacé par Redis/PostgreSQL)
_SESSIONS: Dict[str, UserSession] = {}


def get_or_create_session(session_id: str) -> UserSession:
    if session_id not in _SESSIONS:
        _SESSIONS[session_id] = UserSession(session_id)
    return _SESSIONS[session_id]


# Textes des menus
LANG_CHOICE_PAYLOAD = {
    "text": "Bonjour ! 👋 / Nanga def ! 👋 / Hello ! 👋\nBienvenue chez TexMiles (Groupe Logidoo).\nVeuillez choisir votre langue / Tannal sa lakk / Choose your language:",
    "buttons": [
        {"id": "lang_fr", "label": "Français 🇫🇷"},
        {"id": "lang_wo", "label": "Wolof 🇸🇳"},
        {"id": "lang_en", "label": "English 🇬🇧"}
    ],
    "options": [
        "1. Français 🇫🇷",
        "2. Wolof 🇸🇳",
        "3. English 🇬🇧"
    ]
}

MODE_CHOICE_PAYLOAD_FR = {
    "text": "Comment souhaitez-vous échanger avec nous ? Choisissez une option :",
    "buttons": [
        {"id": "mode_write", "label": "💬 Écrire un message"},
        {"id": "mode_call", "label": "📞 Appel Réceptionniste"}
    ],
    "options": [
        "1. 💬 Écrire un message",
        "2. 📞 Faire un appel téléphonique vers la réceptionniste"
    ]
}

MODE_CHOICE_PAYLOAD_WO = {
    "text": "Naka nga bëggée waxtaan ak nu ? Tannal am opsiyoŋ :",
    "buttons": [
        {"id": "mode_write", "label": "💬 Bind ab bataaxal"},
        {"id": "mode_call", "label": "📞 Wo réceptionniste bi"}
    ],
    "options": [
        "1. 💬 Bind ab bataaxal (Écrire un message)",
        "2. 📞 Wo réceptionniste bi (Appel téléphonique)"
    ]
}

MODE_CHOICE_PAYLOAD_EN = {
    "text": "How would you like to communicate with us? Please choose an option:",
    "buttons": [
        {"id": "mode_write", "label": "💬 Write a message"},
        {"id": "mode_call", "label": "📞 Receptionist Phone Call"}
    ],
    "options": [
        "1. 💬 Write a message",
        "2. 📞 Make a phone call to the receptionist"
    ]
}

MENU_PAYLOAD_FR = {
    "text": "Bienvenue sur le **Menu Principal** TexMiles ! 📦\nComment puis-je vous aider aujourd'hui ? Choisissez une option :",
    "buttons": [
        {"id": "service_tracking", "label": "📦 Suivi de colis"},
        {"id": "service_claim", "label": "📝 Réclamation"},
        {"id": "service_faq", "label": "❓ FAQ & Info"}
    ],
    "options": [
        "1. 📦 Suivi de colis",
        "2. 📝 Réclamation / Support",
        "3. ❓ Questions fréquentes (FAQ)"
    ]
}

MENU_PAYLOAD_WO = {
    "text": "Dalal ak jamm ci **Menu Principal** TexMiles ! 📦\nNaka lañu la mën a dimbale tey ? Tannal am serbis :",
    "buttons": [
        {"id": "service_tracking", "label": "📦 Topatu mboolo"},
        {"id": "service_claim", "label": "📝 Ñaxtu / Dimbal"},
        {"id": "service_faq", "label": "❓ FAQ & Léral"}
    ],
    "options": [
        "1. 📦 Topatu sa mboolo (Suivi de colis)",
        "2. 📝 Ñaxtu / Dimbal (Réclamation)",
        "3. ❓ Laaj yees tamal (FAQ)"
    ]
}

MENU_PAYLOAD_EN = {
    "text": "Welcome to the TexMiles **Main Menu**! 📦\nHow can I help you today? Please choose an option:",
    "buttons": [
        {"id": "service_tracking", "label": "📦 Order Tracking"},
        {"id": "service_claim", "label": "📝 Claim & Support"},
        {"id": "service_faq", "label": "❓ FAQ & Info"}
    ],
    "options": [
        "1. 📦 Order tracking",
        "2. 📝 Claim & Support",
        "3. ❓ Frequently Asked Questions (FAQ)"
    ]
}


def process_interactive_step(
    session_id: str,
    user_input: str,
    action_id: Optional[str] = None
) -> Tuple[Optional[Dict[str, Any]], UserSession]:
    """
    Traite une interaction utilisateur et retourne la réponse formatée et l'objet session.
    """
    session = get_or_create_session(session_id)
    text_clean = (user_input or "").strip().lower()

    # Commande de réinitialisation universelle
    if text_clean in ["reset", "menu", "retour", "start", "restart", "0"] or action_id == "menu_reset":
        session.reset()
        response = {
            "text": LANG_CHOICE_PAYLOAD["text"],
            "buttons": LANG_CHOICE_PAYLOAD["buttons"],
            "state": session.state,
            "language": session.language
        }
        return response, session

    # ÉTAPE 1 : Choix de la langue
    if session.state == SessionState.AWAITING_LANG:
        # Premier appel (message vide, pas d'action) → afficher directement le bienvenu
        if not text_clean and not action_id:
            response = {
                "text": LANG_CHOICE_PAYLOAD["text"],
                "buttons": LANG_CHOICE_PAYLOAD["buttons"],
                "state": session.state,
                "language": session.language
            }
            return response, session

        if action_id == "lang_fr" or text_clean in ["1", "fr", "français", "francais"]:
            session.language = "fr"
            session.state = SessionState.AWAITING_MODE
            mode_data = MODE_CHOICE_PAYLOAD_FR
            response = {
                "text": f"✅ Langue enregistrée : **Français**\n\n{mode_data['text']}",
                "buttons": mode_data["buttons"],
                "state": session.state,
                "language": session.language
            }
            return response, session

        elif action_id == "lang_wo" or text_clean in ["2", "wo", "wolof"]:
            session.language = "wo"
            session.state = SessionState.AWAITING_MODE
            mode_data = MODE_CHOICE_PAYLOAD_WO
            response = {
                "text": f"✅ Lakk bi nga tann : **Wolof**\n\n{mode_data['text']}",
                "buttons": mode_data["buttons"],
                "state": session.state,
                "language": session.language
            }
            return response, session

        elif action_id == "lang_en" or text_clean in ["3", "en", "english", "anglais"]:
            session.language = "en"
            session.state = SessionState.AWAITING_MODE
            mode_data = MODE_CHOICE_PAYLOAD_EN
            response = {
                "text": f"✅ Selected language: **English**\n\n{mode_data['text']}",
                "buttons": mode_data["buttons"],
                "state": session.state,
                "language": session.language
            }
            return response, session
        else:
            # Relancer le choix de langue
            response = {
                "text": "Veuillez choisir une langue valide (1. FR, 2. WO, 3. EN) / Please choose a valid language:\n\n" + LANG_CHOICE_PAYLOAD["text"],
                "buttons": LANG_CHOICE_PAYLOAD["buttons"],
                "state": session.state,
                "language": session.language
            }
            return response, session

    # ÉTAPE 2 : Choix du mode de communication (Écrire ou Appeler)
    if session.state == SessionState.AWAITING_MODE:
        if action_id == "mode_write" or text_clean in ["1", "écrire", "ecrire", "write", "bind", "message", "chat"]:
            session.selected_mode = "write"
            session.state = SessionState.AWAITING_MENU
            if session.language == "wo":
                menu_data = MENU_PAYLOAD_WO
            elif session.language == "en":
                menu_data = MENU_PAYLOAD_EN
            else:
                menu_data = MENU_PAYLOAD_FR

            response = {
                "text": menu_data["text"],
                "buttons": menu_data["buttons"],
                "state": session.state,
                "language": session.language
            }
            return response, session

        elif action_id == "mode_call" or text_clean in ["2", "appel", "appeler", "téléphone", "telephone", "phone", "call", "wo", "réceptionniste", "receptionniste"]:
            session.selected_mode = "call"
            if session.language == "en":
                msg = (
                    "📞 **TexMiles Receptionist Service**\n\n"
                    "You can reach our receptionist directly by phone at:\n"
                    "👉 **+221 33 800 00 00** / **+221 77 123 45 67**\n\n"
                    "🕒 Opening Hours: Monday to Saturday, 8:00 AM to 6:00 PM.\n\n"
                    "Would you like to send a message instead?"
                )
                btn_write = "💬 Write a message"
                btn_reset = "🔄 Change language"
            elif session.language == "wo":
                msg = (
                    "📞 **Serbis Réception TexMiles**\n\n"
                    "Mën nga wo sunu réceptionniste ci télefoon ci nimero bi :\n"
                    "👉 **+221 33 800 00 00** / **+221 77 123 45 67**\n\n"
                    "🕒 Jamono liggéey : Altine ba Gaawu, 08h00 ba 18h00.\n\n"
                    "Bëgg nga weey ci bind ab bataaxal ?"
                )
                btn_write = "💬 Bind ab bataaxal"
                btn_reset = "🔄 Tannat lakk"
            else:
                msg = (
                    "📞 **Contact Réceptionniste TexMiles**\n\n"
                    "Vous pouvez joindre notre réceptionniste par téléphone au :\n"
                    "👉 **+221 33 800 00 00** / **+221 77 123 45 67**\n\n"
                    "🕒 Horaires de la réception : Lundi au Samedi, 08h00 - 18h00.\n\n"
                    "Souhaitez-vous plutôt nous écrire un message ?"
                )
                btn_write = "💬 Écrire un message"
                btn_reset = "🔄 Changer de langue"

            response = {
                "text": msg,
                "buttons": [
                    {"id": "mode_write", "label": btn_write},
                    {"id": "menu_reset", "label": btn_reset}
                ],
                "state": session.state,
                "language": session.language,
                "mode": session.selected_mode
            }
            return response, session

        else:
            # Relancer le choix du mode
            if session.language == "wo":
                mode_data = MODE_CHOICE_PAYLOAD_WO
                prompt_err = "Veuillez choisir une option valide / Tannal opsiyoŋ bi nga bëgg :\n\n"
            elif session.language == "en":
                mode_data = MODE_CHOICE_PAYLOAD_EN
                prompt_err = "Please choose a valid option:\n\n"
            else:
                mode_data = MODE_CHOICE_PAYLOAD_FR
                prompt_err = "Veuillez choisir une option valide :\n\n"

            response = {
                "text": prompt_err + mode_data["text"],
                "buttons": mode_data["buttons"],
                "state": session.state,
                "language": session.language
            }
            return response, session

    # ÉTAPE 3 : Choix du service dans le Menu
    if session.state == SessionState.AWAITING_MENU:
        if action_id == "service_tracking" or text_clean in ["1", "suivi", "colis", "tracking", "topatu"]:
            session.selected_service = "tracking"
            session.state = SessionState.AGENT_ACTIVE
            if session.language == "en":
                msg = "You have selected **Order Tracking** 📦.\nPlease provide your order number (e.g. `CMD-1001`)."
                btn_label = "🔄 Back to Menu"
            elif session.language == "wo":
                msg = "Tann nga **Topatu sa mboolo** 📦.\nJox ma nimero commande bi (ex: `CMD-1001`)."
                btn_label = "🔄 Retour au Menu"
            else:
                msg = "Vous avez choisi le **Suivi de colis** 📦.\nVeuillez me donner votre numéro de commande (ex: `CMD-1001`)."
                btn_label = "🔄 Retour au Menu"

            response = {
                "text": msg,
                "buttons": [{"id": "menu_reset", "label": btn_label}],
                "state": session.state,
                "language": session.language,
                "service": session.selected_service
            }
            return response, session

        elif action_id == "service_claim" or text_clean in ["2", "reclamation", "réclamation", "claim", "ñaxtu", "support"]:
            session.selected_service = "claim"
            session.state = SessionState.AGENT_ACTIVE
            if session.language == "en":
                msg = "You have selected **Claim & Support** 📝.\nPlease describe the issue you encountered with your delivery."
                btn_label = "🔄 Back to Menu"
            elif session.language == "wo":
                msg = "Tann nga **Ñaxtu / Dimbal** 📝.\nLéralal ma jaafe-jaafe bi nga am ci sa mboolo walla livreson."
                btn_label = "🔄 Retour au Menu"
            else:
                msg = "Vous avez choisi **Réclamation & Support** 📝.\nDécrivez-moi le problème rencontré avec votre colis ou livraison."
                btn_label = "🔄 Retour au Menu"

            response = {
                "text": msg,
                "buttons": [{"id": "menu_reset", "label": btn_label}],
                "state": session.state,
                "language": session.language,
                "service": session.selected_service
            }
            return response, session

        elif action_id == "service_faq" or text_clean in ["3", "faq", "question", "laaj", "info"]:
            session.selected_service = "faq"
            session.state = SessionState.AGENT_ACTIVE
            if session.language == "en":
                msg = "You have selected **Frequently Asked Questions (FAQ)** ❓.\nAsk me any question regarding our prices, delivery delays or areas."
                btn_label = "🔄 Back to Menu"
            elif session.language == "wo":
                msg = "Tann nga **Questions fréquentes (FAQ)** ❓.\nLaajal ma lu jëm ci sunu njég, jamono walla bérab yi ñuy livrer."
                btn_label = "🔄 Retour au Menu"
            else:
                msg = "Vous avez choisi **Questions fréquentes (FAQ)** ❓.\nPosez-moi votre question sur nos tarifs, délais ou zones de livraison."
                btn_label = "🔄 Retour au Menu"

            response = {
                "text": msg,
                "buttons": [{"id": "menu_reset", "label": btn_label}],
                "state": session.state,
                "language": session.language,
                "service": session.selected_service
            }
            return response, session

        else:
            # Si l'utilisateur pose directement sa question dans le menu sans taper 1, 2, 3
            session.selected_service = "general"
            session.state = SessionState.AGENT_ACTIVE
            # Continuer vers le traitement par l'agent IA ci-dessous (fallthrough)

    # ÉTAPE 4 : Agent IA actif (traitement intelligent)
    return None, session
