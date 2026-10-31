# Agente de atendimento · Empório da Música

Protótipo de agente de atendimento por texto para a Empório da Música, loja fictícia de instrumentos musicais de Campo Grande (MS). Desafio técnico da vaga de AI Engineer (Artefact).

O agente assume a persona da loja, responde com base no manual de políticas, consulta os dados da operação (catálogo, estoque, promoções, pedidos) por function calling e recusa com educação o que foge do escopo.

```
Você: tem violão de nylon até mil reais?
Agente: Tem sim! Consultei aqui o catálogo e separei as opções de nylon até R$ 1.000 que estão em estoque: ...
```

Conversas completas de exemplo, gravadas de execuções reais, estão em [`exemplos/`](exemplos/):

| Conversa | O que mostra |
|---|---|
| [01 · Catálogo: violões até R$ 1.000](exemplos/01-catalogo-violoes-ate-1000.md) | busca com filtro de preço, PIX e parcelamento de um item |
| [02 · Preço: Takamine GD20 e produto em promoção](exemplos/02-preco-takamine-e-promocao.md) | preço promocional com original e percentual; promoção não acumula com PIX |
| [03 · Pedido com confirmação de identidade](exemplos/03-pedido-com-confirmacao-de-identidade.md) | pede contato antes de consultar; status de pedido pendente |
| [04 · Devolução por arrependimento](exemplos/04-devolucao-por-arrependimento.md) | **caso não trivial**: cruza a política de 7 dias com a data real do pedido e explica o que ainda cabe |
| [05 · Fora de escopo e produto sem estoque](exemplos/05-fora-de-escopo-e-produto-indisponivel.md) | recusa acessórios e assunto alheio; produto sem estoque com alternativas |

Cada arquivo registra as ferramentas chamadas em cada turno e os tokens da conversa. Para regravar: `python scripts/gravar_exemplos.py`.

## Como rodar

Requisitos: Python 3.11 ou superior e uma chave da API da Anthropic.

```bash
git clone https://github.com/thiagogardev/agente-emporio-musica.git
cd agente-emporio-musica
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate      # Linux e macOS
pip install -e ".[dev]"
copy .env.example .env           # cp no Linux e macOS
```

Edite o `.env` e preencha `ANTHROPIC_API_KEY`. As outras variáveis têm padrão.

```bash
python -m emporio                                  # conversa interativa
python -m emporio -m "Quanto custa o Takamine GD20?"   # uma pergunta
python -m emporio --debug                          # mostra ferramentas chamadas e tokens
python -m emporio --salvar conversas/minha.md      # grava a transcrição ao sair
pytest                                             # testes das ferramentas (não usam a API)
```

| Variável | Padrão | Para quê |
|---|---|---|
| `ANTHROPIC_API_KEY` | obrigatória | autenticação na API |
| `EMPORIO_MODELO` | `claude-sonnet-5-5` | modelo; `claude-haiku-5-5` para testes baratos |
| `EMPORIO_ESFORCO` | `medium` | profundidade de raciocínio (`low`, `medium`, `high`) |

## Como funciona

```
cliente ──texto──▶ Agente.responder()
                      │  system = persona + manual de políticas (cacheado) + data/hora
                      │  tools  = 5 ferramentas sobre os CSVs
                      ▼
                 Claude (messages.create)
                      │ stop_reason == "tool_use"?
                      ├── sim: executa as ferramentas localmente, devolve tool_result, repete
                      └── não: texto final para o cliente
```

**Duas fontes de conhecimento, dois mecanismos.**

- **Políticas** (horário, pagamento, trocas, frete, garantia, LGPD) vão inteiras no prompt de sistema. O manual tem 8 páginas, cerca de 3 mil tokens: cabe com folga e dispensa um pipeline de RAG, que acrescentaria uma etapa de recuperação (e uma fonte de erro) sem ganho. O bloco é marcado com `cache_control`, então é cobrado integralmente só na primeira chamada de cada sessão.
- **Dados** (produtos, estoque, promoções, pedidos, clientes) ficam fora do prompt e são consultados sob demanda por ferramentas. Dado operacional muda; o modelo não deve memorizá-lo. O manual é explícito: "nunca fornecer preço, estoque ou prazo sem consultar o sistema".

**As ferramentas** ([`emporio/ferramentas.py`](emporio/ferramentas.py)):

| Ferramenta | Quando o modelo chama | O que faz de especial |
|---|---|---|
| `buscar_produtos` | "o que vocês têm de X", faixa de preço | filtra por termo, categoria e preço máximo já com promoção aplicada; esconde indisponíveis por padrão, mas lista o que escondeu |
| `detalhar_produto` | um produto específico | specs, estoque, status; se indisponível ou descontinuado, traz 3 alternativas da mesma categoria com preço próximo |
| `listar_promocoes_ativas` | ofertas, descontos | só promoções com `is_active = 1`; as 21 inativas nunca aparecem |
| `consultar_pedido` | status, rastreio, previsão | exige número do pedido **e** telefone ou e-mail do dono; se não bater, recusa e não revela nada (LGPD) |
| `situacao_atendimento` | horário, aberto agora, endereço | calcula no fuso de Campo Grande se está aberto e quando reabre |

As regras de preço do manual estão em código, não no prompt: PIX com 5% sobre o preço de tabela, promoção não cumulativa com PIX, parcelamento sem juros com os mínimos de parcela por faixa (3x, 4 a 6x, 7 a 12x). O modelo decide *quando* consultar; a conta é determinística e testada.

**Casos de borda dos dados**, tratados de propósito porque o manual diz o que fazer em cada um:

- produto ativo com estoque zero (Giannini GF-3D): "temporariamente indisponível" + alternativas;
- produtos descontinuados (Shelby SN-7C, Ibanez Bass 2X): "saiu do catálogo" + equivalentes;
- produto `coming_soon` (Kala barítono): "em breve", não está à venda;
- 21 de 25 promoções inativas: nunca prometidas;
- pedidos cancelados trazem o motivo registrado; pendentes e confirmados não têm rastreio ainda.

## Decisões técnicas

**Abordagem: function calling com loop manual, sem framework.** O problema tem cinco ferramentas e uma base de dados pequena. LangChain, LlamaIndex ou um agente de SQL acrescentariam camadas que escondem exatamente o que o avaliador quer ver: quando o modelo decide consultar, o que recebe e como responde. O loop em [`emporio/agente.py`](emporio/agente.py) tem 30 linhas e cada passo é visível e testável. O SDK da Anthropic oferece um *tool runner* que faz esse loop sozinho; não usei para não depender de API em beta e para controlar os casos de parada (`refusal`, `max_tokens`, limite de rodadas).

**Modelo: Claude Sonnet 5.5 via API da Anthropic.** O núcleo do agente é decidir corretamente entre responder, chamar uma ferramenta ou chamar várias. É onde modelos menores erram mais (ferramenta errada, argumento inventado, preço de cabeça). Sonnet 5.5 tem function calling confiável, português natural para a persona e custo irrelevante neste volume (centavos por dezenas de conversas). O raciocínio adaptativo fica ligado com esforço `medium`; `low` deixa mais rápido e barato, `high` ajuda em casos ambíguos. `claude-haiku-5-5` está documentado como alternativa barata.

**Retrieval: contexto completo, não RAG.** Explicado acima. Se o manual crescesse para dezenas de páginas, ou houvesse vários documentos, o caminho seria chunking por seção com busca híbrida (BM25 + embeddings) e citação da seção na resposta.

**Prompt.** Persona curta, nove regras numeradas que são as do manual em forma imperativa, um guia de qual ferramenta usar quando, e o manual inteiro em markdown como "fonte da verdade". O manual original era PDF; a versão em [`data/politicas_da_loja.md`](data/politicas_da_loja.md) foi extraída e revisada à mão para manter títulos e listas, porque texto bem estruturado melhora o uso que o modelo faz dele. A data e hora atuais entram num bloco separado, depois do bloco cacheado, para não invalidar o cache a cada minuto.

**Interface: CLI.** O enunciado diz que o foco é o agente funcionando. A CLI tem modo interativo, modo de mensagem única (bom para scripts e para gerar os exemplos) e gravação da transcrição em markdown.

**Persistência do histórico: em memória, por sessão.** O histórico completo (incluindo chamadas e resultados de ferramentas) é mantido durante a conversa e reenviado a cada turno, que é como a API funciona. Entre sessões não persiste: num canal real (WhatsApp) o histórico viria do próprio canal ou de um banco por número de telefone, e isso é uma decisão de produto, não do protótipo. A opção `--salvar` grava a conversa visível em markdown.

**Tratamento de dados.** CSVs lidos com a biblioteca padrão para dataclasses tipadas; `specs` (JSON em string) é desserializado; busca normaliza acentos e pontuação; telefone compara só dígitos; e-mail ignora maiúsculas. Nenhum dado foi alterado.

**Identidade antes de dados pessoais.** A ferramenta de pedido recusa se o contato não for do dono do pedido, e o prompt instrui o modelo a pedir o contato com naturalidade. A ferramenta é a barreira; o prompt é só a conversa. Dados de clientes nunca entram no prompt de sistema.

## Testes

`pytest` roda 34 testes sobre a camada de dados e as ferramentas, sem chamar a API: regras de parcelamento e PIX, busca com e sem promoção, produtos indisponíveis, descontinuados e em breve, confirmação de identidade no pedido, cálculo de horário em quatro momentos da semana. Eles protegem exatamente as regras que o manual chama de inegociáveis.

O comportamento do modelo (decidir qual ferramenta chamar, tom, recusa fora de escopo) foi validado com as conversas em [`exemplos/`](exemplos/), gravadas de execuções reais pelo script [`scripts/gravar_exemplos.py`](scripts/gravar_exemplos.py), que roda cenários fixos e salva a transcrição sem edição. Nas cinco conversas o modelo escolheu a ferramenta certa em todos os turnos e não chamou nenhuma quando a resposta estava no manual ou fora do escopo. Custo total das cinco gravações: cerca de 20 mil tokens de entrada (a maior parte servida do cache) e 5 mil de saída.

## Limitações conhecidas e o que eu faria com mais tempo

- **Sem avaliação automática do agente.** Os testes cobrem as ferramentas; o comportamento do modelo foi verificado à mão. O próximo passo seria um conjunto de 30 a 50 perguntas com resposta esperada (ferramenta certa chamada, dado certo citado, recusa fora de escopo) rodado em CI, e um juiz automático para tom e aderência às políticas.
- **Um provedor só.** Uma camada de provedor plugável permitiria comparar Sonnet com um modelo aberto via Groq ou Ollama, medindo acerto de ferramenta, latência e custo.
- **Sem canal real.** A integração com WhatsApp (API oficial) traria identificação do cliente pelo número, histórico persistente e transferência para atendente humano.
- **Dados estáticos.** Em produção as ferramentas consultariam o sistema da loja (ERP ou banco) em vez de CSVs; a interface das ferramentas já isola isso.
- **Busca léxica.** A busca de produtos é por palavras normalizadas. Perguntas abertas ("quero algo para começar a tocar") dependem do modelo escolher bons termos; embeddings sobre nome e descrição resolveriam melhor.
- **Sem streaming nem interface gráfica.** Numa UI de chat, a resposta deveria chegar em streaming.

## Uso de assistentes de código

Usei o **Claude Code** (Anthropic) como par de programação durante todo o desenvolvimento, em sessão de terminal. Fluxo:

1. Li o enunciado, o manual e os CSVs e defini a abordagem (contexto completo para políticas, ferramentas para dados, loop manual) antes de escrever código. As decisões deste README são minhas; o assistente ajudou a argumentar prós e contras.
2. Pedi ao assistente a estrutura do projeto e a primeira versão de cada módulo, revisando arquivo por arquivo. Corrigi regras de negócio que vieram erradas na primeira versão (os mínimos de parcela por faixa, por exemplo, foram ajustados com testes que falharam de propósito).
3. Os testes foram escritos junto com as ferramentas e rodados a cada mudança. Vários casos de borda dos dados (estoque zero, descontinuado, em breve, promoções inativas) foram encontrados explorando os CSVs com o assistente antes de codar.
4. As conversas de exemplo foram geradas rodando o agente de verdade por um script; nenhuma foi editada à mão. Ao ler a primeira gravação, vi que a busca cortava a lista em 10 itens quando havia 14; subi o limite e regravei.
5. Commits incrementais ao longo do trabalho, com mensagens escritas por mim.

O assistente acelerou a parte mecânica (esqueleto, parsing, testes repetitivos) e serviu de revisor; a arquitetura, as decisões e a verificação final foram minhas.

## Entrega

O enunciado pede o link do repositório na resposta ao e-mail do processo; o e-mail de abertura pede o envio de um PDF pelo Google Forms. Como as duas instruções coexistem, o link vai pelos dois canais: na resposta ao e-mail e num PDF curto enviado pelo formulário, com o mesmo link e um resumo deste README. Suposições e ambiguidades do enunciado estão documentadas acima, como pedido.

## Estrutura

```
emporio/
  config.py        caminhos, modelo, dados fixos da loja, horário
  dados.py         leitura dos CSVs em dataclasses; busca normalizada
  ferramentas.py   as 5 ferramentas, regras de preço, definições para o modelo
  agente.py        persona, prompt de sistema, loop de ferramentas
  cli.py           interface de linha de comando
data/              CSVs, PDF original e manual em markdown
exemplos/          conversas gravadas de execuções reais
scripts/           gravar_exemplos.py roda os cenários e salva as transcrições
tests/             34 testes das ferramentas
```

Licença MIT.
