"""Interface de linha de comando: conversa interativa ou uma mensagem só.

  python -m emporio                      conversa interativa
  python -m emporio -m "Qual o endereço?" uma pergunta e sai
  python -m emporio --salvar conversas/x.md   grava a transcrição ao sair
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import anthropic

from .agente import Agente
from .config import LOJA, MODELO


def salvar_transcricao(agente: Agente, caminho: Path, titulo: str = "") -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    linhas = [f"# {titulo or 'Conversa com o agente da ' + LOJA['nome']}", "", f"Modelo: `{agente.modelo}`", ""]
    for quem, texto in agente.transcricao():
        linhas.append(f"**{quem}:** {texto}")
        linhas.append("")
    caminho.write_text("\n".join(linhas), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    # Windows: garante acentuação correta no terminal (inclusive no --help).
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(prog="emporio", description=f"Agente de atendimento da {LOJA['nome']}")
    parser.add_argument("-m", "--mensagem", help="responde uma única mensagem e encerra")
    parser.add_argument("--salvar", type=Path, help="arquivo .md para gravar a transcrição ao final")
    parser.add_argument("--modelo", default=MODELO, help=f"modelo da Anthropic (padrão: {MODELO})")
    parser.add_argument("--debug", action="store_true", help="mostra ferramentas chamadas e tokens por resposta")
    args = parser.parse_args(argv)

    cliente = anthropic.Anthropic()
    if not (cliente.api_key or cliente.auth_token or getattr(cliente, "credentials", None)):
        print("Nenhuma credencial encontrada. Defina ANTHROPIC_API_KEY no arquivo .env (veja .env.example).", file=sys.stderr)
        return 2
    agente = Agente(cliente=cliente, modelo=args.modelo)

    def falar(texto: str) -> None:
        try:
            r = agente.responder(texto)
        except anthropic.AuthenticationError:
            print("Chave da API inválida ou ausente. Confira ANTHROPIC_API_KEY no .env.", file=sys.stderr)
            raise SystemExit(2)
        except anthropic.RateLimitError:
            print("Limite de requisições atingido. Aguarde um instante e tente de novo.", file=sys.stderr)
            return
        except anthropic.APIStatusError as e:
            print(f"Erro da API ({e.status_code}): {e.message}", file=sys.stderr)
            return
        except anthropic.APIConnectionError:
            print("Sem conexão com a API. Verifique a internet.", file=sys.stderr)
            return
        print(f"\nAgente: {r.texto}\n")
        if args.debug:
            print(f"  [ferramentas: {', '.join(r.ferramentas_usadas) or 'nenhuma'} | tokens: {r.tokens_entrada} entrada, {r.tokens_saida} saída]\n")

    if args.mensagem:
        falar(args.mensagem)
    else:
        print(f"{LOJA['nome']} · assistente virtual ({agente.modelo}). Digite sua mensagem; 'sair' encerra.\n")
        while True:
            try:
                texto = input("Você: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not texto:
                continue
            if texto.lower() in {"sair", "exit", "quit", "/sair"}:
                break
            falar(texto)

    if args.salvar and agente.historico:
        salvar_transcricao(agente, args.salvar)
        print(f"Transcrição salva em {args.salvar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
