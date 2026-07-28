"""
L'orchestrateur : le "cerveau" qui coordonne tout.

Pour chaque message client, il :
  1. envoie le message + les consignes + les outils au modèle,
  2. exécute les outils que le modèle demande (recherche commande, FAQ, réclamation,
     escalade),
  3. applique les garde-fous côté code (identité, filet d'escalade),
  4. renvoie une réponse en français + des indicateurs (escaladé ? ticket créé ?).

Il ne dépend que de l'interface LLMProvider : on peut donc brancher n'importe quel
modèle derrière, sans rien changer ici.
"""

import json
from dataclasses import dataclass, field

from .providers.base import LLMProvider, ToolCall
from .orders import OrderSource
from .faq import FaqBase
from .guardrails import escalade_forcee
from .prompt_fr import SYSTEM_PROMPT_FR
from .prompt_wo import SYSTEM_PROMPT_WO
from .prompt_en import SYSTEM_PROMPT_EN
from .prompt_ar import SYSTEM_PROMPT_AR


# --- Description des outils, au format attendu par l'API (style OpenAI) ---------
OUTILS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_order",
            "description": "Retrouver une commande et son statut à partir d'un numéro de commande, d'un téléphone ou d'un email. À utiliser dès que le client parle d'une commande précise.",
            "parameters": {
                "type": "object",
                "properties": {
                    "numero": {"type": "string", "description": "Numéro de commande, ex. CMD1002"},
                    "telephone": {"type": "string", "description": "Téléphone du client"},
                    "email": {"type": "string", "description": "Email du client"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_faq",
            "description": "Chercher une réponse dans la base FAQ (horaires, délais, zones de livraison, retours, frais, moyens de paiement).",
            "parameters": {
                "type": "object",
                "properties": {
                    "requete": {"type": "string", "description": "La question du client, reformulée"},
                },
                "required": ["requete"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_quotation",
            "description": "Générer un devis estimatif de cotation d'expédition.",
            "parameters": {
                "type": "object",
                "properties": {
                    "origine": {"type": "string", "description": "Lieu de départ / origine"},
                    "destination": {"type": "string", "description": "Lieu d'arrivée / destination"},
                    "poids": {"type": "string", "description": "Poids ou dimensions du colis"},
                    "type_marchandise": {"type": "string", "description": "Nature de la marchandise"},
                },
                "required": ["origine", "destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_operation",
            "description": "Enregistrer une demande d'opération logistique (enlèvement, livraison spécifique, stockage/entreposage).",
            "parameters": {
                "type": "object",
                "properties": {
                    "type_operation": {"type": "string", "description": "Type d'opération : enlèvement, livraison, entreposage"},
                    "adresse": {"type": "string", "description": "Adresse concernée"},
                    "instructions": {"type": "string", "description": "Instructions ou détails spécifiques"},
                },
                "required": ["type_operation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_complaint",
            "description": "Ouvrir une réclamation (colis endommagé, manquant, retard important, erreur). Renvoie un numéro de ticket.",
            "parameters": {
                "type": "object",
                "properties": {
                    "numero": {"type": "string", "description": "Numéro de commande concernée, si connu"},
                    "description": {"type": "string", "description": "Description du problème signalé"},
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": "Transférer la conversation à un agent humain (colère, demande explicite d'un humain, hors périmètre, échec après tentatives).",
            "parameters": {
                "type": "object",
                "properties": {
                    "raison": {"type": "string", "description": "Pourquoi on escalade"},
                },
                "required": ["raison"],
            },
        },
    },
]

# Message de repli si le modèle/API est indisponible (cahier des charges §4.11).
MESSAGE_REPLI = (
    "Je rencontre un problème technique temporaire et je ne peux pas traiter votre "
    "demande à l'instant. Vous pouvez réessayer dans quelques minutes, ou je peux vous "
    "orienter vers un agent humain."
)


@dataclass
class AssistantReply:
    """Résultat structuré d'un tour de conversation."""
    texte: str
    escalade: bool = False
    raison_escalade: str = ""
    ticket_id: str = ""
    outils_utilises: list[str] = field(default_factory=list)


class Assistant:
    def __init__(self, provider: LLMProvider, orders: OrderSource, faq: FaqBase):
        self.provider = provider
        self.orders = orders
        self.faq = faq
        self._compteur_tickets = 0  # pour générer des numéros de ticket lisibles
        self._compteur_devis = 0
        self._compteur_ops = 0

    def handle(self, message: str, historique: list[dict] | None = None, language: str = "fr") -> AssistantReply:
        """Traite un message client et renvoie la réponse de l'assistant."""
        historique = historique or []
        messages = historique + [{"role": "user", "content": message}]

        reply = AssistantReply(texte="")
        if language == "wo":
            system_prompt = SYSTEM_PROMPT_WO
        elif language == "en":
            system_prompt = SYSTEM_PROMPT_EN
        elif language == "ar":
            system_prompt = SYSTEM_PROMPT_AR
        else:
            system_prompt = SYSTEM_PROMPT_FR

        # Filet de sécurité côté code : colère / demande explicite d'humain.
        raison = escalade_forcee(message)
        if raison:
            reply.escalade = True
            reply.raison_escalade = raison

        try:
            # Boucle outils : le modèle peut demander plusieurs outils avant de répondre.
            for _ in range(5):  # garde-fou anti-boucle infinie
                resp = self.provider.chat(system_prompt, messages, OUTILS)

                if not resp.tool_calls:
                    reply.texte = resp.text.strip()
                    break

                # On rejoue le tour "assistant" (avec ses demandes d'outils)...
                messages.append({
                    "role": "assistant",
                    "content": resp.text,
                    "tool_calls": resp.tool_calls,
                })
                # ...puis on exécute chaque outil et on renvoie le résultat au modèle.
                for tc in resp.tool_calls:
                    resultat = self._executer_outil(tc, reply)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "content": resultat,
                    })
            else:
                # On a atteint la limite de tours sans réponse texte finale.
                if not reply.texte:
                    reply.texte = MESSAGE_REPLI
        except Exception as e:  # noqa: BLE001 — on veut un repli pour TOUTE panne API
            # Continuité de service : jamais d'erreur technique brute au client.
            print(f"[repli] Erreur fournisseur : {e}")
            reply.texte = MESSAGE_REPLI
            reply.escalade = True
            if not reply.raison_escalade:
                reply.raison_escalade = "indisponibilité technique"

        return reply

    # --- Exécution des outils demandés par le modèle -----------------------------
    def _executer_outil(self, tc: ToolCall, reply: AssistantReply) -> str:
        reply.outils_utilises.append(tc.name)

        if tc.name == "lookup_order":
            res = self.orders.find(
                numero=tc.arguments.get("numero"),
                telephone=tc.arguments.get("telephone"),
                email=tc.arguments.get("email"),
            )
            if res["resultat"] == "ok":
                c = res["commande"]
                return json.dumps({
                    "resultat": "ok",
                    "numero": c["numero"],
                    "statut": c["statut"],
                    "date_estimee": c["date_estimee"],
                }, ensure_ascii=False)
            if res["resultat"] == "incoherence":
                # Prudence : on escalade et on interdit la divulgation.
                reply.escalade = True
                reply.raison_escalade = reply.raison_escalade or "incohérence d'identité"
                return json.dumps({
                    "resultat": "incoherence",
                    "consigne": "Ne divulgue AUCUN détail. Reste prudent et propose un agent humain.",
                }, ensure_ascii=False)
            return json.dumps({"resultat": res["resultat"]}, ensure_ascii=False)

        if tc.name == "search_faq":
            matches = self.faq.search(tc.arguments.get("requete", ""))
            return json.dumps({"resultats": matches}, ensure_ascii=False)

        if tc.name == "create_quotation":
            self._compteur_devis += 1
            devis_id = f"COT-{self._compteur_devis:04d}"
            reply.ticket_id = devis_id
            return json.dumps({
                "cotation_id": devis_id,
                "statut": "devis_généré",
                "estimation_tarif": "15 000 FCFA (tarif estimatif)",
                "delai_livraison": "24 à 48 heures",
                "consigne": "Présente cette estimation au client avec le numéro de référence du devis."
            }, ensure_ascii=False)

        if tc.name == "create_operation":
            self._compteur_ops += 1
            op_id = f"OPS-{self._compteur_ops:04d}"
            reply.ticket_id = op_id
            return json.dumps({
                "operation_id": op_id,
                "statut": "demande_enregistrée",
                "consigne": "Confirme au client que la demande d'opération est prise en compte et qu'un agent logistique le contactera."
            }, ensure_ascii=False)

        if tc.name == "create_complaint":
            self._compteur_tickets += 1
            ticket = f"REC-{self._compteur_tickets:04d}"
            reply.ticket_id = ticket
            reply.escalade = True  # transmise à l'équipe réclamations (traitement humain)
            reply.raison_escalade = reply.raison_escalade or "réclamation ouverte"
            return json.dumps({
                "ticket_id": ticket,
                "statut": "enregistrée",
                "delai_indicatif": "48 heures",
            }, ensure_ascii=False)

        if tc.name == "escalate_to_human":
            reply.escalade = True
            reply.raison_escalade = tc.arguments.get("raison") or reply.raison_escalade or "escalade demandée"
            return json.dumps({"statut": "escalade enregistrée"}, ensure_ascii=False)

        return json.dumps({"erreur": f"outil inconnu: {tc.name}"}, ensure_ascii=False)
