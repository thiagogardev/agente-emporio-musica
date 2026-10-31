"""Configuração: caminhos, modelo e dados fixos da loja."""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
PASTA_DADOS = RAIZ / "data"

load_dotenv(RAIZ / ".env")

MODELO = os.getenv("EMPORIO_MODELO", "claude-sonnet-5-5")
ESFORCO = os.getenv("EMPORIO_ESFORCO", "medium")  # low | medium | high
MAX_TOKENS = 4096
MAX_RODADAS_FERRAMENTAS = 8  # limite de idas e vindas de ferramentas numa única resposta

FUSO = ZoneInfo("America/Campo_Grande")

LOJA = {
    "nome": "Empório da Música",
    "slogan": "Sua música começa aqui.",
    "endereco": "Rua 14 de Maio, 3200, Centro, Campo Grande - MS, CEP 79202-333",
    "telefone": "(67) 3341-4444",
    "whatsapp": "(67) 3321-4500",
    "email": "contato@emporiodamusica.com.br",
}

# (dia da semana ISO: 1 = segunda ... 7 = domingo) -> (abre, fecha) ou None se fechado
HORARIO = {
    1: ("09:00", "18:00"),
    2: ("09:00", "18:00"),
    3: ("09:00", "18:00"),
    4: ("09:00", "18:00"),
    5: ("09:00", "18:00"),
    6: ("09:00", "13:00"),
    7: None,
}

DESCONTO_PIX = 0.05
