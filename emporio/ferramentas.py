"""Ferramentas que o modelo pode chamar (function calling).

Cada ferramenta é uma função pura sobre a BaseDeDados que devolve um dicionário
serializável. As regras de negócio do manual (PIX, parcelamento, promoção não
cumulativa, LGPD no pedido) ficam aqui, em código, e não no prompt: o modelo
decide *quando* consultar; o cálculo é determinístico.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from .config import DESCONTO_PIX, FUSO, HORARIO, LOJA
from .dados import BaseDeDados, Produto, normalizar

STATUS_PRODUTO = {
    "active": "ativo",
    "discontinued": "descontinuado",
    "coming_soon": "em breve",
}

STATUS_PEDIDO = {
    "pending": "pendente (aguardando confirmação do pagamento)",
    "confirmed": "confirmado (em preparação para envio)",
    "shipped": "enviado",
    "delivered": "entregue",
    "cancelled": "cancelado",
}

PAGAMENTO = {
    "pix": "PIX",
    "boleto": "boleto bancário",
    "debit": "cartão de débito",
    "credit_3x": "cartão de crédito em 3x",
    "credit_6x": "cartão de crédito em 6x",
    "credit_12x": "cartão de crédito em 12x",
}

DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def brl(valor: float) -> str:
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------- regras de preço (manual, seções 3 e 6) ----------


def parcelamento_maximo(valor: float) -> int:
    """Maior número de parcelas sem juros permitido para o valor (seção 3.1)."""
    for n in range(12, 0, -1):
        parcela = valor / n
        if n >= 7 and parcela >= 100:
            return n
        if 4 <= n <= 6 and parcela >= 80:
            return n
        if n <= 3 and (n == 1 or valor >= 50):
            return n
    return 1


def condicoes_de_preco(db: BaseDeDados, p: Produto) -> dict[str, Any]:
    promo = db.promocao_ativa(p.id)
    if promo:
        preco_final = round(p.preco * (1 - promo.desconto_percent / 100), 2)
        pix = preco_final  # desconto de PIX não se aplica sobre preço promocional (6.2)
        pix_nota = "promoção não acumula com o desconto de PIX"
    else:
        preco_final = p.preco
        pix = round(p.preco * (1 - DESCONTO_PIX), 2)
        pix_nota = "5% de desconto no PIX"
    n = parcelamento_maximo(preco_final)
    return {
        "preco_tabela": brl(p.preco),
        "promocao": (
            {"descricao": promo.descricao, "desconto_percent": promo.desconto_percent, "preco_promocional": brl(preco_final)}
            if promo
            else None
        ),
        "preco_pix": brl(pix),
        "pix_nota": pix_nota,
        "parcelamento": f"até {n}x sem juros de {brl(preco_final / n)}" if n > 1 else "à vista",
    }


def disponibilidade(p: Produto) -> str:
    if p.status == "discontinued":
        return "descontinuado (não faz mais parte do catálogo)"
    if p.status == "coming_soon":
        return "em breve (ainda não disponível para venda)"
    if p.estoque <= 0:
        return "temporariamente indisponível (sem estoque)"
    if p.estoque <= 3:
        return f"disponível, últimas {p.estoque} unidades"
    return f"disponível ({p.estoque} em estoque)"


def _resumo(db: BaseDeDados, p: Produto) -> dict[str, Any]:
    return {
        "id": p.id,
        "nome": p.nome,
        "categoria": db.categorias[p.categoria_id].nome,
        "disponibilidade": disponibilidade(p),
        **condicoes_de_preco(db, p),
    }


# ---------- ferramentas ----------


def buscar_produtos(
    db: BaseDeDados,
    termo: str = "",
    categoria: str = "",
    preco_max: float | None = None,
    incluir_indisponiveis: bool = False,
    limite: int = 10,
) -> dict[str, Any]:
    cat = db.categoria_por_nome(categoria) if categoria else None
    if categoria and not cat:
        return {"erro": f"Categoria '{categoria}' não encontrada.", "categorias_existentes": [c.nome for c in db.categorias.values()]}
    palavras = normalizar(termo).split()
    encontrados: list[Produto] = []
    for p in db.produtos.values():
        if cat and p.categoria_id != cat.id:
            continue
        texto = normalizar(" ".join([p.nome, p.descricao, db.categorias[p.categoria_id].nome, " ".join(map(str, p.specs.values()))]))
        if palavras and not all(w in texto for w in palavras):
            continue
        encontrados.append(p)

    def preco_efetivo(p: Produto) -> float:
        promo = db.promocao_ativa(p.id)
        return round(p.preco * (1 - promo.desconto_percent / 100), 2) if promo else p.preco

    if preco_max is not None:
        encontrados = [p for p in encontrados if preco_efetivo(p) <= preco_max]
    disponiveis = [p for p in encontrados if p.status == "active" and p.estoque > 0]
    ocultos = [p for p in encontrados if p not in disponiveis]
    lista = encontrados if incluir_indisponiveis else disponiveis
    lista.sort(key=preco_efetivo)
    return {
        "total_encontrado": len(encontrados),
        "exibidos": len(lista[:limite]),
        "produtos": [_resumo(db, p) for p in lista[:limite]],
        "ocultos_por_indisponibilidade": [f"{p.nome} ({disponibilidade(p)})" for p in ocultos] if not incluir_indisponiveis else [],
        "observacao": "Preços de tabela; preço promocional e PIX já calculados por item. Promoção não acumula com PIX.",
    }


def detalhar_produto(db: BaseDeDados, nome_ou_id: str) -> dict[str, Any]:
    p: Produto | None = None
    if str(nome_ou_id).strip().isdigit():
        p = db.produtos.get(int(nome_ou_id))
    if p is None:
        alvo = normalizar(str(nome_ou_id))
        candidatos = [q for q in db.produtos.values() if alvo and alvo in normalizar(q.nome)]
        if not candidatos:
            palavras = alvo.split()
            candidatos = [q for q in db.produtos.values() if palavras and all(w in normalizar(q.nome) for w in palavras)]
        if len(candidatos) > 1:
            return {"ambiguo": True, "opcoes": [f"{q.id}: {q.nome}" for q in candidatos[:8]]}
        p = candidatos[0] if candidatos else None
    if p is None:
        return {"erro": f"Produto '{nome_ou_id}' não encontrado no catálogo."}
    cat = db.categorias[p.categoria_id]
    detalhe = {
        **_resumo(db, p),
        "descricao": p.descricao,
        "especificacoes": p.specs,
        "status": STATUS_PRODUTO.get(p.status, p.status),
        "estoque": p.estoque,
    }
    if p.status != "active" or p.estoque <= 0:
        similares = [
            q for q in db.produtos.values()
            if q.id != p.id and q.categoria_id == cat.id and q.status == "active" and q.estoque > 0
        ]
        similares.sort(key=lambda q: abs(q.preco - p.preco))
        detalhe["alternativas_disponiveis"] = [_resumo(db, q) for q in similares[:3]]
    return detalhe


def listar_promocoes_ativas(db: BaseDeDados) -> dict[str, Any]:
    ativas = []
    for promo in db.promocoes:
        if not promo.ativa:
            continue
        p = db.produtos.get(promo.produto_id)
        if not p:
            continue
        ativas.append({**_resumo(db, p), "campanha": promo.descricao})
    return {"promocoes_ativas": ativas, "total": len(ativas), "observacao": "Só promoções marcadas como ativas no sistema. Promoções encerradas não devem ser prometidas."}


def consultar_pedido(db: BaseDeDados, numero_pedido: int | str, contato_cliente: str) -> dict[str, Any]:
    """Status de um pedido. Exige telefone ou e-mail do cliente dono do pedido (LGPD, seção 9)."""
    try:
        pid = int(str(numero_pedido).strip().lstrip("#"))
    except ValueError:
        return {"erro": "Número de pedido inválido."}
    pedido = db.pedidos.get(pid)
    if not pedido:
        return {"erro": f"Pedido {pid} não encontrado."}
    cliente = db.cliente_por_contato(contato_cliente)
    if not cliente or cliente.id != pedido.cliente_id:
        return {
            "erro": "Não foi possível confirmar a identidade: o telefone ou e-mail informado não corresponde ao cliente deste pedido.",
            "orientacao": "Peça ao cliente o telefone ou e-mail cadastrado na compra. Não revele dados do pedido sem essa confirmação.",
        }
    itens = []
    for i in db.itens_do_pedido(pid):
        p = db.produtos.get(i.produto_id)
        itens.append({"produto": p.nome if p else f"produto {i.produto_id}", "quantidade": i.quantidade, "preco_unitario": brl(p.preco) if p else None})
    return {
        "pedido": pid,
        "cliente": cliente.nome.split()[0],
        "cidade": cliente.cidade,
        "data_pedido": pedido.data,
        "status": STATUS_PEDIDO.get(pedido.status, pedido.status),
        "status_codigo": pedido.status,
        "total": brl(pedido.total),
        "pagamento": PAGAMENTO.get(pedido.pagamento, pedido.pagamento),
        "codigo_rastreio": pedido.rastreio or None,
        "previsao_entrega": pedido.previsao_entrega or None,
        "observacoes": pedido.observacoes or None,
        "itens": itens,
    }


def situacao_atendimento(agora: datetime | None = None) -> dict[str, Any]:
    """Se a loja está aberta agora e quando volta a atender (seção 2)."""
    agora = agora or datetime.now(FUSO)
    dia = agora.isoweekday()
    janela = HORARIO.get(dia)
    aberta = False
    if janela:
        abre, fecha = (datetime.strptime(h, "%H:%M").time() for h in janela)
        aberta = abre <= agora.time() < fecha
    proximo = None
    if not aberta:
        for passo in range(0, 8):
            d = ((dia - 1 + passo) % 7) + 1
            j = HORARIO.get(d)
            if not j:
                continue
            if passo == 0 and agora.time() >= datetime.strptime(j[1], "%H:%M").time():
                continue
            proximo = f"{DIAS[d - 1]} às {j[0]}"
            break
    return {
        "agora": agora.strftime("%d/%m/%Y %H:%M") + f" ({DIAS[dia - 1]})",
        "loja_aberta": aberta,
        "horario_hoje": f"{janela[0]} às {janela[1]}" if janela else "fechado",
        "proxima_abertura": None if aberta else proximo,
        "horarios": {"segunda a sexta": "09:00 às 18:00", "sábado": "09:00 às 13:00", "domingo e feriados": "fechado"},
        "contato": LOJA,
    }


# ---------- registro das ferramentas para o modelo ----------

DEFINICOES: list[dict[str, Any]] = [
    {
        "name": "buscar_produtos",
        "description": (
            "Busca instrumentos no catálogo por termo (nome, marca, descrição, especificação), categoria e preço máximo. "
            "Devolve preço de tabela, promoção ativa, preço no PIX e parcelamento de cada item. "
            "Por padrão só lista itens disponíveis em estoque; os indisponíveis vêm listados à parte. "
            "Use SEMPRE antes de falar de preço, estoque ou opções de produto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "termo": {"type": "string", "description": "Palavras para procurar (ex.: 'violão nylon', 'yamaha', 'ukulele tenor'). Pode ficar vazio."},
                "categoria": {"type": "string", "description": "Categoria: Guitarras, Baixos, Baterias e Percussão, Teclados e Pianos, Violões, Ukuleles, etc. Opcional."},
                "preco_max": {"type": "number", "description": "Preço máximo em reais, já considerando promoção ativa. Opcional."},
                "incluir_indisponiveis": {"type": "boolean", "description": "Se true, inclui produtos sem estoque, descontinuados ou em breve na lista."},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "detalhar_produto",
        "description": (
            "Detalhes completos de um produto pelo nome (ou parte dele) ou pelo id: descrição, especificações, estoque, status, "
            "promoção ativa, preço no PIX e parcelamento. Se estiver indisponível ou descontinuado, traz alternativas disponíveis."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"nome_ou_id": {"type": "string", "description": "Nome (ex.: 'Takamine GD20') ou id numérico do produto."}},
            "required": ["nome_ou_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "listar_promocoes_ativas",
        "description": "Lista as promoções ativas no momento, com preço original, percentual e preço promocional. Use quando o cliente perguntar por ofertas, descontos ou campanhas.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "consultar_pedido",
        "description": (
            "Status, rastreio, previsão de entrega e itens de um pedido. Por LGPD, exige o número do pedido E o telefone ou e-mail "
            "cadastrado do cliente; se não bater, a ferramenta recusa. Peça esses dados ao cliente antes de chamar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "numero_pedido": {"type": "string", "description": "Número do pedido informado pelo cliente."},
                "contato_cliente": {"type": "string", "description": "Telefone ou e-mail que o cliente informou."},
            },
            "required": ["numero_pedido", "contato_cliente"],
            "additionalProperties": False,
        },
    },
    {
        "name": "situacao_atendimento",
        "description": "Diz se a loja está aberta agora (fuso de Campo Grande), o horário de hoje, quando reabre e os contatos. Use para perguntas de horário e para avisar o retorno fora do expediente.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


def executor(db: BaseDeDados) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    """Devolve a função que despacha uma chamada do modelo para a ferramenta certa."""

    def executar(nome: str, entrada: dict[str, Any]) -> dict[str, Any]:
        if nome == "buscar_produtos":
            return buscar_produtos(
                db,
                termo=entrada.get("termo", "") or "",
                categoria=entrada.get("categoria", "") or "",
                preco_max=entrada.get("preco_max"),
                incluir_indisponiveis=bool(entrada.get("incluir_indisponiveis", False)),
            )
        if nome == "detalhar_produto":
            return detalhar_produto(db, entrada.get("nome_ou_id", ""))
        if nome == "listar_promocoes_ativas":
            return listar_promocoes_ativas(db)
        if nome == "consultar_pedido":
            return consultar_pedido(db, entrada.get("numero_pedido", ""), entrada.get("contato_cliente", ""))
        if nome == "situacao_atendimento":
            return situacao_atendimento()
        return {"erro": f"Ferramenta desconhecida: {nome}"}

    return executar
