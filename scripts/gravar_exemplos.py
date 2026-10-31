"""Roda conversas-cenário contra o agente de verdade e grava cada uma em exemplos/*.md.

As transcrições NÃO são editadas depois: o que está nos arquivos é o que o agente respondeu.
Rodar: python scripts/gravar_exemplos.py            (todas)
       python scripts/gravar_exemplos.py 03         (só a que começa com 03)
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from emporio.agente import Agente  # noqa: E402
from emporio.config import FUSO  # noqa: E402

PASTA = Path(__file__).resolve().parent.parent / "exemplos"

# (arquivo, título, descrição do que o cenário testa, falas do cliente)
CENARIOS = [
    (
        "01-catalogo-violoes-ate-1000.md",
        "Catálogo: violões até R$ 1.000",
        "Consulta de catálogo com filtro de preço, seguida de pergunta sobre PIX e parcelamento de um item. Testa buscar_produtos e detalhar_produto, e a regra de PIX e parcelas do manual.",
        [
            "Boa tarde! Quais opções de violões vocês têm custando até R$ 1.000?",
            "O Yamaha C40 me interessou. No PIX sai mais barato? E dá pra parcelar em quantas vezes?",
        ],
    ),
    (
        "02-preco-takamine-e-promocao.md",
        "Preço: Takamine GD20 e um produto em promoção",
        "Consulta de preço de produto específico e de um produto com promoção ativa. Testa a apresentação do preço promocional junto ao original e ao percentual, e a regra de que promoção não acumula com PIX.",
        [
            "Quanto custa o Takamine GD20?",
            "E o Crafter HT-100? Vi que estava em promoção.",
            "Se eu pagar no PIX o Crafter ganho mais 5%?",
        ],
    ),
    (
        "03-pedido-com-confirmacao-de-identidade.md",
        "Pedido: status com confirmação de identidade (LGPD)",
        "O cliente pede o status sem se identificar; o agente deve pedir um contato antes de consultar. Depois, com o e-mail certo, informa o status. Testa consultar_pedido e a barreira de identidade.",
        [
            "Oi, quero saber como está o meu pedido 15.",
            "Meu e-mail é aline.monteiro@jmail.com",
            "Quando chega? Já tem código de rastreio?",
        ],
    ),
    (
        "04-devolucao-por-arrependimento.md",
        "Devolução: direito de arrependimento aplicado a um pedido real",
        "Caso não trivial: o cliente quer devolver; o agente precisa cruzar a política (7 dias corridos após o recebimento) com os dados do pedido (entregue em 25/10/2025) e explicar o que ainda é possível. Testa política + dados na mesma resposta.",
        [
            "Me arrependi da minha compra, posso devolver meu pedido?",
            "É o pedido 1, meu telefone é (67) 98432-1098.",
            "Entendi. E se o violão apresentar algum defeito, o que eu faço?",
        ],
    ),
    (
        "05-fora-de-escopo-e-produto-indisponivel.md",
        "Fora de escopo, produto sem estoque e assunto sem relação",
        "Acessório (a loja não vende), produto ativo mas sem estoque (deve oferecer alternativas) e pergunta sem relação com a loja. Testa o redirecionamento educado e a regra de estoque do manual.",
        [
            "Vocês têm cordas de nylon pra violão?",
            "Tá bom. E o violão Giannini GF-3D Dreadnought Sunburst, tem em estoque?",
            "Valeu! Aproveitando, você sabe me dizer a previsão do tempo pra amanhã em Campo Grande?",
        ],
    ),
]


def gravar(arquivo: str, titulo: str, descricao: str, falas: list[str]) -> None:
    agente = Agente()
    inicio = datetime.now(FUSO)
    blocos = [f"# {titulo}", "", descricao, "", f"Gravado em {inicio.strftime('%d/%m/%Y %H:%M')} (horário de Campo Grande) com o modelo `{agente.modelo}`. Transcrição sem edição.", ""]
    total_in = total_out = 0
    for fala in falas:
        r = agente.responder(fala)
        total_in += r.tokens_entrada
        total_out += r.tokens_saida
        blocos.append(f"**Cliente:** {fala}")
        blocos.append("")
        blocos.append(f"**Agente:** {r.texto}")
        blocos.append("")
        usadas = ", ".join(f"`{f}`" for f in r.ferramentas_usadas) or "nenhuma"
        blocos.append(f"<sub>ferramentas: {usadas}</sub>")
        blocos.append("")
        print(f"  [{arquivo}] {fala[:50]!r} -> {usadas}")
    blocos.append(f"<sub>tokens da conversa: {total_in} de entrada, {total_out} de saída</sub>")
    (PASTA / arquivo).write_text("\n".join(blocos) + "\n", encoding="utf-8")


def main() -> None:
    PASTA.mkdir(exist_ok=True)
    filtro = sys.argv[1] if len(sys.argv) > 1 else ""
    for arquivo, titulo, descricao, falas in CENARIOS:
        if filtro and not arquivo.startswith(filtro):
            continue
        print(f"== {titulo}")
        gravar(arquivo, titulo, descricao, falas)
    print("ok")


if __name__ == "__main__":
    main()
