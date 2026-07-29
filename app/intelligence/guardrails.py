"""
Garde-fous "filet de sécurité" appliqués dans le code.

L'escalade vers un humain est d'abord gérée intelligemment par le modèle (il a un
outil escalate_to_human). Mais pour deux cas critiques et faciles à détecter — le
client en colère et la demande explicite d'un humain — on ajoute une détection par
mots-clés côté code. Ainsi, même si le modèle "rate" le signal, l'escalade se
déclenche quand même. C'est une exigence de fiabilité, pas une optimisation.
"""

import unicodedata


def _normaliser(texte: str) -> str:
    texte = texte.lower()
    texte = unicodedata.normalize("NFD", texte)
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


# Le client demande explicitement un humain.
_DEMANDE_HUMAIN = [
    # Français
    "parler a un humain", "parler a quelqu un", "un humain", "un vrai agent",
    "un agent", "un conseiller", "une personne", "quelqu un de reel",
    "service client humain", "un operateur", "un vrai gens", "un responsable",
    "un chef", "passez moi quelqu un", "je veux un humain",
    # English
    "speak to a human", "talk to a human", "real person", "human agent",
    "speak to a representative", "customer service agent", "real agent",
    # Wolof
    "bëgg na waxtaan ak nit", "wooko ma nit", "jox ma responsable",
    "jox ma borom", "dinaa waxtaan ak nit dëgg", "woxal ma ak nit",
]

# Signes de forte insatisfaction / colère.
_COLERE = [
    # Français
    "inadmissible", "inacceptable", "scandale", "scandaleux", "honteux", "honte",
    "j en ai marre", "marre", "furieux", "en colere", "arnaque", "arnaqueur",
    "vous vous moquez", "nul", "lamentable", "c est une blague", "voleurs",
    "porter plainte", "avocat", "toujours rien", "service mediocre",
    "remboursez moi", "remboursement immediat", "trop long", "ras le bol",
    # English
    "unacceptable", "scam", "scammers", "ridiculous", "refund my money",
    "terrible service", "horrible", "angry", "furious", "disgusted",
    # Wolof
    "mer na", "jaaxle na", "dara doxul", "amul benn yoon", "du yoon",
    "fen ngen", "bëgguma lii", "ay voleur ngen", "sàcc ngen",
]


def escalade_forcee(message: str) -> str | None:
    """
    Regarde le message du client. Renvoie une raison d'escalade si un signal fort
    est détecté, sinon None.
    """
    t = _normaliser(message)
    for motif in _DEMANDE_HUMAIN:
        if motif in t:
            return "demande explicite de parler à un humain"
    for motif in _COLERE:
        if motif in t:
            return "insatisfaction forte / colère détectée"
    return None

