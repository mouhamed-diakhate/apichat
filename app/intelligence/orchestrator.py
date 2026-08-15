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
from .prompt_fr import SYSTEM_PROMPT_FR, SYSTEM_PROMPT_FR_VARIANTS
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
            "description": "Interroger la base de connaissances TexMiles (FAQ et documents internes citables : CGV, politiques, procédures, horaires, délais, zones, retours, frais et paiement). À utiliser avant toute réponse fondée sur une politique ou un document.",
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
            "description": "Générer un devis estimatif complet de cotation d'expédition.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lieu_expedition": {"type": "string", "description": "Lieu d'expédition / ville ou pays de départ"},
                    "lieu_destination": {"type": "string", "description": "Lieu de destination / ville ou pays d'arrivée"},
                    "expediteur_nom": {"type": "string", "description": "Nom complet de l'expéditeur"},
                    "expediteur_entreprise": {"type": "string", "description": "Nom de l'entreprise (facultatif)"},
                    "expediteur_telephone": {"type": "string", "description": "Numéro de téléphone de l'expéditeur"},
                    "expediteur_email": {"type": "string", "description": "Adresse email de l'expéditeur"},
                    "nature_marchandise": {"type": "string", "description": "Nature de la marchandise"},
                    "colis_designation": {"type": "string", "description": "Désignation / description du colis"},
                    "colis_poids": {"type": "string", "description": "Poids du colis (ex: 15 kg)"},
                    "colis_valeur": {"type": "string", "description": "Valeur déclarée du colis (ex: 500 000)"},
                    "colis_devise": {"type": "string", "description": "Devise de la valeur (FCFA, EUR, USD...)"},
                    "colis_volume": {"type": "string", "description": "Volume ou dimensions du colis (ex: 0.5 m3)"},
                    "message_complementaire": {"type": "string", "description": "Message ou précisions complémentaires (facultatif)"},
                },
                "required": ["lieu_expedition", "lieu_destination", "nature_marchandise"],
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
            "description": "Ouvrir une réclamation client officielle pour un colis endommagé, perdu, très en retard ou non conforme.",
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
    # Sources réellement récupérées côté serveur. Elles sont indépendantes du texte
    # généré par le modèle pour empêcher les citations inventées.
    sources: list[dict] = field(default_factory=list)
    prompt_variant: str = "A"


class Assistant:
    def __init__(self, provider: LLMProvider, orders: OrderSource, faq: FaqBase):
        self.provider = provider
        self.orders = orders
        self.faq = faq
        self._compteur_tickets = 0  # pour générer des numéros de ticket lisibles
        self._compteur_devis = 0
        self._compteur_ops = 0

    def handle(
        self,
        message: str,
        historique: list[dict] | None = None,
        language: str = "fr",
        session_id: str | None = None,
    ) -> AssistantReply:
        """Traite un message client et renvoie la réponse de l'assistant."""
        historique = historique or []
        messages = historique + [{"role": "user", "content": message}]

        reply = AssistantReply(texte="")
        if language == "wo":
            system_prompt = SYSTEM_PROMPT_WO
            variant = "A"
        elif language == "en":
            system_prompt = SYSTEM_PROMPT_EN
            variant = "A"
        elif language == "ar":
            system_prompt = SYSTEM_PROMPT_AR
            variant = "A"
        else:
            # A/B Testing pour le français : alternance déterministe basée sur le session_id
            if session_id:
                variant = "B" if (sum(ord(c) for c in session_id) % 2 == 1) else "A"
            else:
                variant = "A"
            system_prompt = SYSTEM_PROMPT_FR_VARIANTS.get(variant, SYSTEM_PROMPT_FR)

        reply.prompt_variant = variant

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

        if reply.texte and reply.texte != MESSAGE_REPLI:
            self._append_source_footer(reply)
        return reply

    def _register_sources(self, reply: AssistantReply, matches: list[dict]) -> list[dict]:
        """Associe les passages récupérés à la réponse avec des références stables.

        Le LLM ne reçoit que des marqueurs ``[S1]``/``[S2]`` provenant du serveur.
        Il ne peut donc pas choisir lui-même une page ou un document à citer.
        """
        known_ids = {source.get("id") for source in reply.sources}
        tool_results: list[dict] = []

        for match in matches:
            chunk_id = str(match.get("id") or "")
            source = dict(match.get("source") or {})
            if not chunk_id or not source:
                continue

            existing = next((item for item in reply.sources if item.get("id") == chunk_id), None)
            if existing is None:
                if chunk_id in known_ids:
                    continue
                marker = f"S{len(reply.sources) + 1}"
                existing = {
                    "id": chunk_id,
                    "marker": marker,
                    "citation": match.get("citation") or source.get("title") or "Source interne",
                    "document": source.get("title") or source.get("filename") or "Document interne",
                    "filename": source.get("filename"),
                    "page": source.get("page"),
                    "section": source.get("section"),
                    "score": match.get("score"),
                }
                reply.sources.append(existing)
                known_ids.add(chunk_id)

            tool_results.append(
                {
                    "source_id": existing["marker"],
                    "citation": existing["citation"],
                    "score": match.get("score"),
                    "contenu": match.get("reponse", ""),
                }
            )
        return tool_results

    @staticmethod
    def _append_source_footer(reply: AssistantReply) -> None:
        """Ajoute les citations à la réponse, même si le modèle oublie de le faire."""
        if not reply.sources:
            return
        citations = "\n".join(
            f"- [{source['marker']}] {source['citation']}"
            for source in reply.sources
        )
        reply.texte = f"{reply.texte.rstrip()}\n\nSources vérifiées :\n{citations}"

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
            # Un passage source précis est préférable à une liste de contextes
            # partiellement pertinents : la citation finale reste ainsi exacte.
            matches = self.faq.search(tc.arguments.get("requete", ""), limite=1)
            results = self._register_sources(reply, matches)
            if not results:
                return json.dumps(
                    {
                        "resultats": [],
                        "consigne": (
                            "Aucune source fiable n'a été trouvée dans la base de connaissances. "
                            "N'invente pas de règle ni de politique ; indique cette limite et propose un agent humain si nécessaire."
                        ),
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                {
                    "resultats": results,
                    "consigne": (
                        "Réponds uniquement à partir des extraits ci-dessus. Tu peux référencer les marqueurs "
                        "[S1], [S2], etc. Les citations vérifiées seront ajoutées automatiquement à la réponse."
                    ),
                },
                ensure_ascii=False,
            )

        if tc.name == "create_quotation":
            self._compteur_devis += 1
            devis_id = f"COT-{self._compteur_devis:04d}"
            reply.ticket_id = devis_id
            args = tc.arguments or {}
            lieu_exp = args.get("lieu_expedition") or args.get("origine") or "Non précisé"
            lieu_dest = args.get("lieu_destination") or args.get("destination") or "Non précisé"
            nom_exp = args.get("expediteur_nom") or "Non précisé"
            entreprise = args.get("expediteur_entreprise") or "N/A"
            tel = args.get("expediteur_telephone") or "Non précisé"
            email = args.get("expediteur_email") or "Non précisé"
            nature = args.get("nature_marchandise") or "Générale"
            designation = args.get("colis_designation") or "Colis marchandise"
            poids = args.get("colis_poids") or "Non précisé"
            valeur = args.get("colis_valeur") or "Non précisée"
            devise = args.get("colis_devise") or "FCFA"
            volume = args.get("colis_volume") or "Non précisé"
            msg_comp = args.get("message_complementaire") or ""

            return json.dumps({
                "cotation_id": devis_id,
                "statut": "devis_généré",
                "lieu_expedition": lieu_exp,
                "lieu_destination": lieu_dest,
                "expediteur_nom": nom_exp,
                "expediteur_entreprise": entreprise,
                "expediteur_telephone": tel,
                "expediteur_email": email,
                "nature_marchandise": nature,
                "colis": {
                    "designation": designation,
                    "poids": poids,
                    "valeur": f"{valeur} {devise}",
                    "volume": volume,
                },
                "message_complementaire": msg_comp,
                "estimation_tarif": f"Tarif estimatif sur devis {devis_id}",
                "delai_livraison": "24 à 48 heures (indicatif)",
                "consigne": (
                    f"Présente ce récapitulatif complet de cotation au client avec la référence {devis_id}. "
                    "Confirme-lui que l'équipe commerciale TexMiles étudiera les détails de son expédition et le recontactera rapidement."
                )
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
