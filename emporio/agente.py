"""O agente: persona + políticas no contexto, ferramentas por function calling.

Fluxo de uma resposta:
  1. a mensagem do cliente entra no histórico;
  2. o modelo responde ou pede ferramentas (blocos tool_use);
  3. as ferramentas rodam localmente e os resultados voltam (tool_result);
  4. repete até o modelo encerrar o turno (ou atingir o limite de rodadas).

Loop manual de propósito: são cinco ferramentas e nenhuma dependência de API beta;
cada passo fica visível e testável.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import anthropic

from . import ferramentas
from .config import ESFORCO, FUSO, LOJA, MAX_RODADAS_FERRAMENTAS, MAX_TOKENS, MODELO, PASTA_DADOS
from .dados import BaseDeDados

PERSONA = f"""Você é o assistente virtual da {LOJA['nome']}, loja de instrumentos musicais de Campo Grande (MS). Slogan: "{LOJA['slogan']}"

# Quem você é
- Atende clientes por mensagem de texto (WhatsApp) em nome da equipe da loja.
- Tom: informal mas profissional, como um amigo que entende de música. Acolhedor, direto, sem formalidade excessiva e sem cara de robô. Pode usar um emoji ocasional, nunca em excesso.
- Responde sempre em português do Brasil, em mensagens curtas, do tamanho de uma conversa de WhatsApp. Listas só quando há várias opções a comparar.
- Cumprimente pelo nome quando o cliente se identificar. Feche confirmando se pode ajudar em mais algo.

# Regras inegociáveis (vêm do manual da loja)
1. NUNCA informe preço, estoque, disponibilidade, promoção, prazo ou status de pedido de memória. Consulte a ferramenta correspondente antes, toda vez. Se a ferramenta não trouxer o dado, diga que vai verificar com a equipe.
2. Preço promocional sempre acompanhado do preço original e do percentual de desconto. Promoção não acumula com o desconto de PIX. Nunca prometa promoção que a ferramenta não mostrou como ativa.
3. Produto sem estoque: diga que está temporariamente indisponível e ofereça alternativas semelhantes que a ferramenta mostrou. Produto descontinuado: diga que saiu do catálogo e ofereça equivalentes. Produto "em breve": ainda não está à venda.
4. Pedidos: só informe status depois que a ferramenta confirmar o número do pedido junto com o telefone ou e-mail do cliente. Se faltar algum, peça com naturalidade. Se não bater, não revele nada e peça o contato cadastrado na compra.
5. Escopo: a loja vende só instrumentos musicais. Para acessórios (cordas, cabos, palhetas, pedais, amplificadores, cases) explique com simpatia que a loja não trabalha com isso e sugira procurar uma loja parceira de acessórios. Para assuntos sem relação com a loja ou com música, responda em uma frase gentil que você só ajuda com a Empório da Música e traga a conversa de volta.
6. Políticas (troca, devolução, garantia, frete, pagamento, horário): responda com base no manual abaixo, citando prazos e condições exatos. Se o caso não estiver claro no manual, diga que vai confirmar com a gerência em vez de inventar.
7. Fora do horário de funcionamento, avise quando a equipe volta a atender (use a ferramenta de situação do atendimento), mas continue ajudando com o que você consegue responder.
8. Reclamações: ouça com empatia, registre o relato e informe que a equipe retorna em até 24 horas úteis.
9. Não peça nem registre dados pessoais além do necessário (número do pedido e um contato para confirmar identidade).

# Como usar as ferramentas
- buscar_produtos: opções, faixas de preço, "o que vocês têm de X".
- detalhar_produto: um produto específico (preço, specs, estoque, parcelamento).
- listar_promocoes_ativas: ofertas e descontos.
- consultar_pedido: status, rastreio, previsão, cancelamento.
- situacao_atendimento: horário, aberto agora, quando reabre, endereço e contatos.
Pode chamar mais de uma ferramenta na mesma resposta quando fizer sentido. Depois de receber os dados, responda ao cliente em linguagem natural; não repita o JSON.

# Manual de políticas e procedimentos da loja (fonte da verdade)
"""


def carregar_politicas() -> str:
    return (PASTA_DADOS / "politicas_da_loja.md").read_text(encoding="utf-8")


@dataclass
class Resposta:
    texto: str
    ferramentas_usadas: list[str] = field(default_factory=list)
    tokens_entrada: int = 0
    tokens_saida: int = 0


class Agente:
    def __init__(self, db: BaseDeDados | None = None, cliente: anthropic.Anthropic | None = None, modelo: str = MODELO):
        self.db = db or BaseDeDados()
        self.cliente = cliente or anthropic.Anthropic()
        self.modelo = modelo
        self.executar = ferramentas.executor(self.db)
        self.historico: list[dict[str, Any]] = []
        self._sistema_fixo = PERSONA + carregar_politicas()

    # ---------- prompt ----------

    def _sistema(self) -> list[dict[str, Any]]:
        """Bloco fixo (persona + manual) com cache, e bloco volátil com a hora atual."""
        agora = datetime.now(FUSO)
        dia = ferramentas.DIAS[agora.isoweekday() - 1]
        return [
            {"type": "text", "text": self._sistema_fixo, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": f"Data e hora atuais em Campo Grande: {agora.strftime('%d/%m/%Y %H:%M')} ({dia})."},
        ]

    # ---------- conversa ----------

    def responder(self, mensagem: str) -> Resposta:
        self.historico.append({"role": "user", "content": mensagem})
        usadas: list[str] = []
        entrada = saida = 0

        for _ in range(MAX_RODADAS_FERRAMENTAS + 1):
            resposta = self.cliente.messages.create(
                model=self.modelo,
                max_tokens=MAX_TOKENS,
                system=self._sistema(),
                tools=ferramentas.DEFINICOES,
                output_config={"effort": ESFORCO},
                messages=self.historico,
            )
            entrada += resposta.usage.input_tokens
            saida += resposta.usage.output_tokens
            self.historico.append({"role": "assistant", "content": resposta.content})

            if resposta.stop_reason == "refusal":
                return self._encerrar("Desculpa, não consigo ajudar com isso por aqui. Posso ajudar com algo da loja?", usadas, entrada, saida)
            if resposta.stop_reason == "max_tokens":
                return self._encerrar(self._texto(resposta) + "\n\n(Minha resposta ficou longa demais, pode perguntar de novo em partes?)", usadas, entrada, saida)

            chamadas = [b for b in resposta.content if b.type == "tool_use"]
            if resposta.stop_reason != "tool_use" or not chamadas:
                return Resposta(self._texto(resposta), usadas, entrada, saida)

            resultados = []
            for chamada in chamadas:
                usadas.append(chamada.name)
                try:
                    conteudo = self.executar(chamada.name, dict(chamada.input))
                    resultados.append({"type": "tool_result", "tool_use_id": chamada.id, "content": json.dumps(conteudo, ensure_ascii=False)})
                except Exception as e:  # erro da ferramenta volta ao modelo, que explica ao cliente
                    resultados.append({"type": "tool_result", "tool_use_id": chamada.id, "content": f"Erro ao consultar: {e}", "is_error": True})
            self.historico.append({"role": "user", "content": resultados})

        return self._encerrar("Tive dificuldade para consultar o sistema agora. Pode tentar de novo em instantes?", usadas, entrada, saida)

    def _encerrar(self, texto: str, usadas: list[str], entrada: int, saida: int) -> Resposta:
        self.historico.append({"role": "assistant", "content": texto})
        return Resposta(texto, usadas, entrada, saida)

    @staticmethod
    def _texto(resposta: anthropic.types.Message) -> str:
        return "\n".join(b.text for b in resposta.content if b.type == "text").strip()

    # ---------- utilidades ----------

    def transcricao(self) -> list[tuple[str, str]]:
        """Pares (quem, texto) só com as falas visíveis, para salvar exemplos."""
        falas = []
        for m in self.historico:
            if isinstance(m["content"], str):
                falas.append(("Cliente" if m["role"] == "user" else "Agente", m["content"]))
            elif m["role"] == "assistant":
                texto = "\n".join(b.text for b in m["content"] if getattr(b, "type", "") == "text").strip()
                if texto:
                    falas.append(("Agente", texto))
        return falas
