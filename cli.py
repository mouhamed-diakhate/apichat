"""
Petit CLI pour discuter avec l'assistant depuis le terminal.

Lancement (depuis le dossier apichat/) :
    py cli.py

Tapez un message, appuyez sur Entrée, lisez la réponse. 'quitter' pour sortir.
La conversation garde en mémoire les échanges précédents (§4.7 du cahier des charges).
"""

from app.intelligence.config import build_assistant


def main():
    print("=== Assistant Texmiles (démo — commandes fictives) ===")
    print("Tapez votre message. 'quitter' pour sortir.\n")

    try:
        assistant = build_assistant()
    except RuntimeError as e:
        print(f"[Configuration] {e}")
        return

    historique: list[dict] = []

    while True:
        try:
            message = input("Vous > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not message:
            continue
        if message.lower() in {"quitter", "quit", "exit"}:
            break

        reply = assistant.handle(message, historique)
        print(f"Assistant > {reply.texte}")
        if reply.escalade:
            print(f"   [escalade -> humain | raison : {reply.raison_escalade}]")
        if reply.ticket_id:
            print(f"   [réclamation ouverte : {reply.ticket_id}]")
        print()

        # On mémorise le tour pour garder le contexte de la conversation.
        historique.append({"role": "user", "content": message})
        historique.append({"role": "assistant", "content": reply.texte})


if __name__ == "__main__":
    main()
