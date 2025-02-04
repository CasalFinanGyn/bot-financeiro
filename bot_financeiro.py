import os
import json
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, CallbackContext
from datetime import datetime
from collections import defaultdict  # Import necessário para os relatórios


# 🔹 Pegar credenciais do ambiente
CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS")  # Pegando do Render

def autenticar_google_sheets():
    try:
        if not CREDENTIALS_JSON:
            raise ValueError("❌ ERRO: Credenciais do Google não encontradas!")

        credenciais = json.loads(CREDENTIALS_JSON)
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(credenciais, scopes=scopes)
        return gspread.authorize(creds)

    except Exception as e:
        raise ValueError(f"❌ Erro ao carregar credenciais: {e}")

# Conectar ao Google Sheets
gc = autenticar_google_sheets()

# Teste de conexão à planilha (Opcional: para verificar se está funcionando)
try:
    planilha = gc.open("Controle Financeiro")  # Substitua pelo nome da sua planilha
    print("✅ Conexão bem-sucedida com a planilha!")
except Exception as e:
    print(f"❌ Erro ao acessar a planilha: {e}")

# Conectar à planilha do Google Sheets
gc = autenticar_google_sheets()
if gc:
    planilha = gc.open("Controle Financeiro")  # Substitua pelo nome da sua planilha
    aba = planilha.sheet1  # Aba principal onde os gastos são registrados
    try:
        aba_categorias = planilha.worksheet("Config_Categorias")
    except gspread.exceptions.WorksheetNotFound:
        aba_categorias = planilha.add_worksheet(title="Config_Categorias", rows="100", cols="1")
    try:
        aba_cartoes = planilha.worksheet("Config_Cartões")
    except gspread.exceptions.WorksheetNotFound:
        aba_cartoes = planilha.add_worksheet(title="Config_Cartões", rows="100", cols="1")


# Função para carregar categorias e cartões da planilha
def carregar_configuracoes():
    categorias = aba_categorias.col_values(1) if aba_categorias else []
    cartoes = aba_cartoes.col_values(1) if aba_cartoes else []
    return categorias, cartoes


# Carregar categorias e cartões diretamente da planilha
CATEGORIAS, CARTOES = carregar_configuracoes()

# Formas de pagamento fixas
FORMAS_PAGAMENTO = ["💳 Crédito", "💳 Débito", "💸 Dinheiro", "⚡ PIX"]

# Criar menu inicial com botões
async def start(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("💰 Ver saldo", callback_data="saldo")],
        [InlineKeyboardButton("📅 Extrato do mês", callback_data="extrato")],
        [InlineKeyboardButton("📈 Gastos por categoria", callback_data="categoria")],
        [InlineKeyboardButton("📂 Exportar planilha", callback_data="exportar")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📊 Menu Financeiro:", reply_markup=reply_markup)

# Gerar relatório de gastos por categoria
async def relatorio_categoria(update: Update, context: CallbackContext):
    dados = aba.get_all_values()[1:]  # Pega todas as linhas, ignorando o cabeçalho

    categorias = defaultdict(float)
    for linha in dados:
        if len(linha) < 4:  # Se a linha tiver menos de 4 colunas, pula
            continue
        data, descricao, valor, categoria, *resto = linha  # Garante que só pegamos as colunas certas

        try:
            valor = float(valor.replace(',', '.'))  # Converte o valor para float
            categorias[categoria] += valor  # Soma os valores por categoria
        except ValueError:
            continue  # Pula linhas com valores inválidos

    if not categorias:
        await update.message.reply_text("📊 Nenhum gasto registrado ainda.")
        return

    mensagem = "📊 Gastos por Categoria:\n"
    for cat, total in categorias.items():
        mensagem += f"- {cat}: R$ {total:.2f}\n"

    await update.message.reply_text(mensagem)

# Registrar gasto e perguntar categoria
async def registrar_gasto(update: Update, context: CallbackContext):
    try:
        mensagem = update.message.text.strip()
        partes = mensagem.rsplit(' ', 1)  # Divide a mensagem em descrição e valor
        descricao = partes[0]
        valor = float(partes[1].replace(',', '.'))  # Converte para float

        # Salva temporariamente o gasto na memória
        context.user_data['gasto_temp'] = (descricao, valor)

        # Criar botões de categorias
        keyboard = [[InlineKeyboardButton(cat, callback_data=f"cat_{cat}")] for cat in CATEGORIAS]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"Qual a categoria para '{descricao} - R$ {valor:.2f}'?",
            reply_markup=reply_markup
        )

    except (IndexError, ValueError):
        await update.message.reply_text("Formato inválido! Use: Descrição Valor (ex.: iFood 19,90).")

# Registrar categoria e perguntar forma de pagamento
async def registrar_categoria(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    if 'gasto_temp' not in context.user_data:
        await query.message.reply_text("Erro: Nenhum gasto para categorizar.")
        return

    categoria = query.data.replace("cat_", "")  # Remove o prefixo "cat_"
    context.user_data['categoria_temp'] = categoria

    # Criar botões de formas de pagamento
    keyboard = [[InlineKeyboardButton(fp, callback_data=f"pag_{fp}")] for fp in FORMAS_PAGAMENTO]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(f"✅ Categoria selecionada: {categoria}\nAgora, escolha a forma de pagamento:", reply_markup=reply_markup)

# Registrar forma de pagamento e perguntar cartão (se necessário)
async def registrar_pagamento(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    forma_pagamento = query.data.replace("pag_", "")
    context.user_data['pagamento_temp'] = forma_pagamento

    if forma_pagamento in ["💳 Crédito", "💳 Débito"]:
        # Criar botões para escolher o cartão
        keyboard = [[InlineKeyboardButton(cartao, callback_data=f"cart_{cartao}")] for cartao in CARTOES]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_text(f"💰 Pagamento com {forma_pagamento} selecionado.\nAgora, escolha o cartão:", reply_markup=reply_markup)
    else:
        await salvar_gasto(update, context, "-")

# Registrar cartão e salvar na planilha
async def registrar_cartao(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    cartao = query.data.replace("cart_", "")
    await salvar_gasto(update, context, cartao)

# Salvar gasto na planilha
async def salvar_gasto(update: Update, context: CallbackContext, cartao):
    query = update.callback_query
    await query.answer()

    descricao, valor = context.user_data['gasto_temp']
    categoria = context.user_data['categoria_temp']
    forma_pagamento = context.user_data['pagamento_temp']
    data_atual = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

    # Salvar na planilha com categoria, pagamento e cartão
    aba.append_row([data_atual, descricao, valor, categoria, forma_pagamento, cartao])

    await query.message.edit_text(f"✅ Gasto registrado com sucesso!\n\n💸 {descricao} - R$ {valor:.2f}\n📂 Categoria: {categoria}\n💳 Pagamento: {forma_pagamento} ({cartao})")

    # Limpar dados temporários do usuário
    context.user_data.clear()
    
from datetime import datetime

from datetime import datetime

from datetime import datetime

# Processar botões do menu principal
async def botao_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    if query.data == "saldo":
        valores = aba.col_values(3)[1:]  # Pega todos os valores da coluna "Valor"
        saldo = sum(float(v.replace(',', '.')) for v in valores if v)  # Converte para float e soma
        await query.message.reply_text(f"💰 Saldo atual: R$ {saldo:.2f}")

    elif query.data == "extrato":
        dados = aba.get_all_values()[1:]  # Pega todas as linhas, ignorando o cabeçalho

        meses_disponiveis = set()
        for linha in dados:
            if len(linha) < 3:
                continue  # Ignora linhas incompletas
            data = linha[0]
            try:
                data_formatada = datetime.strptime(data, '%d/%m/%Y %H:%M:%S')
                meses_disponiveis.add(data_formatada.strftime('%m/%Y'))  # Formato MM/AAAA
            except ValueError:
                continue  # Ignora erros de formatação de data

        if not meses_disponiveis:
            await query.message.edit_text("📅 Nenhum lançamento encontrado.")
            return

        # Criar botões com os meses disponíveis
        meses_ordenados = sorted(meses_disponiveis, key=lambda x: datetime.strptime(x, '%m/%Y'), reverse=True)
        keyboard = [[InlineKeyboardButton(mes, callback_data=f"extrato_mes_{mes}")] for mes in meses_ordenados]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("📅 Selecione o mês para ver o extrato:", reply_markup=reply_markup)

    elif query.data == "categoria":
        await selecionar_mes_categoria(update, context)

    elif query.data == "categoria":
        await relatorio_categoria(query, context)

        # Exibir extrato do mês selecionado
async def extrato_por_mes(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    dados = aba.get_all_values()[1:]  # Pega todas as linhas, ignorando o cabeçalho
    mes_selecionado = query.data.replace("extrato_mes_", "")  # Remove o prefixo para obter o mês (MM/AAAA)

    extrato = []
    for linha in dados:
        if len(linha) < 3:
            continue  # Ignora linhas incompletas
        data = linha[0]
        try:
            data_formatada = datetime.strptime(data, '%d/%m/%Y %H:%M:%S')
            if data_formatada.strftime('%m/%Y') == mes_selecionado:
                extrato.append(linha)
        except ValueError:
            continue  # Ignora erros de formatação de data

    if not extrato:
        await query.message.edit_text(f"📅 Nenhum lançamento encontrado para {mes_selecionado}.")
        return

    mensagem = f"📅 Extrato de {mes_selecionado}:\n"
    for linha in extrato:
        mensagem += f"{linha[0]} - {linha[1]}: R$ {linha[2]}\n"

    await query.message.edit_text(mensagem)

# Exibir meses disponíveis para o relatório de gastos por categoria
async def selecionar_mes_categoria(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    dados = aba.get_all_values()[1:]  # Pega todas as linhas, ignorando o cabeçalho

    meses_disponiveis = set()
    for linha in dados:
        if len(linha) < 3:
            continue  # Ignora linhas incompletas
        data = linha[0]
        try:
            data_formatada = datetime.strptime(data, '%d/%m/%Y %H:%M:%S')
            meses_disponiveis.add(data_formatada.strftime('%m/%Y'))  # Formato MM/AAAA
        except ValueError:
            continue  # Ignora erros de formatação de data

    if not meses_disponiveis:
        await query.message.edit_text("📊 Nenhum gasto registrado para categorias.")
        return

    # Criar botões com os meses disponíveis
    meses_ordenados = sorted(meses_disponiveis, key=lambda x: datetime.strptime(x, '%m/%Y'), reverse=True)
    keyboard = [[InlineKeyboardButton(mes, callback_data=f"categoria_mes_{mes}")] for mes in meses_ordenados]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text("📊 Selecione o mês para ver os gastos por categoria:", reply_markup=reply_markup)

    from collections import defaultdict

# Exibir gastos por categoria no mês selecionado
async def relatorio_categoria_por_mes(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    dados = aba.get_all_values()[1:]  # Pega todas as linhas, ignorando o cabeçalho
    mes_selecionado = query.data.replace("categoria_mes_", "")  # Remove o prefixo para obter o mês (MM/AAAA)

    categorias = defaultdict(float)
    for linha in dados:
        if len(linha) < 4:
            continue  # Ignora linhas incompletas
        data, descricao, valor, categoria, *resto = linha
        try:
            data_formatada = datetime.strptime(data, '%d/%m/%Y %H:%M:%S')
            if data_formatada.strftime('%m/%Y') == mes_selecionado:
                categorias[categoria] += float(valor.replace(',', '.'))
        except ValueError:
            continue  # Ignora erros de formatação de data

    if not categorias:
        await query.message.edit_text(f"📊 Nenhum gasto registrado para {mes_selecionado}.")
        return

    mensagem = f"📊 Gastos por categoria em {mes_selecionado}:\n"
    for cat, total in categorias.items():
        mensagem += f"- {cat}: R$ {total:.2f}\n"

    await query.message.edit_text(mensagem)




    # Carregar categorias e cartões salvos na planilha
def carregar_configuracoes():
    categorias = aba_categorias.col_values(1) if aba_categorias else []
    cartoes = aba_cartoes.col_values(1) if aba_cartoes else []
    return categorias, cartoes

# Atualizar categorias e cartões ao iniciar o bot
CATEGORIAS, CARTOES = carregar_configuracoes()





# Configuração do bot
if __name__ == '__main__':
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_gasto))
    app.add_handler(CallbackQueryHandler(registrar_categoria, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(registrar_pagamento, pattern="^pag_"))
    app.add_handler(CallbackQueryHandler(registrar_cartao, pattern="^cart_"))
    app.add_handler(CallbackQueryHandler(botao_menu, pattern="^(saldo|extrato|categoria|exportar)$"))
    app.add_handler(CallbackQueryHandler(extrato_por_mes, pattern="^extrato_mes_"))
    app.add_handler(CallbackQueryHandler(relatorio_categoria_por_mes, pattern="^categoria_mes_"))

    app.run_polling()
