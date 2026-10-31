"""Testes das ferramentas e das regras de negócio, sem chamar o modelo."""

from datetime import datetime

import pytest

from emporio.config import FUSO
from emporio.dados import BaseDeDados
from emporio import ferramentas as f


@pytest.fixture(scope="module")
def db() -> BaseDeDados:
    return BaseDeDados()


# ---------- dados ----------


def test_carrega_todos_os_arquivos(db):
    assert len(db.produtos) == 65
    assert len(db.clientes) == 50
    assert len(db.pedidos) == 20
    assert len(db.categorias) == 9
    assert len(db.promocoes) == 25


def test_promocao_ativa_so_quando_marcada(db):
    assert db.promocao_ativa(90).desconto_percent == 18  # Crafter HT-100, ativa
    assert db.promocao_ativa(93) is None  # Martin D-28: duas promoções, ambas inativas


# ---------- regras de preço ----------


@pytest.mark.parametrize(
    "valor, parcelas",
    [(2199.0, 12), (1200.0, 12), (1199.0, 11), (799.9, 7), (599.9, 6), (429.9, 5), (240.0, 3), (159.9, 3), (45.0, 1)],
)
def test_parcelamento_segue_regras_do_manual(valor, parcelas):
    assert f.parcelamento_maximo(valor) == parcelas


def test_pix_tem_5_por_cento_sem_promocao(db):
    takamine = db.produtos[95]  # Takamine GD20, R$ 2.199, sem promoção ativa
    c = f.condicoes_de_preco(db, takamine)
    assert c["preco_tabela"] == "R$ 2.199,00"
    assert c["promocao"] is None
    assert c["preco_pix"] == "R$ 2.089,05"
    assert c["parcelamento"].startswith("até 12x")


def test_promocao_nao_acumula_com_pix(db):
    crafter = db.produtos[90]  # R$ 2.399 com 18% ativo
    c = f.condicoes_de_preco(db, crafter)
    assert c["promocao"]["preco_promocional"] == "R$ 1.967,18"
    assert c["preco_pix"] == "R$ 1.967,18"
    assert "não acumula" in c["pix_nota"]


# ---------- busca ----------


def test_busca_violoes_ate_mil_so_disponiveis(db):
    r = f.buscar_produtos(db, categoria="violões", preco_max=1000)
    nomes = [p["nome"] for p in r["produtos"]]
    assert "Yamaha C40 Nylon Natural" in nomes
    assert "Giannini GF-3D Dreadnought Sunburst" not in nomes  # ativo, mas estoque zero
    assert any("GF-3D" in o for o in r["ocultos_por_indisponibilidade"])
    assert all(p["disponibilidade"].startswith("disponível") for p in r["produtos"])


def test_busca_por_termo_e_marca(db):
    r = f.buscar_produtos(db, termo="takamine")
    assert {p["nome"] for p in r["produtos"]} >= {"Takamine GD20 Dreadnought Natural", "Takamine GC5CE Elétrico Nylon Natural"}


def test_busca_categoria_inexistente(db):
    r = f.buscar_produtos(db, categoria="amplificadores")
    assert "erro" in r and "Guitarras" in r["categorias_existentes"]


def test_busca_respeita_preco_promocional(db):
    # Crafter HT-100 custa 2.399 de tabela, 1.967,18 na promoção: entra num teto de 2.000
    r = f.buscar_produtos(db, termo="crafter ht-100", preco_max=2000)
    assert r["total_encontrado"] == 1


# ---------- detalhe ----------


def test_detalhe_por_nome_parcial(db):
    d = f.detalhar_produto(db, "Takamine GD20")
    assert d["id"] == 95 and d["preco_tabela"] == "R$ 2.199,00"
    assert d["especificacoes"]["top"] == "Cedro Sólido"


def test_detalhe_ambiguo_lista_opcoes(db):
    d = f.detalhar_produto(db, "Yamaha")
    assert d.get("ambiguo") and len(d["opcoes"]) > 1


def test_detalhe_descontinuado_traz_alternativas(db):
    d = f.detalhar_produto(db, "113")
    assert d["status"] == "descontinuado"
    assert d["alternativas_disponiveis"] and all(a["disponibilidade"].startswith("disponível") for a in d["alternativas_disponiveis"])


def test_detalhe_em_breve(db):
    d = f.detalhar_produto(db, "Kala KA-ABP-CTG")
    assert d["status"] == "em breve" and d["disponibilidade"].startswith("em breve")


def test_detalhe_sem_estoque(db):
    d = f.detalhar_produto(db, "Giannini GF-3D")
    assert "indisponível" in d["disponibilidade"] and d["alternativas_disponiveis"]


def test_detalhe_inexistente(db):
    assert "erro" in f.detalhar_produto(db, "Stradivarius 1715")


# ---------- promoções ----------


def test_promocoes_ativas(db):
    r = f.listar_promocoes_ativas(db)
    assert r["total"] == 4
    assert {p["id"] for p in r["promocoes_ativas"]} == {127, 121, 90, 94}


# ---------- pedidos (LGPD) ----------


def test_pedido_com_contato_correto(db):
    r = f.consultar_pedido(db, "1", "(67) 98432-1098")  # pedido 1 é do cliente 3
    assert r["status_codigo"] == "delivered" and r["codigo_rastreio"] == "BRAB1234567BR"
    assert r["itens"][0]["produto"] == "Martin D-28 Dreadnought Natural"


def test_pedido_por_email_sem_diferenciar_maiusculas(db):
    r = f.consultar_pedido(db, "#15", "Aline.Monteiro@jmail.com")
    assert r["status_codigo"] == "pending" and len(r["itens"]) == 2


def test_pedido_com_contato_de_outro_cliente_e_recusado(db):
    r = f.consultar_pedido(db, "1", "lucas.mendes@jmail.com")
    assert "erro" in r and "status" not in r


def test_pedido_cancelado_traz_motivo(db):
    r = f.consultar_pedido(db, "19", "(67) 98432-1098")
    assert r["status_codigo"] == "cancelled" and "Pagamento" in r["observacoes"]


def test_pedido_inexistente(db):
    assert "erro" in f.consultar_pedido(db, "999", "(67) 98432-1098")


# ---------- horário ----------


def test_aberta_sabado_de_manha():
    s = f.situacao_atendimento(datetime(2026, 10, 31, 10, 30, tzinfo=FUSO))  # sábado
    assert s["loja_aberta"] is True and s["horario_hoje"] == "09:00 às 13:00"


def test_fechada_sabado_a_tarde_reabre_segunda():
    s = f.situacao_atendimento(datetime(2026, 10, 31, 15, 0, tzinfo=FUSO))
    assert s["loja_aberta"] is False and s["proxima_abertura"] == "segunda às 09:00"


def test_fechada_domingo():
    s = f.situacao_atendimento(datetime(2026, 11, 1, 11, 0, tzinfo=FUSO))
    assert s["loja_aberta"] is False and s["horario_hoje"] == "fechado" and s["proxima_abertura"] == "segunda às 09:00"


def test_fechada_quarta_a_noite_reabre_quinta():
    s = f.situacao_atendimento(datetime(2026, 11, 4, 19, 0, tzinfo=FUSO))
    assert s["loja_aberta"] is False and s["proxima_abertura"] == "quinta às 09:00"


# ---------- executor ----------


def test_executor_despacha_e_trata_desconhecida(db):
    ex = f.executor(db)
    assert ex("listar_promocoes_ativas", {})["total"] == 4
    assert "erro" in ex("ferramenta_que_nao_existe", {})
