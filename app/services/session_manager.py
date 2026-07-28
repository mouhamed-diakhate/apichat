"""
Gestionnaire de session conversationnelle (canal-agnostique : Web Chat ou WhatsApp).

Parcours :
  Langue -> Mode (écrire / appel) -> Menu principal -> parcours guidé pas à pas.

Menu principal (3 services) :
  1. Suivi d'opération      -> confié à l'agent IA (recherche de commande).
  2. Demande d'opération    -> parcours guidé : provenance -> destination -> transport -> pickup.
  3. Demande de cotation    -> même collecte, puis ESTIMATION de prix enregistrée,
                               puis on demande si le client veut lancer une opération.

Les choix fixes (transport, oui/non) sont des BOUTONS ; les infos libres
(provenance, destination, pickup) sont saisies une par une.
"""

import random
import unicodedata
from typing import Any, Dict, Optional, Tuple


class SessionState:
    AWAITING_LANG = "AWAITING_LANG"
    AWAITING_MODE = "AWAITING_MODE"
    AWAITING_MENU = "AWAITING_MENU"
    AGENT_ACTIVE = "AGENT_ACTIVE"
    # Parcours guidé cotation / opération
    COLLECT_ORIGIN = "COLLECT_ORIGIN"
    COLLECT_DEST = "COLLECT_DEST"
    COLLECT_TRANSPORT = "COLLECT_TRANSPORT"
    COLLECT_PICKUP = "COLLECT_PICKUP"
    COT_WANT_OP = "COT_WANT_OP"


class UserSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.state: str = SessionState.AWAITING_LANG
        self.language: Optional[str] = None       # "fr", "wo", "en", "ar"
        self.selected_mode: Optional[str] = None   # "write" ou "call"
        self.selected_service: Optional[str] = None
        self.history: list[dict] = []
        self.data: dict = {}                        # données du parcours guidé

    def reset(self):
        self.state = SessionState.AWAITING_LANG
        self.language = None
        self.selected_mode = None
        self.selected_service = None
        self.history = []
        self.data = {}


_SESSIONS: Dict[str, UserSession] = {}


def get_or_create_session(session_id: str) -> UserSession:
    if session_id not in _SESSIONS:
        _SESSIONS[session_id] = UserSession(session_id)
    return _SESSIONS[session_id]


# ─── Menus d'accueil (langue / mode) ─────────────────────────────────────────
LANG_CHOICE_PAYLOAD = {
    "text": "Bonjour ! 👋 / Nanga def ! 👋 / Hello ! 👋 / مرحبا بكم ! 👋\nBienvenue chez TexMiles (Groupe Logidoo).\nVeuillez choisir votre langue / Tannal sa lakk / Choose your language / اختر لغتك:",
    "buttons": [
        {"id": "lang_fr", "label": "Français 🇫🇷"},
        {"id": "lang_wo", "label": "Wolof 🇸🇳"},
        {"id": "lang_en", "label": "English 🇬🇧"},
        {"id": "lang_ar", "label": "العربية 🇸🇦"},
    ],
}

MODE_CHOICE_PAYLOAD_FR = {
    "text": "Comment souhaitez-vous échanger avec nous ?",
    "buttons": [
        {"id": "mode_write", "label": "💬 Écrire un message"},
        {"id": "mode_call", "label": "📞 Appel Réceptionniste"},
    ],
}
MODE_CHOICE_PAYLOAD_WO = {
    "text": "Naka nga bëggée waxtaan ak nu ?",
    "buttons": [
        {"id": "mode_write", "label": "💬 Bind ab bataaxal"},
        {"id": "mode_call", "label": "📞 Wo réceptionniste bi"},
    ],
}
MODE_CHOICE_PAYLOAD_EN = {
    "text": "How would you like to communicate with us?",
    "buttons": [
        {"id": "mode_write", "label": "💬 Write a message"},
        {"id": "mode_call", "label": "📞 Receptionist Call"},
    ],
}
MODE_CHOICE_PAYLOAD_AR = {
    "text": "كيف ترغب في التواصل معنا؟",
    "buttons": [
        {"id": "mode_write", "label": "💬 كتابة رسالة"},
        {"id": "mode_call", "label": "📞 الاتصال بالاستقبال"},
    ],
}

# ─── Menu principal (3 services : Suivi, Opération, Cotation) ─────────────────
MENU_PAYLOAD_FR = {
    "text": "Menu principal TexMiles 📦\nQue souhaitez-vous faire ?",
    "buttons": [
        {"id": "service_tracking", "label": "📦 Suivi d'opération"},
        {"id": "service_operation", "label": "🚚 Demande d'opération"},
        {"id": "service_quotation", "label": "📋 Demande de cotation"},
    ],
}
MENU_PAYLOAD_WO = {
    "text": "Menu principal TexMiles 📦\nLu nga bëgg def ?",
    "buttons": [
        {"id": "service_tracking", "label": "📦 Topatu opération"},
        {"id": "service_operation", "label": "🚚 Laaj opération"},
        {"id": "service_quotation", "label": "📋 Laaj njég (cotation)"},
    ],
}
MENU_PAYLOAD_EN = {
    "text": "TexMiles Main Menu 📦\nHow can we help?",
    "buttons": [
        {"id": "service_tracking", "label": "📦 Track an operation"},
        {"id": "service_operation", "label": "🚚 Operation request"},
        {"id": "service_quotation", "label": "📋 Quotation request"},
    ],
}
MENU_PAYLOAD_AR = {
    "text": "القائمة الرئيسية TexMiles 📦\nكيف يمكننا مساعدتك؟",
    "buttons": [
        {"id": "service_tracking", "label": "📦 تتبع عملية"},
        {"id": "service_operation", "label": "🚚 طلب عملية"},
        {"id": "service_quotation", "label": "📋 طلب تسعير"},
    ],
}


def _menu_for(lang: Optional[str]) -> dict:
    return {"wo": MENU_PAYLOAD_WO, "en": MENU_PAYLOAD_EN, "ar": MENU_PAYLOAD_AR}.get(lang or "fr", MENU_PAYLOAD_FR)


def _mode_for(lang: Optional[str]) -> dict:
    return {"wo": MODE_CHOICE_PAYLOAD_WO, "en": MODE_CHOICE_PAYLOAD_EN, "ar": MODE_CHOICE_PAYLOAD_AR}.get(lang or "fr", MODE_CHOICE_PAYLOAD_FR)


# ─── Textes du parcours guidé (cotation / opération) ─────────────────────────
FLOW_TXT = {
    "fr": {
        "ask_origin": "📍 Quel est le *lieu de provenance* (ville / pays de départ) ?",
        "ask_dest": "🎯 Quel est le *lieu de destination* (ville / pays d'arrivée) ?",
        "ask_transport": "🚚 Choisissez le *moyen de transport* :",
        "ask_pickup": "📦 Indiquez l'*adresse* et la *date* souhaitées pour le pickup (enlèvement).",
        "back": "🔄 Retour au menu",
        "yes": "✅ Oui, lancer l'opération",
        "no": "❌ Non, garder le devis",
        "cot_estimate": (
            "💰 *Estimation de prix (sans engagement)*\n"
            "De : {origin}\nÀ : {destination}\nTransport : {transport}\n"
            "➡️ Prix estimé : *à partir de {price} FCFA*\n"
            "Référence devis : *{ref}*\n\n"
            "Souhaitez-vous lancer une *demande d'opération* (expédition réelle) ?"
        ),
        "cot_saved": "✅ Votre devis *{ref}* est enregistré. Notre équipe commerciale pourra vous recontacter. Merci !",
        "op_created": (
            "✅ *Demande d'opération enregistrée !*\n"
            "Référence : *{ref}*\nDe : {origin} → {destination}\n"
            "Transport : {transport}\nPickup : {pickup}\nDevis lié : {cotation}\n\n"
            "Un agent vous contactera pour confirmer l'enlèvement."
        ),
    },
    "en": {
        "ask_origin": "📍 What is the *origin* (departure city / country)?",
        "ask_dest": "🎯 What is the *destination* (arrival city / country)?",
        "ask_transport": "🚚 Choose the *transport mode*:",
        "ask_pickup": "📦 Please provide the *address* and *date* for pickup.",
        "back": "🔄 Back to menu",
        "yes": "✅ Yes, start operation",
        "no": "❌ No, keep the quote",
        "cot_estimate": (
            "💰 *Estimated price (no commitment)*\n"
            "From: {origin}\nTo: {destination}\nTransport: {transport}\n"
            "➡️ Estimated price: *from {price} FCFA*\n"
            "Quote reference: *{ref}*\n\n"
            "Would you like to start an *operation request* (real shipment)?"
        ),
        "cot_saved": "✅ Your quote *{ref}* is saved. Our sales team may contact you. Thank you!",
        "op_created": (
            "✅ *Operation request registered!*\n"
            "Reference: *{ref}*\nFrom: {origin} → {destination}\n"
            "Transport: {transport}\nPickup: {pickup}\nLinked quote: {cotation}\n\n"
            "An agent will contact you to confirm pickup."
        ),
    },
    "wo": {
        "ask_origin": "📍 Fan la colis bi *joge* (dëkk / réew) ?",
        "ask_dest": "🎯 Fan la colis bi *jëm* (dëkk / réew) ?",
        "ask_transport": "🚚 Tànnal *moyen transport bi* :",
        "ask_pickup": "📦 Bindal *adresse* ak *bés* bi nga bëgg ñu ñëw jël colis bi.",
        "back": "🔄 Dellu ci menu bi",
        "yes": "✅ Waaw, tàmbali opération",
        "no": "❌ Déedéet, denc devis bi",
        "cot_estimate": (
            "💰 *Estimation njég (sans engagement)*\n"
            "Joge : {origin}\nJëm : {destination}\nTransport : {transport}\n"
            "➡️ Njég bu ñu jàpp : *à partir de {price} FCFA*\n"
            "Référence devis : *{ref}*\n\n"
            "Ndax nga bëgg tàmbali ab *demande d'opération* ?"
        ),
        "cot_saved": "✅ Devis bi *{ref}* enregistré na. Sunu équipe dina la mën a woote. Jërëjëf !",
        "op_created": (
            "✅ *Demande d'opération enregistré na !*\n"
            "Référence : *{ref}*\nJoge : {origin} → {destination}\n"
            "Transport : {transport}\nPickup : {pickup}\nDevis : {cotation}\n\n"
            "Ab agent dina la woote ngir confirmer enlèvement bi."
        ),
    },
    "ar": {
        "ask_origin": "📍 ما هو *مكان الانطلاق* (مدينة / بلد المغادرة)؟",
        "ask_dest": "🎯 ما هي *الوجهة* (مدينة / بلد الوصول)؟",
        "ask_transport": "🚚 اختر *وسيلة النقل*:",
        "ask_pickup": "📦 يرجى تقديم *العنوان* و*التاريخ* للاستلام.",
        "back": "🔄 العودة للقائمة",
        "yes": "✅ نعم، ابدأ العملية",
        "no": "❌ لا، احتفظ بالعرض",
        "cot_estimate": (
            "💰 *تقدير السعر (بدون التزام)*\n"
            "من: {origin}\nإلى: {destination}\nالنقل: {transport}\n"
            "➡️ السعر التقديري: *ابتداءً من {price} FCFA*\n"
            "مرجع العرض: *{ref}*\n\n"
            "هل ترغب في بدء *طلب عملية* (شحن فعلي)؟"
        ),
        "cot_saved": "✅ تم حفظ عرضك *{ref}*. قد يتصل بك فريق المبيعات. شكراً!",
        "op_created": (
            "✅ *تم تسجيل طلب العملية!*\n"
            "المرجع: *{ref}*\nمن: {origin} → {destination}\n"
            "النقل: {transport}\nالاستلام: {pickup}\nالعرض المرتبط: {cotation}\n\n"
            "سيتصل بك أحد الوكلاء لتأكيد الاستلام."
        ),
    },
}

# Libellés + boutons de transport, par langue.
TRANSPORT_NAME = {
    "fr": {"routier": "Routier", "maritime": "Maritime", "air": "Fret aérien"},
    "en": {"routier": "Road", "maritime": "Sea", "air": "Air freight"},
    "wo": {"routier": "Yoon (auto)", "maritime": "Géej (gaal)", "air": "Ci jaww (avion)"},
    "ar": {"routier": "بري", "maritime": "بحري", "air": "جوي"},
}
_TRANSPORT_EMOJI = {"routier": "🚛", "maritime": "🚢", "air": "✈️"}


def _transport_buttons(lang: str) -> list:
    names = TRANSPORT_NAME.get(lang, TRANSPORT_NAME["fr"])
    return [{"id": "transport_" + k, "label": _TRANSPORT_EMOJI[k] + " " + names[k]} for k in ("routier", "maritime", "air")]


def _wantop_buttons(lang: str) -> list:
    t = FLOW_TXT.get(lang, FLOW_TXT["fr"])
    return [{"id": "op_yes", "label": t["yes"]}, {"id": "op_no", "label": t["no"]}]


def _back_button(lang: str) -> dict:
    return {"id": "goto_menu", "label": FLOW_TXT.get(lang, FLOW_TXT["fr"])["back"]}


# ─── Estimation de prix (MOCK) + références ──────────────────────────────────
_TARIF_BASE = {"routier": 150000, "maritime": 250000, "air": 500000}


def _estimer_prix(origin: str, destination: str, transport: str) -> int:
    base = _TARIF_BASE.get(transport, 150000)
    extra = (abs(hash(((origin or "") + "|" + (destination or "")).lower())) % 6) * 20000
    return base + extra


def _fmt_prix(p: int) -> str:
    return f"{p:,}".replace(",", " ")


def _ref(prefix: str) -> str:
    return f"{prefix}-{random.randint(1000, 9999)}"


# ─── Détection de réclamation (texte libre, multilingue) ─────────────────────
def _norm(t: str) -> str:
    t = (t or "").lower()
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


_COMPLAINT_KW = [
    # français
    "reclamation", "plainte", "probleme", "endommage", "casse", "abime", "perdu",
    "manquant", "pas recu", "jamais recu", "en retard", "remboursement", "rembourser",
    "mecontent", "insatisfait", "inadmissible", "scandale", "arnaque", "je me plains",
    # anglais
    "complaint", "damaged", "broken", "lost", "missing", "not received", "refund",
    "unhappy", "dissatisfied", "unacceptable", "scam", "late delivery",
    # wolof
    "naxtu", "jafe-jafe", "yaqu", "reccu",
    # arabe
    "شكوى", "تالف", "مكسور", "ضائع", "استرداد", "متأخر",
]


def _looks_like_complaint(text: str) -> bool:
    t = _norm(text)
    return any(kw in t for kw in _COMPLAINT_KW)


# Réponse de prise en charge d'une réclamation (transmise à un humain), par langue.
CLAIM_TXT = {
    "fr": ("📝 *Réclamation prise en compte* (réf *{ref}*).\n"
           "Je la transmets immédiatement à un *agent humain* qui vous recontactera "
           "pour la résoudre. Merci de votre patience."),
    "en": ("📝 *Complaint registered* (ref *{ref}*).\n"
           "I'm forwarding it right away to a *human agent* who will get back to you. "
           "Thank you for your patience."),
    "wo": ("📝 *Réclamation jël nañu ko* (réf *{ref}*).\n"
           "Maa ngi koy yónnee ci ab *agent (nit)* bu la di woote ngir ko saafara. "
           "Jërëjëf ci sa muñ."),
    "ar": ("📝 *تم تسجيل الشكوى* (مرجع *{ref}*).\n"
           "سأحوّلها فوراً إلى *موظف بشري* سيتواصل معك لحلّها. شكراً لصبرك."),
}


def _resp(text, buttons, session, **extra):
    r = {"text": text, "buttons": buttons, "state": session.state, "language": session.language}
    r.update(extra)
    return r


def process_interactive_step(
    session_id: str,
    user_input: str,
    action_id: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], UserSession]:
    """Traite une interaction et renvoie (réponse, session). réponse=None => agent IA."""
    session = get_or_create_session(session_id)
    text_clean = (user_input or "").strip().lower()

    # Retour au MENU PRINCIPAL (langue conservée)
    if action_id == "goto_menu" or (session.language and text_clean in ["menu", "retour", "back"]):
        session.state = SessionState.AWAITING_MENU
        session.data = {}
        menu = _menu_for(session.language)
        return _resp(menu["text"], menu["buttons"], session), session

    # RESET complet (revient au choix de langue)
    if text_clean in ["reset", "start", "restart", "0"] or action_id == "menu_reset":
        session.reset()
        return _resp(LANG_CHOICE_PAYLOAD["text"], LANG_CHOICE_PAYLOAD["buttons"], session), session

    # RÉCLAMATION exprimée librement (au menu ou en conversation) -> escalade humaine.
    # (Pas de bouton dédié : l'assistant la détecte, la prend en compte, et la transmet.)
    if (action_id is None and text_clean
            and session.state in (SessionState.AWAITING_MENU, SessionState.AGENT_ACTIVE)
            and _looks_like_complaint(user_input)):
        lang = session.language or "fr"
        ref = _ref("REC")
        session.selected_service = "claim"
        session.state = SessionState.AWAITING_MENU
        return _resp(
            CLAIM_TXT.get(lang, CLAIM_TXT["fr"]).format(ref=ref),
            [_back_button(lang)], session,
            persist=True, intent="claim", reference=ref,
            escalade=True, raison_escalade="réclamation client",
            user_summary="Réclamation : " + (user_input or "").strip()[:100],
        ), session

    # ── ÉTAPE 1 : Langue ──────────────────────────────────────────────────────
    if session.state == SessionState.AWAITING_LANG:
        if not text_clean and not action_id:
            return _resp(LANG_CHOICE_PAYLOAD["text"], LANG_CHOICE_PAYLOAD["buttons"], session), session

        lang = None
        if action_id == "lang_fr" or text_clean in ["1", "fr", "français", "francais"]:
            lang = "fr"
        elif action_id == "lang_wo" or text_clean in ["2", "wo", "wolof"]:
            lang = "wo"
        elif action_id == "lang_en" or text_clean in ["3", "en", "english", "anglais"]:
            lang = "en"
        elif action_id == "lang_ar" or text_clean in ["4", "ar", "arabic", "arabe", "عربي", "العربية"]:
            lang = "ar"

        if lang is None:
            return _resp(
                "Veuillez choisir une langue valide / الرجاء اختيار لغة صحيحة:\n\n" + LANG_CHOICE_PAYLOAD["text"],
                LANG_CHOICE_PAYLOAD["buttons"], session), session

        session.language = lang
        session.state = SessionState.AWAITING_MODE
        confirm = {"fr": "✅ Langue : *Français*", "wo": "✅ Lakk : *Wolof*",
                   "en": "✅ Language: *English*", "ar": "✅ اللغة: *العربية*"}[lang]
        mode = _mode_for(lang)
        return _resp(confirm + "\n\n" + mode["text"], mode["buttons"], session), session

    # ── ÉTAPE 2 : Mode (écrire / appel) ───────────────────────────────────────
    if session.state == SessionState.AWAITING_MODE:
        lang = session.language or "fr"
        if action_id == "mode_write" or text_clean in ["1", "écrire", "ecrire", "write", "bind", "message", "chat", "كتابة"]:
            session.selected_mode = "write"
            session.state = SessionState.AWAITING_MENU
            menu = _menu_for(lang)
            return _resp(menu["text"], menu["buttons"], session), session

        if action_id == "mode_call" or text_clean in ["2", "appel", "appeler", "téléphone", "telephone", "phone", "call", "réceptionniste", "receptionniste", "اتصال"]:
            session.selected_mode = "call"
            call_msg = {
                "fr": "📞 *Réceptionniste TexMiles*\nAppelez-nous au *+221 33 800 00 00* / *+221 77 123 45 67*\n🕒 Lundi–Samedi, 08h–18h.\n\nSouhaitez-vous plutôt écrire un message ?",
                "en": "📞 *TexMiles Receptionist*\nCall us at *+221 33 800 00 00* / *+221 77 123 45 67*\n🕒 Mon–Sat, 8am–6pm.\n\nWould you rather write a message?",
                "wo": "📞 *Réceptionniste TexMiles*\nWoo nu ci *+221 33 800 00 00* / *+221 77 123 45 67*\n🕒 Altine–Gaawu, 08h–18h.\n\nWalla nga bëgg bind ab bataaxal ?",
                "ar": "📞 *استقبال TexMiles*\nاتصل بنا على *+221 33 800 00 00* / *+221 77 123 45 67*\n🕒 الإثنين–السبت، 8ص–6م.\n\nهل تفضل كتابة رسالة؟",
            }[lang]
            write_lbl = {"fr": "💬 Écrire un message", "en": "💬 Write a message",
                         "wo": "💬 Bind ab bataaxal", "ar": "💬 كتابة رسالة"}[lang]
            return _resp(call_msg, [{"id": "mode_write", "label": write_lbl}, _back_button(lang)], session), session

        mode = _mode_for(lang)
        return _resp(mode["text"], mode["buttons"], session), session

    # ── ÉTAPE 3 : Menu principal ──────────────────────────────────────────────
    if session.state == SessionState.AWAITING_MENU:
        lang = session.language or "fr"

        # 1) Suivi d'opération -> agent IA (recherche commande avec vérif. identité)
        if action_id == "service_tracking" or text_clean in ["1", "suivi", "colis", "tracking", "topatu", "تتبع"]:
            session.selected_service = "tracking"
            session.state = SessionState.AGENT_ACTIVE
            ask = {"fr": "📦 *Suivi d'opération*\nDonnez-moi votre numéro de commande (ex : `CMD1002`).",
                   "en": "📦 *Operation tracking*\nPlease give me your order number (e.g. `CMD1002`).",
                   "wo": "📦 *Topatu opération*\nJox ma numéro commande bi (ex: `CMD1002`).",
                   "ar": "📦 *تتبع العملية*\nأدخل رقم الطلب (مثال: `CMD1002`)."}[lang]
            return _resp(ask, [_back_button(lang)], session, service="tracking"), session

        # 2) Demande d'opération -> parcours guidé
        if action_id == "service_operation" or text_clean in ["2", "opération", "operation", "opsiyoŋ", "عملية"]:
            session.selected_service = "operation"
            session.data = {"flow": "operation"}
            session.state = SessionState.COLLECT_ORIGIN
            return _resp(FLOW_TXT[lang]["ask_origin"], [_back_button(lang)], session), session

        # 3) Demande de cotation -> parcours guidé (estimation)
        if action_id == "service_quotation" or text_clean in ["3", "cotation", "devis", "quotation", "njég", "تسعير"]:
            session.selected_service = "quotation"
            session.data = {"flow": "cotation"}
            session.state = SessionState.COLLECT_ORIGIN
            return _resp(FLOW_TXT[lang]["ask_origin"], [_back_button(lang)], session), session

        # Sinon : question libre -> agent IA
        session.selected_service = "general"
        session.state = SessionState.AGENT_ACTIVE
        return None, session

    # ── Parcours guidé : collecte pas à pas ───────────────────────────────────
    lang = session.language or "fr"
    txt = FLOW_TXT[lang]

    if session.state == SessionState.COLLECT_ORIGIN:
        session.data["origin"] = user_input.strip()
        session.state = SessionState.COLLECT_DEST
        return _resp(txt["ask_dest"], [_back_button(lang)], session), session

    if session.state == SessionState.COLLECT_DEST:
        session.data["destination"] = user_input.strip()
        session.state = SessionState.COLLECT_TRANSPORT
        return _resp(txt["ask_transport"], _transport_buttons(lang), session), session

    if session.state == SessionState.COLLECT_TRANSPORT:
        tmap = {"transport_routier": "routier", "transport_maritime": "maritime", "transport_air": "air"}
        tkey = tmap.get(action_id) or {"1": "routier", "2": "maritime", "3": "air"}.get(text_clean)
        if not tkey:
            return _resp(txt["ask_transport"], _transport_buttons(lang), session), session
        session.data["transport"] = tkey

        if session.data.get("flow") == "operation":
            session.state = SessionState.COLLECT_PICKUP
            return _resp(txt["ask_pickup"], [_back_button(lang)], session), session

        # Cotation : on estime le prix, on l'enregistre, puis on propose l'opération.
        ref = _ref("COT")
        price = _estimer_prix(session.data.get("origin"), session.data.get("destination"), tkey)
        session.data["cotation_ref"] = ref
        session.state = SessionState.COT_WANT_OP
        body = txt["cot_estimate"].format(
            origin=session.data.get("origin", ""), destination=session.data.get("destination", ""),
            transport=TRANSPORT_NAME[lang][tkey], price=_fmt_prix(price), ref=ref)
        summary = f"Cotation : {session.data.get('origin')} → {session.data.get('destination')} ({TRANSPORT_NAME['fr'][tkey]})"
        return _resp(body, _wantop_buttons(lang), session,
                     persist=True, intent="quotation", reference=ref, user_summary=summary), session

    if session.state == SessionState.COT_WANT_OP:
        if action_id == "op_yes" or text_clean in ["1", "oui", "yes", "waaw", "نعم"]:
            session.state = SessionState.COLLECT_PICKUP
            return _resp(txt["ask_pickup"], [_back_button(lang)], session), session
        if action_id == "op_no" or text_clean in ["2", "non", "no", "déedéet", "deedeet", "لا"]:
            ref = session.data.get("cotation_ref", "COT")
            session.state = SessionState.AWAITING_MENU
            session.data = {}
            return _resp(txt["cot_saved"].format(ref=ref), [_back_button(lang)], session,
                         persist=True, intent="quotation", reference=ref,
                         user_summary="Cotation enregistrée (sans opération)"), session
        return _resp(txt["cot_estimate"].split("\n\n")[-1], _wantop_buttons(lang), session), session

    if session.state == SessionState.COLLECT_PICKUP:
        session.data["pickup"] = user_input.strip()
        op_ref = _ref("OP")
        d = session.data
        cotation = d.get("cotation_ref", "—")
        body = txt["op_created"].format(
            ref=op_ref, origin=d.get("origin", ""), destination=d.get("destination", ""),
            transport=TRANSPORT_NAME[lang][d.get("transport", "routier")], pickup=d.get("pickup", ""),
            cotation=cotation)
        summary = f"Opération : {d.get('origin')} → {d.get('destination')} ({TRANSPORT_NAME['fr'][d.get('transport','routier')]}), pickup: {d.get('pickup')}"
        session.state = SessionState.AWAITING_MENU
        session.data = {}
        return _resp(body, [_back_button(lang)], session,
                     persist=True, intent="operation", reference=op_ref, user_summary=summary), session

    # ── ÉTAPE 4 : Agent IA (question libre / suivi) ───────────────────────────
    return None, session
