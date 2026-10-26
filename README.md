# QRErwk — versão 2.0.0.0 (base de atualização)

Projeto web do jogo O Quarto Reich Estelar. Mantém os recursos originais e adiciona a base de contas, loja, inventário, recordes e power-ups.

## Rodar localmente

Requer Python 3.11 ou superior.

```bash
python -m pip install -r requirements.txt
python main.py
```

Abra `http://localhost:5000`. Sem `DATABASE_URL`, o servidor usa SQLite em `qrerwk.sqlite3`, adequado para desenvolvimento e testes locais.

## Publicação multiusuário

Para uma publicação real com contas compartilhadas e placar mundial, configure um banco PostgreSQL persistente no provedor de hospedagem e defina `DATABASE_URL` como variável de ambiente secreta. Instale as dependências com `pip install -r requirements.txt`. Não publique credenciais no GitHub. Em HTTPS, o cookie de sessão usa `Secure` quando o proxy define `X-Forwarded-Proto: https`; se necessário, defina `COOKIE_SECURE=true`.

SQLite local não deve ser usado como banco compartilhado em ambientes autoscale/efêmeros: os dados podem não persistir ou não ser compartilhados entre instâncias.

## O que está nesta atualização

- Cadastro/login com nickname e senha; hash de senha com scrypt e cookie de sessão HTTP-only.
- Sessão persistente e opções para trocar de conta ou excluir a conta após confirmar a senha.
- Loja com os preços de naves e power-ups definidos para a versão 2.0.
- Inventário, ativação/desativação de power-ups e equipamento de naves P1/P2.
- Recorde pessoal e tabela dos 20 melhores por modo.
- Recompensas de moedas, quatro efeitos de power-up, indicador de moedas na partida, ícones de nave para vidas e aumento da vida inimiga a cada dez ondas.
- Correção do movimento da formação junto às bordas.

## Limitação importante antes de abrir ao público

A jogabilidade continua sendo executada no navegador, como no projeto original. A API atual salva o resultado final enviado pelo cliente, portanto não é um sistema antitrapaça totalmente autoritativo: alguém tecnicamente experiente poderia falsificar resultados por chamadas diretas à API. Antes de promover o placar a competição pública com recompensas valiosas, será necessário implementar validação de partida no servidor (ou um protocolo de eventos de jogo verificáveis) e adicionar proteções operacionais como rate limiting, logs e política de backup do banco.

## Estrutura

- `index.html`: introdução, autenticação, menu, loja, inventário, pontuação e opções.
- `game.html`: jogo, ondas, inimigos, chefes, power-ups e resultado da partida.
- `lore.html`: história original.
- `main.py`: servidor HTTP e API.
- `assets/`: artes e vídeos originais.
- `requirements.txt`: driver PostgreSQL opcional/produção.
