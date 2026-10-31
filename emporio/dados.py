"""Camada de dados: lê os CSVs da loja e expõe objetos tipados.

Só biblioteca padrão. Os arquivos são pequenos (dezenas de linhas), então
tudo é carregado em memória uma vez; não há banco nem índice.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .config import PASTA_DADOS


def _num(valor: str) -> float:
    return float(valor) if valor not in ("", None) else 0.0


def normalizar(texto: str) -> str:
    """Minúsculas, sem acentos e sem pontuação, para comparação tolerante."""
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", sem_acento.lower()).strip()


def so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


@dataclass(frozen=True)
class Categoria:
    id: int
    nome: str
    descricao: str


@dataclass(frozen=True)
class Produto:
    id: int
    nome: str
    categoria_id: int
    preco: float
    descricao: str
    estoque: int
    status: str  # active | discontinued | coming_soon
    specs: dict = field(default_factory=dict)
    criado_em: str = ""


@dataclass(frozen=True)
class Promocao:
    id: int
    produto_id: int
    desconto_percent: float
    descricao: str
    ativa: bool


@dataclass(frozen=True)
class Cliente:
    id: int
    nome: str
    telefone: str
    email: str
    cidade: str


@dataclass(frozen=True)
class ItemPedido:
    pedido_id: int
    produto_id: int
    quantidade: int


@dataclass(frozen=True)
class Pedido:
    id: int
    cliente_id: int
    data: str
    status: str  # pending | confirmed | shipped | delivered | cancelled
    total: float
    pagamento: str
    rastreio: str
    previsao_entrega: str
    observacoes: str


class BaseDeDados:
    """Todos os dados da loja carregados em memória."""

    def __init__(self, pasta: Path = PASTA_DADOS):
        self.pasta = Path(pasta)
        self.categorias = {c.id: c for c in self._ler_categorias()}
        self.produtos = {p.id: p for p in self._ler_produtos()}
        self.promocoes = self._ler_promocoes()
        self.clientes = {c.id: c for c in self._ler_clientes()}
        self.itens = self._ler_itens()
        self.pedidos = {p.id: p for p in self._ler_pedidos()}

    # ---------- leitura ----------

    def _linhas(self, arquivo: str) -> list[dict[str, str]]:
        with open(self.pasta / arquivo, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    def _ler_categorias(self) -> list[Categoria]:
        return [Categoria(int(l["category_id"]), l["name"], l["description"]) for l in self._linhas("categories.csv")]

    def _ler_produtos(self) -> list[Produto]:
        produtos = []
        for l in self._linhas("products.csv"):
            try:
                specs = json.loads(l.get("specs") or "{}")
            except json.JSONDecodeError:
                specs = {}
            produtos.append(
                Produto(
                    id=int(l["product_id"]),
                    nome=l["name"].strip(),
                    categoria_id=int(l["category_id"]),
                    preco=_num(l["price_brl"]),
                    descricao=l.get("description", "").strip(),
                    estoque=int(_num(l.get("stock_quantity", "0"))),
                    status=(l.get("status") or "active").strip(),
                    specs=specs,
                    criado_em=l.get("created_at", ""),
                )
            )
        return produtos

    def _ler_promocoes(self) -> list[Promocao]:
        return [
            Promocao(int(l["promotion_id"]), int(l["product_id"]), _num(l["discount_percent"]), l["description"], l["is_active"].strip() == "1")
            for l in self._linhas("promotions.csv")
        ]

    def _ler_clientes(self) -> list[Cliente]:
        return [Cliente(int(l["customer_id"]), l["name"], l["phone"], l["email"], l["city"]) for l in self._linhas("customers.csv")]

    def _ler_itens(self) -> list[ItemPedido]:
        return [ItemPedido(int(l["order_id"]), int(l["product_id"]), int(_num(l["quantity"]))) for l in self._linhas("order_items.csv")]

    def _ler_pedidos(self) -> list[Pedido]:
        return [
            Pedido(
                id=int(l["order_id"]),
                cliente_id=int(l["customer_id"]),
                data=l["order_date"],
                status=l["status"].strip(),
                total=_num(l["total_brl"]),
                pagamento=l["payment_method"],
                rastreio=l.get("tracking_code", "") or "",
                previsao_entrega=l.get("estimated_delivery", "") or "",
                observacoes=l.get("notes", "") or "",
            )
            for l in self._linhas("orders.csv")
        ]

    # ---------- consultas ----------

    def promocao_ativa(self, produto_id: int) -> Promocao | None:
        """Maior promoção ativa do produto (promoções não são cumulativas)."""
        ativas = [p for p in self.promocoes if p.produto_id == produto_id and p.ativa]
        return max(ativas, key=lambda p: p.desconto_percent) if ativas else None

    def categoria_por_nome(self, texto: str) -> Categoria | None:
        alvo = normalizar(texto)
        if not alvo:
            return None
        for c in self.categorias.values():
            if alvo in normalizar(c.nome) or normalizar(c.nome) in alvo:
                return c
        # singular/plural simples (violao -> violoes)
        for c in self.categorias.values():
            if alvo.rstrip("s") and alvo.rstrip("s")[:5] in normalizar(c.nome):
                return c
        return None

    def itens_do_pedido(self, pedido_id: int) -> list[ItemPedido]:
        return [i for i in self.itens if i.pedido_id == pedido_id]

    def cliente_por_contato(self, contato: str) -> Cliente | None:
        """Localiza o cliente por telefone (comparando só dígitos) ou e-mail (sem diferenciar maiúsculas)."""
        digitos = so_digitos(contato)
        email = (contato or "").strip().lower()
        for c in self.clientes.values():
            tel = so_digitos(c.telefone)
            if len(digitos) >= 8 and (tel.endswith(digitos) or digitos.endswith(tel)):
                return c
            if "@" in email and c.email.lower() == email:
                return c
        return None
