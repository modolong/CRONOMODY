# -*- coding: utf-8 -*-
"""
CRONOMODY - Plataforma Inteligente de Estudos
===============================================
Aplicativo completo em Streamlit para gestão de estudos com:
- Dashboard com KPIs e mapa de calor de constância
- Cronograma com pesos automáticos e modo ciclo de estudos
- Importador de editais/materiais (PDF/TXT) com geração de flashcards e questões
- Flashcards com repetição espaçada (algoritmo SM-2)
- Simulador de questões com relatório de desempenho
- Cronômetro Pomodoro
- Relatórios semanais e curva de esquecimento de Ebbinghaus

Autor: Engenharia de Software Educacional
Banco de dados: Neon (PostgreSQL na nuvem) - sincronizado entre dispositivos
"""

import streamlit as st
try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, date, timedelta
import json
import random
import time
import os
import re
import io
import base64
import calendar as calendar_lib

# Extração de PDF (pypdf é o sucessor mantido do PyPDF2)
try:
    from pypdf import PdfReader
except ImportError:
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        PdfReader = None

# SDK oficial da Anthropic (opcional) - usado no modo "Máxima Precisão (IA)".
# Se não estiver instalado, o app funciona normalmente no modo heurístico local.
try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

# Componente de listas arrastáveis (drag-and-drop), usado no Quadro de Cronograma
# estilo Trello. Se não estiver instalado, o app cai automaticamente para um
# modo alternativo de reorganização por seletor (sem prejuízo funcional).
try:
    from streamlit_sortables import sort_items
except ImportError:
    sort_items = None

# bcrypt - usado para hashing seguro de senhas no sistema de autenticação.
# Diferente dos componentes acima, este é OBRIGATÓRIO: sem ele o app bloqueia
# o acesso com uma mensagem clara, em vez de rebaixar silenciosamente a segurança.
try:
    import bcrypt
except ImportError:
    bcrypt = None

# =============================================================================
# CONFIGURAÇÃO GERAL DA PÁGINA
# =============================================================================
st.set_page_config(
    page_title="CRONOMODY",
    page_icon="⏱️",
    layout="wide",
    initial_sidebar_state="expanded",
)

def obter_dsn_neon() -> str:
    """
    Obtém a string de conexão do banco Neon (Postgres), na ordem:
    1) st.secrets["NEON_DATABASE_URL"] (recomendado - .streamlit/secrets.toml ou secrets do host)
    2) variável de ambiente NEON_DATABASE_URL ou DATABASE_URL
    Formato esperado (fornecido pelo painel do Neon):
    postgresql://usuario:senha@ep-xxxxx.us-east-2.aws.neon.tech/nomedobanco?sslmode=require
    """
    try:
        if "NEON_DATABASE_URL" in st.secrets:
            return st.secrets["NEON_DATABASE_URL"]
    except Exception:
        pass
    return os.environ.get("NEON_DATABASE_URL") or os.environ.get("DATABASE_URL") or ""

# =============================================================================
# SISTEMA DE TEMAS DINÂMICOS (paleta de cores selecionável pelo usuário)
# =============================================================================
# Cada tema define cores de fundo, destaque (accent) e texto. Temas "escuros"
# usam texto claro; temas "claros" usam texto escuro - a regra de contraste é
# aplicada automaticamente pela função gerar_css_tema() com base em is_dark.
THEMES = {
    "Vermelho Bordô (Padrão)": {
        "bg1": "#2B0A12", "bg2": "#3D0F1A", "bg3": "#1C0509",
        "panel": "23, 10, 15", "accent": "#B23A5C", "accent2": "#7A1E36",
        "text_main": "#F5E6EA", "text_muted": "#D9AEB9", "is_dark": True,
    },
    "Azul Escuro": {
        "bg1": "#16223E", "bg2": "#0B1120", "bg3": "#070C17",
        "panel": "23, 34, 59", "accent": "#5B8DEF", "accent2": "#3E63C7",
        "text_main": "#E6EBF5", "text_muted": "#93A4C3", "is_dark": True,
    },
    "Verde Musgo": {
        "bg1": "#1E301F", "bg2": "#101B12", "bg3": "#0A130B",
        "panel": "23, 42, 26", "accent": "#5E9463", "accent2": "#3C6B40",
        "text_main": "#E8F0E9", "text_muted": "#A9C2AC", "is_dark": True,
    },
    "Laranja": {
        "bg1": "#3D2410", "bg2": "#2A1506", "bg3": "#190C03",
        "panel": "61, 32, 10", "accent": "#E07A2C", "accent2": "#B85A18",
        "text_main": "#FBEDE0", "text_muted": "#E0B792", "is_dark": True,
    },
    "Butter Yellow": {
        "bg1": "#FFF7DE", "bg2": "#FFF0BF", "bg3": "#FFE9A6",
        "panel": "255, 250, 230", "accent": "#C9971A", "accent2": "#A87A0E",
        "text_main": "#4A3B0A", "text_muted": "#7A6A2E", "is_dark": False,
    },
    "Azul Claro": {
        "bg1": "#EAF4FF", "bg2": "#D8EBFF", "bg3": "#C6E0FF",
        "panel": "232, 244, 255", "accent": "#2E6FCC", "accent2": "#1E4E96",
        "text_main": "#0F2B4A", "text_muted": "#3E5A78", "is_dark": False,
    },
    "Rosa Bebê": {
        "bg1": "#FFEEF3", "bg2": "#FFDCE6", "bg3": "#FFCADA",
        "panel": "255, 238, 243", "accent": "#D6739C", "accent2": "#B14A78",
        "text_main": "#4A1E2E", "text_muted": "#7A4B5C", "is_dark": False,
    },
}
TEMA_PADRAO = "Vermelho Bordô (Padrão)"


def gerar_css_tema(nome_tema: str) -> str:
    """Gera o CSS customizado (glassmorphism + bordas arredondadas) para o tema selecionado."""
    t = THEMES.get(nome_tema, THEMES[TEMA_PADRAO])
    sombra = "rgba(0,0,0,0.35)" if t["is_dark"] else "rgba(60,60,60,0.18)"
    borda = "rgba(255,255,255,0.08)" if t["is_dark"] else "rgba(0,0,0,0.07)"
    botao_texto = "#FFFFFF" if t["is_dark"] else "#FFFFFF"
    return f"""
<style>
:root {{
    --cm-accent: {t['accent']};
    --cm-accent2: {t['accent2']};
    --cm-text-main: {t['text_main']};
    --cm-text-muted: {t['text_muted']};
    --cm-glass-border: {borda};
}}
html, body, [class*="css"] {{
    font-family: -apple-system, "Segoe UI", "Inter", Roboto, Helvetica, Arial, sans-serif;
}}
.stApp {{
    background: radial-gradient(circle at 15% 0%, {t['bg1']} 0%, {t['bg2']} 45%, {t['bg3']} 100%);
    color: var(--cm-text-main);
}}
section[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, {t['bg1']} 0%, {t['bg3']} 100%);
    border-right: 1px solid var(--cm-glass-border);
}}
div[data-testid="stVerticalBlockBorderWrapper"],
div[data-testid="stExpander"],
div[data-testid="stForm"] {{
    background: rgba({t['panel']}, 0.55);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    border: 1px solid var(--cm-glass-border);
    border-radius: 18px;
    box-shadow: 0 8px 30px {sombra};
}}
div[data-testid="stMetric"] {{
    background: rgba({t['panel']}, 0.6);
    backdrop-filter: blur(10px);
    border: 1px solid var(--cm-glass-border);
    border-radius: 16px;
    padding: 14px 16px;
    box-shadow: 0 6px 20px {sombra};
}}
div[data-testid="stMetricValue"] {{ color: var(--cm-accent); }}
div[data-testid="stMetricLabel"] {{ color: var(--cm-text-muted); }}
.stButton > button {{
    border-radius: 12px;
    border: 1px solid var(--cm-glass-border);
    background: linear-gradient(135deg, var(--cm-accent), var(--cm-accent2));
    color: {botao_texto};
    font-weight: 600;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
}}
.stButton > button:hover {{
    transform: translateY(-1px);
    box-shadow: 0 6px 18px rgba(0,0,0,0.25);
}}
.stButton > button p {{ color: {botao_texto} !important; }}
input, textarea, select, .stTextInput input, .stSelectbox div, .stTextArea textarea {{
    border-radius: 10px !important;
    color: var(--cm-text-main) !important;
}}
h1, h2, h3, h4, p, label, span, div {{ color: var(--cm-text-main); }}
h1, h2, h3 {{ letter-spacing: -0.01em; }}
.cm-hero {{
    background: linear-gradient(135deg, rgba({t['panel']},0.4), rgba({t['panel']},0.7));
    border: 1px solid var(--cm-glass-border);
    border-radius: 22px;
    padding: 28px 32px;
    backdrop-filter: blur(16px);
    box-shadow: 0 10px 40px {sombra};
    margin-bottom: 18px;
}}
.cm-hero h1 {{ margin: 0 0 4px 0; font-size: 1.8rem; color: var(--cm-text-main); }}
.cm-hero p {{ margin: 0; color: var(--cm-text-muted); }}
.cm-card {{
    background: rgba({t['panel']}, 0.6);
    border: 1px solid var(--cm-glass-border);
    border-radius: 14px;
    padding: 12px 16px;
    margin-bottom: 8px;
    backdrop-filter: blur(8px);
    color: var(--cm-text-main);
}}
.cm-badge {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 600;
    background: rgba({t['panel']}, 0.9);
    color: var(--cm-accent);
    border: 1px solid var(--cm-accent);
}}
</style>
"""

# =============================================================================
# CAMADA DE BANCO DE DADOS (Neon - PostgreSQL na nuvem)
# =============================================================================
# Trocamos o SQLite local por um banco Postgres hospedado no Neon, garantindo
# que os dados do usuário (cursos, matérias, flashcards, questões, decks,
# provas, cronogramas, métricas) sejam sincronizados entre dispositivos: o
# mesmo login acessa os mesmos dados de qualquer navegador/computador/celular,
# pois tudo fica em um único banco na nuvem em vez de um arquivo local.


@st.cache_resource(show_spinner=False)
def obter_conexao_streamlit():
    """
    Cria (uma única vez por processo do servidor) a conexão gerenciada pelo
    Streamlit via st.connection("sql", ...), que usa SQLAlchemy por baixo dos
    panos e mantém um pool de conexões reaproveitáveis com o Neon - evitando
    o custo de abrir uma conexão TCP/TLS nova a cada consulta.
    """
    dsn = obter_dsn_neon()
    if not dsn:
        st.error(
            "🔌 Não foi possível conectar ao banco de dados Neon: nenhuma string de conexão "
            "encontrada. Configure `NEON_DATABASE_URL` em `.streamlit/secrets.toml` (ou como "
            "variável de ambiente) com a Connection String fornecida pelo painel do Neon "
            "(Dashboard → Connection Details), no formato:\n\n"
            "`postgresql://usuario:senha@ep-xxxxx-pooler.regiao.aws.neon.tech/nomedobanco?sslmode=require`"
        )
        st.stop()
    return st.connection("neon_db", type="sql", url=dsn)


def get_conn():
    """
    Obtém uma conexão psycopg2 "crua" a partir do pool gerenciado pelo
    st.connection (via SQLAlchemy). O restante do app (run_query/df_query)
    continua usando a mesma API psycopg2 de sempre - só a origem da conexão
    mudou, então fechar essa conexão (conn.close()) devolve-a ao pool em vez
    de encerrar a conexão TCP, que é reaproveitada na próxima consulta.
    """
    conexao_streamlit = obter_conexao_streamlit()
    return conexao_streamlit.engine.raw_connection()


def init_db():
    """Cria todas as tabelas necessárias caso ainda não existam."""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            is_admin BOOLEAN DEFAULT FALSE,
            display_name TEXT,
            foto_perfil TEXT,
            xp INTEGER DEFAULT 0,
            nivel INTEGER DEFAULT 1,
            streak INTEGER DEFAULT 0,
            ultimo_login TEXT,
            status_atual TEXT DEFAULT '',
            ultimo_visto TEXT
        );

        CREATE TABLE IF NOT EXISTS courses (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            name TEXT NOT NULL,
            exam_date TEXT,
            weekly_hours REAL DEFAULT 20,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE (user_id, name)
        );

        CREATE TABLE IF NOT EXISTS subjects (
            id SERIAL PRIMARY KEY,
            course_id INTEGER,
            name TEXT NOT NULL,
            importance INTEGER DEFAULT 3,
            difficulty INTEGER DEFAULT 3,
            FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS flashcards (
            id SERIAL PRIMARY KEY,
            subject_id INTEGER,
            front TEXT NOT NULL,
            back TEXT NOT NULL,
            ease REAL DEFAULT 2.5,
            review_interval REAL DEFAULT 0,
            repetitions INTEGER DEFAULT 0,
            due_date TEXT,
            last_review TEXT,
            created_at TEXT,
            source TEXT DEFAULT 'manual',
            FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS questions (
            id SERIAL PRIMARY KEY,
            subject_id INTEGER,
            statement TEXT NOT NULL,
            option_a TEXT, option_b TEXT, option_c TEXT, option_d TEXT, option_e TEXT,
            correct_option TEXT,
            explanation TEXT,
            priority REAL DEFAULT 1.0,
            created_at TEXT,
            source TEXT DEFAULT 'manual',
            FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS question_attempts (
            id SERIAL PRIMARY KEY,
            question_id INTEGER,
            subject_id INTEGER,
            is_correct INTEGER,
            timestamp TEXT,
            FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS flashcard_reviews (
            id SERIAL PRIMARY KEY,
            flashcard_id INTEGER,
            quality INTEGER,
            timestamp TEXT,
            FOREIGN KEY (flashcard_id) REFERENCES flashcards(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS study_log (
            id SERIAL PRIMARY KEY,
            log_date TEXT,
            subject_id INTEGER,
            minutes REAL,
            activity_type TEXT
        );

        CREATE TABLE IF NOT EXISTS schedule_board (
            course_id INTEGER PRIMARY KEY,
            board_json TEXT,
            updated_at TEXT,
            FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS decks (
            id SERIAL PRIMARY KEY,
            subject_id INTEGER,
            name TEXT NOT NULL,
            topic TEXT,
            color TEXT DEFAULT '#5B8DEF',
            created_at TEXT,
            FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS exams (
            id SERIAL PRIMARY KEY,
            course_id INTEGER,
            name TEXT NOT NULL,
            exam_date TEXT,
            location TEXT,
            color TEXT DEFAULT '#5B8DEF',
            alert_days_before INTEGER DEFAULT 7,
            created_at TEXT,
            FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS app_settings (
            user_id INTEGER PRIMARY KEY,
            user_name TEXT DEFAULT 'Estudante',
            theme TEXT DEFAULT 'Vermelho Bordô (Padrão)',
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            title TEXT NOT NULL,
            description TEXT,
            subject_name TEXT,
            task_date TEXT,
            status TEXT DEFAULT 'pendente',
            created_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS daily_logs (
            user_id INTEGER,
            log_date TEXT,
            agua_copos INTEGER DEFAULT 0,
            humor TEXT,
            notas TEXT DEFAULT '',
            observacoes TEXT DEFAULT '',
            PRIMARY KEY (user_id, log_date),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS monthly_notes (
            user_id INTEGER,
            year_month TEXT,
            atencao_especial TEXT DEFAULT '',
            PRIMARY KEY (user_id, year_month),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS timeline_blocks (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            block_date TEXT,
            start_time TEXT,
            end_time TEXT,
            subject_name TEXT,
            created_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    conn.commit()

    # ---- Migrações leves: adiciona colunas novas em bancos já existentes ----
    def garantir_coluna(tabela, coluna, definicao):
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
            (tabela, coluna),
        )
        if cur.fetchone() is None:
            cur.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")

    garantir_coluna("flashcards", "deck_id", "INTEGER")
    garantir_coluna("questions", "topic", "TEXT")
    garantir_coluna("questions", "banca", "TEXT")
    garantir_coluna("questions", "dificuldade", "TEXT DEFAULT 'Médio'")
    garantir_coluna("courses", "user_id", "INTEGER")
    garantir_coluna("users", "is_active", "BOOLEAN DEFAULT TRUE")
    garantir_coluna("users", "is_admin", "BOOLEAN DEFAULT FALSE")
    garantir_coluna("users", "display_name", "TEXT")
    garantir_coluna("users", "foto_perfil", "TEXT")
    garantir_coluna("users", "xp", "INTEGER DEFAULT 0")
    garantir_coluna("users", "nivel", "INTEGER DEFAULT 1")
    garantir_coluna("users", "streak", "INTEGER DEFAULT 0")
    garantir_coluna("users", "ultimo_login", "TEXT")
    garantir_coluna("users", "status_atual", "TEXT DEFAULT ''")
    garantir_coluna("users", "ultimo_visto", "TEXT")
    conn.commit()
    conn.close()


def _adaptar_placeholders(query: str) -> str:
    """
    Converte os placeholders '?' (estilo SQLite, usados em todo o código do app)
    para '%s' (estilo psycopg2/Postgres), sem precisar reescrever cada chamada
    individual espalhada pelo app. Seguro aqui porque nenhuma query deste app
    usa literalmente o caractere '?' fora de placeholders de parâmetro.
    """
    return query.replace("?", "%s")


def run_query(query, params=(), fetch=False, many=False):
    """Executa uma query de escrita (INSERT/UPDATE/DELETE) com tratamento de erros."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(_adaptar_placeholders(query), params)
        result = None
        if fetch:
            result = cur.fetchall() if many else cur.fetchone()
        conn.commit()
        return result
    except psycopg2.IntegrityError:
        conn.rollback()
        raise  # deixa o chamador tratar violações de unicidade (ex: nome duplicado)
    except psycopg2.Error as e:
        conn.rollback()
        st.error(f"Erro no banco de dados: {e}")
        return None
    finally:
        conn.close()


def df_query(query, params=()):
    """Executa uma query de leitura (SELECT) e retorna um DataFrame do pandas."""
    conn = get_conn()
    try:
        df = pd.read_sql_query(_adaptar_placeholders(query), conn, params=params)
    except Exception as e:
        conn.rollback()
        st.error(f"Erro ao consultar dados: {e}")
        df = pd.DataFrame()
    finally:
        conn.close()
    return df


if psycopg2 is None:
    st.error(
        "🔌 A biblioteca `psycopg2` (driver do Postgres/Neon) não está instalada. "
        "Rode `pip install psycopg2-binary` e reinicie o app."
    )
    st.stop()

init_db()

if bcrypt is None:
    st.error(
        "🔒 A biblioteca `bcrypt` não está instalada, e ela é obrigatória para a autenticação segura "
        "de usuários. Rode `pip install bcrypt` e reinicie o app."
    )
    st.stop()


# =============================================================================
# AUTENTICAÇÃO E MULTIUSUÁRIO
# =============================================================================
# Cada usuário tem seu próprio conjunto de cursos/frentes de estudo (e, em
# cascata, matérias, flashcards, questões, decks, provas e cronogramas) -
# tudo isolado por user_id, com senhas armazenadas apenas como hash bcrypt
# (nunca em texto puro). A sessão ativa (st.session_state.auth_user_id)
# mantém o usuário logado enquanto ele navega pelas abas do app.
#
# Observação de arquitetura: o banco agora é o Neon (Postgres hospedado na
# nuvem), então o isolamento por user_id garante tanto que um usuário nunca
# veja dados de outro QUANTO sincronização automática entre dispositivos -
# o mesmo login em qualquer navegador/computador/celular aponta para o mesmo
# banco na nuvem, sem depender de um arquivo local a um servidor específico.

def calcular_nivel(xp: int) -> int:
    """Nível sobe a cada 100 XP acumulados (nível 1 = 0-99 XP, nível 2 = 100-199 XP, ...)."""
    return max(1, int(xp // 100) + 1)


def conceder_xp(user_id: int, quantidade: int):
    """
    Concede XP a um usuário por uma ação relevante (revisão de flashcard,
    questão respondida, pomodoro concluído, etc.), recalcula o nível e
    retorna (subiu_de_nivel, novo_nivel) para a interface poder comemorar
    com st.balloons() quando apropriado.
    """
    usuario_atual = df_query("SELECT xp, nivel FROM users WHERE id = ?", (user_id,))
    if usuario_atual.empty:
        return False, 1
    xp_antigo = int(usuario_atual.iloc[0]["xp"] or 0)
    nivel_antigo = int(usuario_atual.iloc[0]["nivel"] or 1)
    novo_xp = xp_antigo + quantidade
    novo_nivel = calcular_nivel(novo_xp)
    run_query("UPDATE users SET xp = ?, nivel = ? WHERE id = ?", (novo_xp, novo_nivel, user_id))
    return novo_nivel > nivel_antigo, novo_nivel


def atualizar_streak_login(user_id: int):
    """
    Atualiza a ofensiva (dias consecutivos de acesso): incrementa se o último
    login foi ontem, reinicia para 1 se pulou um ou mais dias, e mantém se já
    logou hoje. Também atualiza ultimo_login e ultimo_visto.
    """
    usuario_atual = df_query("SELECT ultimo_login, streak FROM users WHERE id = ?", (user_id,))
    hoje = date.today()
    streak_atual = int(usuario_atual.iloc[0]["streak"] or 0) if not usuario_atual.empty else 0
    ultimo_login_str = usuario_atual.iloc[0]["ultimo_login"] if not usuario_atual.empty else None

    if ultimo_login_str:
        try:
            ultimo_login_data = datetime.fromisoformat(ultimo_login_str).date()
        except ValueError:
            ultimo_login_data = None
        if ultimo_login_data == hoje:
            pass  # já logou hoje, mantém a ofensiva como está
        elif ultimo_login_data == hoje - timedelta(days=1):
            streak_atual += 1
        else:
            streak_atual = 1
    else:
        streak_atual = 1

    run_query(
        "UPDATE users SET streak = ?, ultimo_login = ?, ultimo_visto = ? WHERE id = ?",
        (streak_atual, datetime.now().isoformat(), datetime.now().isoformat(), user_id),
    )


def atualizar_ultimo_visto(user_id: int):
    """'Heartbeat' de presença: chamado a cada carregamento de página para alimentar a Comunidade."""
    run_query("UPDATE users SET ultimo_visto = ? WHERE id = ?", (datetime.now().isoformat(), user_id))


def criar_usuario(username: str, password: str):
    """Cria um novo usuário com senha protegida por hash bcrypt. Retorna (sucesso, mensagem)."""
    username = username.strip()
    if not username or not password:
        return False, "Preencha usuário e senha."
    if len(password) < 6:
        return False, "A senha deve ter ao menos 6 caracteres."
    hash_senha = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    # O primeiro usuário do sistema (ou o e-mail configurado abaixo) vira admin automaticamente
    total_usuarios = df_query("SELECT COUNT(*) as c FROM users").iloc[0]["c"]
    eh_admin_inicial = int(total_usuarios) == 0 or username.lower() == "giomodolont@gmail.com"

    try:
        run_query(
            "INSERT INTO users (username, password_hash, created_at, is_active, is_admin, display_name) "
            "VALUES (?, ?, ?, TRUE, ?, ?)",
            (username, hash_senha, datetime.now().isoformat(), eh_admin_inicial, username),
        )
    except psycopg2.IntegrityError:
        return False, "Esse nome de usuário já está em uso."
    usuario = df_query("SELECT id FROM users WHERE username = ?", (username,))
    novo_id = int(usuario.iloc[0]["id"])
    # Cria as configurações e o curso inicial deste novo usuário
    run_query(
        "INSERT INTO app_settings (user_id, user_name, theme) VALUES (?, ?, ?) ON CONFLICT (user_id) DO NOTHING",
        (novo_id, username, TEMA_PADRAO),
    )
    run_query(
        "INSERT INTO courses (user_id, name, exam_date, weekly_hours) VALUES (?, ?, ?, ?)",
        (novo_id, "Curso Principal", (date.today() + timedelta(days=90)).isoformat(), 20),
    )
    return True, "Conta criada com sucesso!"


def verificar_login(username: str, password: str):
    """Verifica usuário/senha e status da conta. Retorna (sucesso, user_id ou mensagem)."""
    usuario = df_query("SELECT * FROM users WHERE username = ?", (username.strip(),))
    if usuario.empty:
        return False, "Usuário não encontrado."
    linha = usuario.iloc[0]
    hash_salvo = linha["password_hash"].encode("utf-8")
    if not bcrypt.checkpw(password.encode("utf-8"), hash_salvo):
        return False, "Senha incorreta."
    if not bool(linha["is_active"]):
        return False, "🚫 Esta conta está suspensa. Entre em contato com um administrador."
    user_id = int(linha["id"])
    atualizar_streak_login(user_id)
    return True, user_id


# ---- Tela de Login / Criar Conta (exibida antes de qualquer outra tela) ----
if "auth_user_id" not in st.session_state:
    st.session_state.auth_user_id = None
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

if st.session_state.auth_user_id is None:
    st.markdown(
        """<div class="cm-hero"><h1>⏱️ CRONOMODY</h1>
               <p>Sua plataforma de alta performance nos estudos. Entre ou crie sua conta para continuar.</p>
           </div>""",
        unsafe_allow_html=True,
    )
    aba_login, aba_cadastro = st.tabs(["🔑 Entrar", "🆕 Criar Conta"])

    with aba_login:
        with st.form("form_login"):
            login_user = st.text_input("Usuário")
            login_pass = st.text_input("Senha", type="password")
            entrar = st.form_submit_button("Entrar")
        if entrar:
            ok, resultado = verificar_login(login_user, login_pass)
            if ok:
                st.session_state.auth_user_id = resultado
                dados_login = df_query("SELECT is_admin FROM users WHERE id = ?", (resultado,))
                st.session_state.is_admin = bool(dados_login.iloc[0]["is_admin"]) if not dados_login.empty else False
                st.rerun()
            else:
                st.error(resultado)

    with aba_cadastro:
        with st.form("form_cadastro"):
            novo_user = st.text_input("Escolha um nome de usuário")
            nova_pass = st.text_input("Escolha uma senha (mín. 6 caracteres)", type="password")
            confirmar_pass = st.text_input("Confirme a senha", type="password")
            criar_conta = st.form_submit_button("Criar conta")
        if criar_conta:
            if nova_pass != confirmar_pass:
                st.error("As senhas não coincidem.")
            else:
                ok, msg = criar_usuario(novo_user, nova_pass)
                if ok:
                    st.success(f"{msg} Faça login na aba 'Entrar'.")
                else:
                    st.error(msg)

    st.stop()  # Bloqueia o restante do app até que o login seja concluído

USER_ID = st.session_state.auth_user_id
atualizar_ultimo_visto(USER_ID)  # heartbeat de presença para a Comunidade

# Aplica o tema visual escolhido pelo usuário logado (lido do app_settings)
config_usuario = df_query("SELECT * FROM app_settings WHERE user_id = ?", (USER_ID,))
tema_ativo = config_usuario.iloc[0]["theme"] if not config_usuario.empty else TEMA_PADRAO
st.markdown(gerar_css_tema(tema_ativo), unsafe_allow_html=True)

# Garante que este usuário tenha ao menos um curso (fallback de segurança)
if df_query("SELECT * FROM courses WHERE user_id = ?", (USER_ID,)).empty:
    run_query(
        "INSERT INTO courses (user_id, name, exam_date, weekly_hours) VALUES (?, ?, ?, ?)",
        (USER_ID, "Curso Principal", (date.today() + timedelta(days=90)).isoformat(), 20),
    )

# =============================================================================
# ESTADO DE SESSÃO (para o curso ativo, Pomodoro, etc.)
# =============================================================================
if "active_course_id" not in st.session_state:
    first_course = df_query("SELECT id FROM courses WHERE user_id = ? ORDER BY id LIMIT 1", (USER_ID,))
    st.session_state.active_course_id = int(first_course.iloc[0]["id"])

if "pomodoro_running" not in st.session_state:
    st.session_state.pomodoro_running = False
if "pomodoro_start_ts" not in st.session_state:
    st.session_state.pomodoro_start_ts = None
if "pomodoro_mode" not in st.session_state:
    st.session_state.pomodoro_mode = "foco"  # foco | pausa
if "pomodoro_cycle_count" not in st.session_state:
    st.session_state.pomodoro_cycle_count = 0
if "current_quiz" not in st.session_state:
    st.session_state.current_quiz = None
if "show_answer_map" not in st.session_state:
    st.session_state.show_answer_map = {}

# =============================================================================
# FUNÇÕES DE LÓGICA DE NEGÓCIO
# =============================================================================

def calcular_peso(importancia: int, dificuldade: int) -> float:
    """
    Fórmula de peso: dá mais força à importância do que à dificuldade,
    pois matérias importantes devem dominar o cronograma mesmo que fáceis,
    mas a dificuldade também empurra a necessidade de mais horas.
    """
    return round((importancia * 3) + (dificuldade * 2), 2)


def distribuir_horas(subjects_df: pd.DataFrame, total_horas: float) -> pd.DataFrame:
    """Distribui as horas semanais proporcionalmente ao peso de cada matéria."""
    if subjects_df.empty:
        return subjects_df
    soma_pesos = subjects_df["weight"].sum()
    if soma_pesos == 0:
        subjects_df["weekly_hours_alloc"] = 0
    else:
        subjects_df["weekly_hours_alloc"] = (
            (subjects_df["weight"] / soma_pesos) * total_horas
        ).round(2)
    return subjects_df


def calcular_desempenho_materia(subject_id: int) -> float:
    """Retorna a taxa de acerto (0 a 1) de uma matéria com base no histórico."""
    df = df_query(
        "SELECT is_correct FROM question_attempts WHERE subject_id = ?", (subject_id,)
    )
    if df.empty:
        return 0.5  # neutro, sem histórico
    return df["is_correct"].mean()


def sugerir_ordem_ciclo(subjects_df: pd.DataFrame) -> pd.DataFrame:
    """
    Modo Ciclo de Estudos: ordena as matérias por prioridade dinâmica,
    combinando peso (importância x dificuldade) com desempenho acumulado.
    Prioridade = peso * (1 - taxa_de_acerto) -> quanto pior o desempenho
    e maior o peso, mais cedo a matéria entra no ciclo.
    """
    if subjects_df.empty:
        return subjects_df
    subjects_df = subjects_df.copy()
    subjects_df["desempenho"] = subjects_df["id"].apply(calcular_desempenho_materia)
    subjects_df["prioridade_ciclo"] = (
        subjects_df["weight"] * (1 - subjects_df["desempenho"] + 0.1)
    ).round(2)
    return subjects_df.sort_values("prioridade_ciclo", ascending=False)


# ---- Quadro de Cronograma estilo Trello (arrastar e soltar) ----------------
DIAS_SEMANA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
COLUNA_LIXEIRA = "🗑️ Remover (arraste aqui para excluir)"


def carregar_board(course_id: int, subjects_df: pd.DataFrame) -> dict:
    """
    Carrega o quadro salvo do curso. Se ainda não existir um quadro salvo,
    gera um quadro inicial distribuindo as matérias pelos dias da semana
    com base nas horas semanais alocadas (fallback razoável na primeira vez).
    Formato: {"Segunda": ["Matéria A - 2h", ...], ..., "🗑️...": []}
    """
    registro = df_query("SELECT board_json FROM schedule_board WHERE course_id = ?", (course_id,))
    if not registro.empty and registro.iloc[0]["board_json"]:
        try:
            board = json.loads(registro.iloc[0]["board_json"])
            # Garante que todas as colunas padrão existam, mesmo que o board salvo seja antigo
            for dia in DIAS_SEMANA + [COLUNA_LIXEIRA]:
                board.setdefault(dia, [])
            return board
        except (json.JSONDecodeError, TypeError):
            pass

    # Quadro inicial: distribui cada matéria em um dia, com as horas alocadas no rótulo
    board = {dia: [] for dia in DIAS_SEMANA}
    if not subjects_df.empty:
        for i, row in subjects_df.reset_index(drop=True).iterrows():
            dia = DIAS_SEMANA[i % len(DIAS_SEMANA)]
            horas = row.get("weekly_hours_alloc", 0)
            board[dia].append(f"{row['name']} - {horas:.1f}h")
    board[COLUNA_LIXEIRA] = []
    return board


def salvar_board(course_id: int, board: dict):
    """Persiste o quadro de cronograma (sem os itens que caíram na lixeira) no banco."""
    board_persistir = {k: v for k, v in board.items() if k != COLUNA_LIXEIRA}
    run_query(
        """INSERT INTO schedule_board (course_id, board_json, updated_at) VALUES (?, ?, ?)
           ON CONFLICT(course_id) DO UPDATE SET board_json = excluded.board_json, updated_at = excluded.updated_at""",
        (course_id, json.dumps(board_persistir, ensure_ascii=False), datetime.now().isoformat()),
    )


def fator_urgencia_prova(exam_date_str: str) -> float:
    """
    Calcula um fator multiplicador de urgência que aumenta conforme a
    data da prova se aproxima. Usado para comprimir intervalos de revisão.
    >1 dias afastados -> fator ~1.0 (normal)
    <=7 dias -> fator até 2.5 (revisões muito mais frequentes)
    """
    if not exam_date_str:
        return 1.0
    try:
        exam_date = datetime.fromisoformat(exam_date_str).date()
    except ValueError:
        return 1.0
    dias_restantes = (exam_date - date.today()).days
    if dias_restantes <= 0:
        return 3.0
    elif dias_restantes <= 7:
        return 2.5
    elif dias_restantes <= 14:
        return 1.8
    elif dias_restantes <= 30:
        return 1.3
    return 1.0


# ---- Algoritmo SM-2 (repetição espaçada, estilo Anki) ----------------------
def sm2(quality: int, repetitions: int, ease: float, interval: float, urgencia: float = 1.0):
    """
    Implementação do algoritmo SM-2 (SuperMemo 2).
    quality: 0 (errado/difícil), 3 (bom/médio) ou 5 (fácil) - mapeado de botões Anki-like
    Retorna: (novas_repeticoes, novo_ease, novo_intervalo, nova_data_vencimento)
    """
    if quality < 3:
        # Errou ou achou difícil -> reinicia repetições, intervalo curto
        repetitions = 0
        interval = 1
    else:
        if repetitions == 0:
            interval = 1
        elif repetitions == 1:
            interval = 6
        else:
            interval = round(interval * ease, 1)
        repetitions += 1

    # Atualiza o fator de facilidade (ease factor), nunca abaixo de 1.3
    ease = ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ease = max(1.3, round(ease, 2))

    # Aplica o fator de urgência da prova (comprime intervalos se a prova está perto)
    interval_ajustado = max(1, round(interval / urgencia))
    due_date = (date.today() + timedelta(days=interval_ajustado)).isoformat()

    return repetitions, ease, interval, due_date


def registrar_estudo(subject_id, minutos, tipo):
    """Registra uma sessão de estudo no log (usado pelo mapa de calor)."""
    run_query(
        "INSERT INTO study_log (log_date, subject_id, minutes, activity_type) VALUES (?, ?, ?, ?)",
        (date.today().isoformat(), subject_id, minutos, tipo),
    )


def gerar_link_google_calendar(titulo: str, data_iso: str, descricao: str = "", local: str = "") -> str:
    """
    Gera um link de 'Adicionar evento' do Google Agenda (sem precisar de OAuth/credenciais -
    basta o usuário estar logado no Google no navegador). Cobre a integração com Google Agenda
    pedida para provas e tarefas do Planner; uma sincronização bidirecional automática exigiria
    configurar OAuth2 no Google Cloud Console, que é um passo à parte a critério do usuário.
    """
    data_obj = datetime.fromisoformat(data_iso)
    data_gcal = data_obj.strftime("%Y%m%d")
    data_gcal_fim = (data_obj + timedelta(days=1)).strftime("%Y%m%d")
    return (
        "https://calendar.google.com/calendar/render?action=TEMPLATE"
        f"&text={titulo.replace(' ', '+')}"
        f"&dates={data_gcal}/{data_gcal_fim}"
        f"&details={descricao.replace(' ', '+')}"
        f"&location={local.replace(' ', '+')}"
    )


# ---- Planner de Estudos: helpers de daily_logs, notas mensais e tarefas ---
STATUS_TAREFA_CORES = {
    "concluido": "#4C9A4C",
    "andamento": "#D4B62C",
    "pendente": "#E07A2C",
    "atrasado": "#D14848",
    "importante": "#8E5FD6",
}
STATUS_TAREFA_LABELS = {
    "concluido": "✅ Concluído",
    "andamento": "🟡 Em andamento",
    "pendente": "🟠 Pendente",
    "atrasado": "🔴 Atrasado",
    "importante": "🟣 Importante",
}


def obter_daily_log(user_id: int, log_date_str: str):
    """Retorna (criando se necessário) o registro diário de água/humor/notas do usuário para a data."""
    df = df_query("SELECT * FROM daily_logs WHERE user_id = ? AND log_date = ?", (user_id, log_date_str))
    if df.empty:
        run_query(
            """INSERT INTO daily_logs (user_id, log_date, agua_copos, humor, notas, observacoes)
               VALUES (?, ?, 0, '', '', '') ON CONFLICT (user_id, log_date) DO NOTHING""",
            (user_id, log_date_str),
        )
        df = df_query("SELECT * FROM daily_logs WHERE user_id = ? AND log_date = ?", (user_id, log_date_str))
    return df.iloc[0]


def atualizar_daily_log_campo(user_id: int, log_date_str: str, campo: str, valor):
    """Atualiza um único campo do daily_log (água, humor, notas ou observações), garantindo que a linha exista."""
    obter_daily_log(user_id, log_date_str)
    colunas_permitidas = {"agua_copos", "humor", "notas", "observacoes"}
    if campo not in colunas_permitidas:
        return
    run_query(
        f"UPDATE daily_logs SET {campo} = ? WHERE user_id = ? AND log_date = ?",
        (valor, user_id, log_date_str),
    )


def obter_nota_mensal(user_id: int, year_month: str) -> str:
    """Retorna o texto de 'atenção especial' do mês (tópicos/matérias para reforçar)."""
    df = df_query(
        "SELECT atencao_especial FROM monthly_notes WHERE user_id = ? AND year_month = ?",
        (user_id, year_month),
    )
    return df.iloc[0]["atencao_especial"] if not df.empty else ""


def salvar_nota_mensal(user_id: int, year_month: str, texto: str):
    run_query(
        """INSERT INTO monthly_notes (user_id, year_month, atencao_especial) VALUES (?, ?, ?)
           ON CONFLICT (user_id, year_month) DO UPDATE SET atencao_especial = excluded.atencao_especial""",
        (user_id, year_month, texto),
    )


# ---- Filtros de limpeza para materiais médicos (remoção de ruído) ---------
# Padrões típicos de cabeçalho/rodapé/marca d'água/avisos legais em apostilas e livros
PADROES_RUIDO = [
    r"^p[aá]gina\s*\d+", r"^\d+\s*/\s*\d+$", r"^\d{1,4}$",
    r"^www\.", r"https?://", r"^\S+@\S+\.\S+$",  # sites e e-mails isolados
    r"^©", r"todos os direitos reservados", r"^isbn", r"^copyright",
    r"confidencial", r"amostra gr[aá]tis", r"^vers[aã]o\s+demonstrativa$",
    r"n[aã]o\s+comercializ", r"reproduç[aã]o proibida", r"material\s+did[aá]tico",
    r"^cap[ií]tulo\s*\d+$", r"^sum[aá]rio$", r"^[\-_=]{3,}$", r"^anexo\s*[iv\d]+$",
    r"^edi[cç][aã]o\s*:?", r"impresso no brasil", r"todos os direitos autorais",
]
PADROES_RUIDO_RE = re.compile("|".join(PADROES_RUIDO), re.IGNORECASE)

# Vocabulário-âncora para validar relevância clínica/médica de uma frase.
# Frases sem nenhum destes indícios são tratadas como ruído/contexto não essencial.
TERMOS_MEDICOS = [
    "diagnóstic", "tratamento", "sintoma", "síndrome", "doença", "paciente",
    "clínic", "fisiopatolog", "farmac", "anatôm", "anatomia", "patolog",
    "terapêutic", "cirurg", "exame", "prognós", "etiolog", "epidemiolog",
    "hospital", "medicament", "dose", "posologia", "infec", "inflama",
    "tumor", "câncer", "neoplas", "cardíac", "cardiovascular", "pulmonar",
    "respirat", "renal", "hepátic", "neurológ", "neuronal", "endócrin",
    "hormôn", "vacina", "vírus", "bactéria", "antibiótic", "lesão",
    "biópsia", "histológic", "célula", "tecido", "órgão", "sangue",
    "sistema imun", "músculo", "esquelétic", "reflexo", "artéria", "veia",
    "gestaç", "pediátri", "geriátri", "psiquiátri", "ortopéd", "dermatológ",
    "oncológ", "metaból", "fisiológ", "anestes", "vacinaç", "imunológ",
]
SUFIXOS_MEDICOS = (
    "ite", "ose", "emia", "patia", "ectomia", "oma", "algia", "grafia",
    "terapia", "plastia", "scopia", "trofia", "gênese",
)


def eh_ruido(linha: str) -> bool:
    """Detecta se uma linha é cabeçalho, rodapé, numeração de página ou marca d'água."""
    l = linha.strip()
    if not l or len(l) <= 3:
        return True
    if PADROES_RUIDO_RE.search(l):
        return True
    # Linhas curtas totalmente em maiúsculas tendem a ser cabeçalhos/títulos repetidos de página
    if l.isupper() and len(l.split()) <= 3:
        return True
    return False


def eh_conteudo_medico(frase: str) -> bool:
    """
    Heurística que valida se uma frase é essencialmente conteúdo médico
    (e não ruído editorial, institucional ou administrativo do material).
    """
    f = frase.lower()
    if any(termo in f for termo in TERMOS_MEDICOS):
        return True
    for p in f.split():
        p_limpo = p.strip(".,;:()")
        if len(p_limpo) > 7 and p_limpo.endswith(SUFIXOS_MEDICOS):
            return True
    return False


def remover_cabecalhos_rodapes_repetidos(paginas: list) -> list:
    """
    Detecta linhas que se repetem de forma idêntica em várias páginas do PDF
    (típico de cabeçalhos, rodapés e marcas d'água institucionais) e as remove
    de todas as ocorrências, preservando apenas o conteúdo único de cada página.
    """
    if len(paginas) < 2:
        return paginas
    contagem = {}
    for pagina in paginas:
        linhas_unicas = {l.strip() for l in pagina.split("\n") if l.strip()}
        for l in linhas_unicas:
            contagem[l] = contagem.get(l, 0) + 1
    # Considera "repetida" (logo, ruído) uma linha presente em ao menos 1/3 das páginas
    limite_repeticao = max(2, len(paginas) // 3)
    linhas_repetidas = {l for l, c in contagem.items() if c >= limite_repeticao and len(l) < 120}
    novas_paginas = []
    for pagina in paginas:
        linhas_filtradas = [l for l in pagina.split("\n") if l.strip() not in linhas_repetidas]
        novas_paginas.append("\n".join(linhas_filtradas))
    return novas_paginas


def limpar_texto_medico(texto: str) -> str:
    """
    Pipeline de limpeza de conteúdo: remove ruído linha a linha (rodapés,
    numeração de página, marcas d'água, avisos legais/editoriais), preservando
    apenas texto que representa efetivamente o conteúdo do material médico.
    """
    linhas = texto.split("\n")
    linhas_limpas = [l for l in linhas if not eh_ruido(l)]
    return "\n".join(linhas_limpas)


# ---- Extração e geração de conteúdo a partir de PDF/TXT --------------------
def extrair_texto_arquivo(uploaded_file):
    """
    Extrai texto de um arquivo PDF ou TXT enviado pelo usuário, já aplicando
    a limpeza de cabeçalhos/rodapés/marcas d'água. Retorna uma tupla
    (texto_limpo, estatisticas) onde estatisticas informa quantas linhas
    de ruído foram descartadas, para transparência com o usuário.
    """
    texto_bruto = ""
    try:
        if uploaded_file.type == "application/pdf" or uploaded_file.name.lower().endswith(".pdf"):
            if PdfReader is None:
                st.error("Biblioteca de leitura de PDF não encontrada. Instale 'pypdf'.")
                return "", {}
            reader = PdfReader(uploaded_file)
            paginas = [(page.extract_text() or "") for page in reader.pages]
            # 1ª etapa: remove cabeçalhos/rodapés/marcas d'água repetidos entre páginas
            paginas_sem_repeticao = remover_cabecalhos_rodapes_repetidos(paginas)
            texto_bruto = "\n".join(paginas_sem_repeticao)
        else:
            texto_bruto = uploaded_file.read().decode("utf-8", errors="ignore")
    except Exception as e:
        st.error(f"Erro ao ler o arquivo: {e}")
        return "", {}

    linhas_antes = len([l for l in texto_bruto.split("\n") if l.strip()])
    # 2ª etapa: remove ruído linha a linha (numeração, avisos legais, etc.)
    texto_limpo = limpar_texto_medico(texto_bruto)
    linhas_depois = len([l for l in texto_limpo.split("\n") if l.strip()])

    estatisticas = {
        "linhas_removidas": linhas_antes - linhas_depois,
        "linhas_antes": linhas_antes,
        "linhas_depois": linhas_depois,
    }
    return texto_limpo, estatisticas


def extrair_topicos(texto: str, max_topicos: int = 25):
    """
    Heurística leve de extração de tópicos: identifica linhas curtas,
    numeradas ou em caixa alta que costumam representar títulos de
    seções em apostilas/editais, já ignorando linhas de ruído
    (cabeçalhos, rodapés, numeração de página e marcas d'água).
    """
    linhas = [l.strip() for l in texto.split("\n") if l.strip() and not eh_ruido(l)]
    topicos = []
    padrao_numerado = re.compile(r"^(\d+[\.\)]|\u2022|-)\s*.+")
    for linha in linhas:
        palavras = linha.split()
        if not (2 <= len(palavras) <= 12):
            continue
        eh_maiuscula = linha.upper() == linha and len(linha) > 4
        eh_numerada = bool(padrao_numerado.match(linha))
        eh_titulo_capitalizado = linha.istitle()
        if eh_maiuscula or eh_numerada or eh_titulo_capitalizado:
            limpo = re.sub(r"^(\d+[\.\)]|\u2022|-)\s*", "", linha).strip()
            if limpo and limpo not in topicos:
                topicos.append(limpo)
        if len(topicos) >= max_topicos:
            break
    if not topicos:
        # Fallback: usa as primeiras frases relevantes como pseudo-tópicos
        frases = re.split(r"(?<=[\.\!\?])\s+", texto)
        topicos = [f.strip()[:80] for f in frases if len(f.strip()) > 20][:max_topicos]
    return topicos


def gerar_flashcards_de_texto(texto: str, subject_id: int, limite: int = 15, deck_id=None):
    """
    Gera flashcards automaticamente a partir do texto extraído.
    Estratégia: quebra o texto em frases, descarta ruído (cabeçalho/rodapé/
    marca d'água já foram removidos na extração) e mantém apenas frases com
    conteúdo clínico reconhecível, criando pares pergunta/resposta a partir
    delas. Retorna (quantidade_criada, quantidade_descartada_por_nao_medica).
    """
    candidatas = [f.strip() for f in re.split(r"(?<=[\.\!\?])\s+", texto) if len(f.strip()) > 30]
    frases_medicas = [f for f in candidatas if not eh_ruido(f) and eh_conteudo_medico(f)]
    descartadas = len(candidatas) - len(frases_medicas)

    criados = 0
    for frase in frases_medicas:
        if criados >= limite:
            break
        palavras = frase.split()
        if len(palavras) < 6:
            continue
        frente = f"Explique / defina: {' '.join(palavras[:8])}..."
        verso = frase
        run_query(
            """INSERT INTO flashcards
               (subject_id, front, back, ease, review_interval, repetitions, due_date, last_review, created_at, source, deck_id)
               VALUES (?, ?, ?, 2.5, 0, 0, ?, NULL, ?, 'importado', ?)""",
            (subject_id, frente, verso, date.today().isoformat(), datetime.now().isoformat(), deck_id),
        )
        criados += 1
    return criados, descartadas


def gerar_questoes_de_texto(texto: str, subject_id: int, limite: int = 10):
    """
    Gera questões de múltipla escolha (cloze) a partir do texto,
    ocultando uma palavra-chave da frase e criando distratores simples.
    Apenas frases com conteúdo clínico reconhecível (após descarte de
    ruído de cabeçalho/rodapé/marca d'água) entram como base das questões.
    Retorna (quantidade_criada, quantidade_descartada_por_nao_medica).
    """
    candidatas = [f.strip() for f in re.split(r"(?<=[\.\!\?])\s+", texto) if len(f.strip()) > 40]
    frases = [f for f in candidatas if not eh_ruido(f) and eh_conteudo_medico(f)]
    descartadas = len(candidatas) - len(frases)

    criados = 0
    # Banco de palavras-chave usado para gerar distratores plausíveis,
    # extraído apenas das frases já filtradas como conteúdo médico
    banco_palavras = list({p.strip(".,;:()") for f in frases for p in f.split() if len(p) > 5})

    for frase in frases:
        if criados >= limite:
            break
        palavras = [p for p in frase.split() if len(p.strip(".,;:()")) > 5]
        if not palavras:
            continue
        alvo = random.choice(palavras)
        alvo_limpo = alvo.strip(".,;:()")
        enunciado = frase.replace(alvo, "____________", 1)

        distratores = random.sample(
            [p for p in banco_palavras if p.lower() != alvo_limpo.lower()],
            k=min(4, max(0, len(banco_palavras) - 1)),
        )
        opcoes = distratores[:4] + [alvo_limpo]
        random.shuffle(opcoes)
        while len(opcoes) < 5:
            opcoes.append("Nenhuma das anteriores")
        letras = ["A", "B", "C", "D", "E"]
        correta = letras[opcoes.index(alvo_limpo)] if alvo_limpo in opcoes else "E"

        run_query(
            """INSERT INTO questions
               (subject_id, statement, option_a, option_b, option_c, option_d, option_e,
                correct_option, explanation, priority, created_at, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, 'importado')""",
            (
                subject_id, enunciado,
                opcoes[0], opcoes[1], opcoes[2], opcoes[3], opcoes[4],
                correta, f"Trecho original: {frase}",
                datetime.now().isoformat(),
            ),
        )
        criados += 1
    return criados, descartadas


# =============================================================================
# MODO "MÁXIMA PRECISÃO" - INTEGRAÇÃO REAL COM A API DA ANTHROPIC (CLAUDE)
# =============================================================================
# Diferente do modo heurístico acima (regex/vocabulário-âncora, 100% local e
# gratuito), este modo envia o texto já limpo (sem cabeçalhos/rodapés/marcas
# d'água) para o modelo Claude, que faz uma leitura semântica real do material
# e separa com muito mais precisão o que é conteúdo médico essencial do que é
# ruído editorial/institucional - inclusive casos ambíguos que a heurística
# local não consegue resolver (ex: uma frase de rodapé sem padrão óbvio, ou
# uma seção de "introdução institucional" escrita em tom técnico).
#
# Requer uma chave de API da Anthropic, informada pelo usuário (nunca é
# persistida no banco de dados - fica apenas em st.session_state, na memória
# da sessão atual do navegador).

ANTHROPIC_MODEL_PADRAO = "claude-sonnet-5"

SYSTEM_PROMPT_MEDICO = """Você é um especialista em curadoria de materiais médicos e educação em saúde.
Sua função é analisar um trecho de material de estudo (apostila, livro-texto ou edital da área médica)
e trabalhar ESTRITAMENTE em cima do conteúdo clínico/científico essencial dele.

Regras obrigatórias:
1. IGNORE COMPLETAMENTE qualquer cabeçalho, rodapé, numeração de página, marca d'água, sumário,
   ficha catalográfica, dados de copyright/ISBN, textos institucionais/administrativos, propagandas,
   dedicatórias, agradecimentos ou qualquer conteúdo que não seja substância médica/clínica.
2. NUNCA invente, complete ou extrapole informações que não estejam explicitamente no texto fornecido.
   Se o texto não tiver conteúdo médico suficiente, retorne listas vazias.
3. Baseie-se exclusivamente no texto fornecido nesta mensagem - não utilize conhecimento médico externo
   para preencher lacunas do material.
4. Responda SEMPRE e SOMENTE em JSON válido, sem nenhum texto, comentário ou markdown antes ou depois."""


def obter_chave_api() -> str:
    """
    Busca a chave de API da Anthropic em ordem de prioridade:
    1) st.secrets (recomendado para deploy - arquivo .streamlit/secrets.toml)
    2) variável de sessão preenchida manualmente pelo usuário na interface
    """
    try:
        if "ANTHROPIC_API_KEY" in st.secrets:
            return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        pass
    return st.session_state.get("anthropic_api_key_manual", "")


def obter_cliente_anthropic():
    """Instancia o cliente oficial da Anthropic, se a biblioteca e a chave estiverem disponíveis."""
    if Anthropic is None:
        return None
    chave = obter_chave_api()
    if not chave:
        return None
    try:
        return Anthropic(api_key=chave)
    except Exception as e:
        st.error(f"Erro ao inicializar cliente da Anthropic: {e}")
        return None


def dividir_em_blocos(texto: str, tamanho: int = 7000):
    """Divide o texto em blocos de tamanho controlado para respeitar limites de contexto/custo por chamada."""
    paragrafos = texto.split("\n")
    blocos, atual = [], ""
    for p in paragrafos:
        if len(atual) + len(p) + 1 > tamanho:
            if atual.strip():
                blocos.append(atual)
            atual = p
        else:
            atual += "\n" + p
    if atual.strip():
        blocos.append(atual)
    return blocos


def chamar_claude_json(client, modelo: str, prompt_usuario: str, max_tokens: int = 4096):
    """
    Faz uma chamada à API de Mensagens da Anthropic pedindo saída estritamente em JSON,
    com tratamento de erros (rede, limite de taxa, JSON malformado).
    """
    try:
        resposta = client.messages.create(
            model=modelo,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT_MEDICO,
            messages=[{"role": "user", "content": prompt_usuario}],
        )
        texto_resposta = "".join(
            bloco.text for bloco in resposta.content if getattr(bloco, "type", "") == "text"
        )
        texto_limpo = re.sub(r"^```(?:json)?|```$", "", texto_resposta.strip(), flags=re.MULTILINE).strip()
        return json.loads(texto_limpo)
    except json.JSONDecodeError as e:
        st.warning(f"⚠️ A IA retornou um formato inesperado em um dos blocos e ele foi ignorado ({e}).")
        return None
    except Exception as e:
        st.error(f"Erro ao chamar a API da Anthropic: {e}")
        return None


def ia_extrair_topicos_medicos(client, modelo: str, texto: str, max_topicos: int = 25):
    """Usa o Claude para identificar, com leitura semântica real, os tópicos médicos essenciais do material."""
    topicos_totais = []
    for bloco in dividir_em_blocos(texto)[:6]:  # limite de blocos para controlar custo/tempo
        prompt = f"""Analise o trecho de material médico abaixo e extraia SOMENTE os tópicos/temas
clínicos essenciais nele abordados (ignore qualquer texto institucional, editorial ou administrativo).

Responda em JSON no formato: {{"topicos": ["tópico 1", "tópico 2", ...]}}
Se não houver conteúdo médico relevante neste trecho, responda {{"topicos": []}}.

TRECHO:
\"\"\"{bloco}\"\"\""""
        resultado = chamar_claude_json(client, modelo, prompt, max_tokens=1024)
        if resultado and isinstance(resultado.get("topicos"), list):
            for t in resultado["topicos"]:
                if t and t not in topicos_totais:
                    topicos_totais.append(t)
        if len(topicos_totais) >= max_topicos:
            break
    return topicos_totais[:max_topicos]


def ia_gerar_flashcards(client, modelo: str, texto: str, subject_id: int, limite: int = 15, deck_id=None):
    """
    Gera flashcards com leitura semântica real do Claude, garantindo que cada
    par frente/verso seja fundamentado estritamente no conteúdo médico do
    trecho, com ruído editorial/institucional já excluído pelo próprio modelo.
    """
    criados, descartados_ia = 0, 0
    for bloco in dividir_em_blocos(texto):
        if criados >= limite:
            break
        restante = limite - criados
        prompt = f"""A partir do trecho de material médico abaixo, gere até {restante} flashcards de
alta qualidade para repetição espaçada (estilo Anki), cobrindo SOMENTE conceitos clínicos/médicos
essenciais explicitamente presentes no texto. Ignore qualquer conteúdo institucional, editorial,
de cabeçalho/rodapé ou administrativo - e não gere flashcard nenhum a partir dele.
Se o trecho não tiver conteúdo médico suficiente, retorne uma lista vazia.

Responda em JSON no formato:
{{"flashcards": [{{"front": "pergunta objetiva", "back": "resposta precisa e completa"}}, ...],
 "trechos_ignorados": <número inteiro de trechos não-médicos identificados e descartados>}}

TRECHO:
\"\"\"{bloco}\"\"\""""
        resultado = chamar_claude_json(client, modelo, prompt, max_tokens=4096)
        if not resultado:
            continue
        descartados_ia += int(resultado.get("trechos_ignorados", 0) or 0)
        for fc in resultado.get("flashcards", []):
            if criados >= limite:
                break
            frente, verso = fc.get("front", "").strip(), fc.get("back", "").strip()
            if not frente or not verso:
                continue
            run_query(
                """INSERT INTO flashcards
                   (subject_id, front, back, ease, review_interval, repetitions, due_date, last_review, created_at, source, deck_id)
                   VALUES (?, ?, ?, 2.5, 0, 0, ?, NULL, ?, 'ia', ?)""",
                (subject_id, frente, verso, date.today().isoformat(), datetime.now().isoformat(), deck_id),
            )
            criados += 1
    return criados, descartados_ia


def ia_gerar_questoes(client, modelo: str, texto: str, subject_id: int, limite: int = 10):
    """
    Gera questões de múltipla escolha (A-E) com gabarito comentado usando o Claude,
    fundamentadas estritamente no conteúdo médico do trecho fornecido.
    """
    criados, descartados_ia = 0, 0
    for bloco in dividir_em_blocos(texto):
        if criados >= limite:
            break
        restante = limite - criados
        prompt = f"""A partir do trecho de material médico abaixo, elabore até {restante} questões de
múltipla escolha (5 alternativas, A a E, apenas uma correta) cobrindo SOMENTE conceitos clínicos/médicos
essenciais explicitamente presentes no texto. Ignore qualquer conteúdo institucional, editorial,
de cabeçalho/rodapé ou administrativo - e não gere questão nenhuma a partir dele.
Cada questão deve ter um gabarito comentado (explicação) baseado no próprio trecho.
Se o trecho não tiver conteúdo médico suficiente, retorne uma lista vazia.

Responda em JSON no formato:
{{"questoes": [
  {{"statement": "enunciado", "option_a": "...", "option_b": "...", "option_c": "...",
    "option_d": "...", "option_e": "...", "correct_option": "A", "explanation": "gabarito comentado"}}
 ],
 "trechos_ignorados": <número inteiro de trechos não-médicos identificados e descartados>}}

TRECHO:
\"\"\"{bloco}\"\"\""""
        resultado = chamar_claude_json(client, modelo, prompt, max_tokens=4096)
        if not resultado:
            continue
        descartados_ia += int(resultado.get("trechos_ignorados", 0) or 0)
        for q in resultado.get("questoes", []):
            if criados >= limite:
                break
            if not q.get("statement") or not q.get("correct_option"):
                continue
            run_query(
                """INSERT INTO questions
                   (subject_id, statement, option_a, option_b, option_c, option_d, option_e,
                    correct_option, explanation, priority, created_at, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, 'ia')""",
                (
                    subject_id, q.get("statement", ""),
                    q.get("option_a", ""), q.get("option_b", ""), q.get("option_c", ""),
                    q.get("option_d", ""), q.get("option_e", ""),
                    str(q.get("correct_option", "A")).strip().upper()[:1],
                    q.get("explanation", ""), datetime.now().isoformat(),
                ),
            )
            criados += 1
    return criados, descartados_ia


def ia_gerar_simulado_residencia(
    client, modelo: str, mapa_subject_ids: dict, topicos_texto: str, conteudo_base: str,
    dificuldade: str, bancas: list, quantidade: int,
):
    """
    Gera um simulado completo no padrão de provas de residência médica: enunciados
    baseados em casos clínicos contextualizados, 5 alternativas (A-E), gabarito
    comentado alinhado a diretrizes médicas oficiais, focado em raciocínio clínico
    e conduta padrão-ouro. Distribui as questões entre as matérias selecionadas
    (mapa_subject_ids: {"Nome da matéria": subject_id}).

    Retorna a lista de IDs das questões recém-criadas (para montar o simulado).
    """
    nomes_materias = list(mapa_subject_ids.keys())
    bancas_texto = ", ".join(bancas) if bancas else "estilo geral de residência médica brasileira"
    base_texto = f'\n\nMATERIAL DE REFERÊNCIA (use como base quando pertinente):\n"""{conteudo_base[:6000]}"""' if conteudo_base.strip() else ""

    prompt = f"""Elabore {quantidade} questões de múltipla escolha no padrão de provas de RESIDÊNCIA MÉDICA
brasileira, cobrindo as seguintes matérias: {", ".join(nomes_materias)}.
{f"Tópicos específicos solicitados: {topicos_texto}." if topicos_texto.strip() else ""}

Regras obrigatórias:
1. Cada enunciado deve ser um CASO CLÍNICO contextualizado e realista (idade, sexo, queixa principal,
   história clínica, exame físico e/ou exames complementares quando pertinente), como nas grandes provas
   de residência (ENARE, USP-SP, UNIFESP, SUS-SP, SES-PE, etc.).
2. Nível de dificuldade: {dificuldade}.
3. Estilo de cobrança/banca a simular: {bancas_texto}.
4. Cada questão deve ter exatamente 5 alternativas (A a E), apenas uma correta, testando raciocínio
   clínico e conduta médica padrão-ouro (não decoreba isolada).
5. Cada questão deve indicar a matéria a que pertence (usando exatamente um dos nomes fornecidos) e,
   opcionalmente, um tópico específico dentro dela.
6. O gabarito comentado deve explicar por que a alternativa correta está certa E por que cada uma das
   outras está errada, de forma alinhada a diretrizes médicas oficiais.
7. Baseie-se apenas em conhecimento médico consolidado e, se fornecido, no material de referência abaixo -
   nunca invente dados de diretrizes inexistentes.{base_texto}

Responda em JSON no formato:
{{"questoes": [
  {{"materia": "nome exato de uma das matérias fornecidas", "topic": "tópico específico ou null",
    "statement": "caso clínico completo + pergunta", "option_a": "...", "option_b": "...",
    "option_c": "...", "option_d": "...", "option_e": "...", "correct_option": "A",
    "explanation": "gabarito comentado detalhado, alternativa por alternativa"}}
 ]}}"""

    resultado = chamar_claude_json(client, modelo, prompt, max_tokens=8000)
    ids_criados = []
    if not resultado:
        return ids_criados

    for q in resultado.get("questoes", []):
        materia_da_questao = q.get("materia", "").strip()
        subject_id = mapa_subject_ids.get(materia_da_questao) or list(mapa_subject_ids.values())[0]
        if not q.get("statement") or not q.get("correct_option"):
            continue
        resultado_insert = run_query(
            """INSERT INTO questions
               (subject_id, statement, option_a, option_b, option_c, option_d, option_e,
                correct_option, explanation, priority, created_at, source, topic, banca, dificuldade)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, 'ia_simulado', ?, ?, ?)
               RETURNING id""",
            (
                subject_id, q.get("statement", ""),
                q.get("option_a", ""), q.get("option_b", ""), q.get("option_c", ""),
                q.get("option_d", ""), q.get("option_e", ""),
                str(q.get("correct_option", "A")).strip().upper()[:1],
                q.get("explanation", ""), datetime.now().isoformat(),
                q.get("topic"), bancas_texto, dificuldade,
            ),
            fetch=True,
        )
        if resultado_insert:
            ids_criados.append(int(resultado_insert[0]))
    return ids_criados


def render_kpi_cards(total_questoes, total_flashcards, pct_acerto):
    col1, col2, col3 = st.columns(3)
    col1.metric("📝 Total de Questões Feitas", f"{total_questoes}")
    col2.metric("🎴 Flashcards Criados/Estudados", f"{total_flashcards}")
    col3.metric("🎯 Percentual Geral de Acertos", f"{pct_acerto:.1f}%")


def render_heatmap_constancia(user_id: int):
    """Mapa de calor de constância de estudos (estilo GitHub) para o ano corrente, escopado ao usuário logado."""
    df = df_query(
        """SELECT log_date, SUM(minutes) as minutos FROM study_log
           WHERE subject_id IN (
               SELECT s.id FROM subjects s JOIN courses c ON s.course_id = c.id WHERE c.user_id = ?
           )
           GROUP BY log_date""",
        (user_id,),
    )
    ano = date.today().year
    inicio = date(ano, 1, 1)
    fim = date(ano, 12, 31)
    todos_dias = pd.date_range(inicio, fim, freq="D")

    minutos_por_dia = {}
    if not df.empty:
        df["log_date"] = pd.to_datetime(df["log_date"])
        minutos_por_dia = dict(zip(df["log_date"], df["minutos"]))

    valores, semanas, dias_semana, textos = [], [], [], []
    for d in todos_dias:
        valores.append(minutos_por_dia.get(d, 0))
        semanas.append(int(d.strftime("%U")))
        dias_semana.append(d.weekday())
        textos.append(f"{d.date()} - {minutos_por_dia.get(d, 0):.0f} min")

    matriz = np.full((7, max(semanas) + 1), np.nan)
    texto_matriz = np.full((7, max(semanas) + 1), "", dtype=object)
    for v, s, dw, t in zip(valores, semanas, dias_semana, textos):
        matriz[dw, s] = v
        texto_matriz[dw, s] = t

    # Cor de destaque fixa (Verde Maçã) para marcar dias estudados, independente do tema ativo
    fig = go.Figure(
        data=go.Heatmap(
            z=matriz,
            text=texto_matriz,
            hoverinfo="text",
            colorscale=[[0, "rgba(135,166,41,0.08)"], [0.35, "#5C7A1E"], [1, "#87A629"]],
            showscale=False,
            xgap=2, ygap=2,
        )
    )
    fig.update_layout(
        title=f"Constância de Estudos - {ano}",
        yaxis=dict(
            tickmode="array", tickvals=list(range(7)),
            ticktext=["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"], autorange="reversed",
        ),
        xaxis=dict(title="Semana do ano"),
        height=260, margin=dict(t=40, b=20, l=40, r=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=THEMES.get(tema_ativo, THEMES[TEMA_PADRAO])["text_main"]),
    )
    st.plotly_chart(fig, use_container_width=True)


# =============================================================================
# SIDEBAR - NAVEGAÇÃO E SELEÇÃO DE CURSO (MULTI CURSOS)
# =============================================================================
st.sidebar.title("⏱️ CRONOMODY")
st.sidebar.caption("Sua plataforma de alta performance nos estudos")

# ---- Gamificação: XP, nível e ofensiva (sempre visíveis) ----
dados_gamificacao = df_query(
    "SELECT xp, nivel, streak, display_name, foto_perfil, status_atual FROM users WHERE id = ?", (USER_ID,)
)
xp_atual = int(dados_gamificacao.iloc[0]["xp"] or 0) if not dados_gamificacao.empty else 0
nivel_atual = int(dados_gamificacao.iloc[0]["nivel"] or 1) if not dados_gamificacao.empty else 1
streak_atual = int(dados_gamificacao.iloc[0]["streak"] or 0) if not dados_gamificacao.empty else 0

xp_base_nivel = (nivel_atual - 1) * 100
progresso_nivel = min(1.0, max(0.0, (xp_atual - xp_base_nivel) / 100))
st.sidebar.caption(f"🏅 Nível {nivel_atual} · {xp_atual} XP")
st.sidebar.progress(progresso_nivel, text=f"{int(progresso_nivel * 100)}% para o nível {nivel_atual + 1}")
st.sidebar.markdown(
    f'<span class="cm-badge">🔥 Ofensiva: {streak_atual} dia(s)</span>', unsafe_allow_html=True
)

# ---- Comunidade: usuários ativos nos últimos 5 minutos ----
with st.sidebar.expander("👥 Comunidade"):
    limite_online = (datetime.now() - timedelta(minutes=5)).isoformat()
    usuarios_ativos = df_query(
        """SELECT username, display_name, foto_perfil, status_atual, ultimo_visto FROM users
           WHERE ultimo_visto >= ? AND id != ? ORDER BY ultimo_visto DESC LIMIT 15""",
        (limite_online, USER_ID),
    )
    if usuarios_ativos.empty:
        st.caption("Nenhum outro colega online agora.")
    else:
        for _, u in usuarios_ativos.iterrows():
            nome_exibicao = u["display_name"] or u["username"]
            status_txt = u["status_atual"] or "sem status definido"
            st.markdown(
                f"""<div class="cm-card" style="padding:8px 12px;">
                        🟢 <b>{nome_exibicao}</b><br>
                        <span style="color:var(--cm-text-muted); font-size:0.8rem">{status_txt}</span>
                    </div>""",
                unsafe_allow_html=True,
            )

    st.divider()
    status_atual_valor = dados_gamificacao.iloc[0]["status_atual"] if not dados_gamificacao.empty else ""
    novo_status = st.text_input("Seu status atual", value=status_atual_valor or "", placeholder="Ex: Estudando Cardiologia")
    if st.button("Atualizar status"):
        run_query("UPDATE users SET status_atual = ? WHERE id = ?", (novo_status.strip(), USER_ID))
        st.success("Status atualizado!")
        st.rerun()

config_usuario = df_query("SELECT * FROM app_settings WHERE user_id = ?", (USER_ID,))
nome_usuario_atual = config_usuario.iloc[0]["user_name"] if not config_usuario.empty else "Estudante"

with st.sidebar.expander("👤 Perfil"):
    novo_nome_usuario = st.text_input("Como devemos te chamar?", value=nome_usuario_atual)
    tema_escolhido = st.selectbox(
        "🎨 Tema visual", list(THEMES.keys()),
        index=list(THEMES.keys()).index(tema_ativo) if tema_ativo in THEMES else 0,
    )
    if st.button("💾 Salvar perfil"):
        run_query(
            "UPDATE app_settings SET user_name = ?, theme = ? WHERE user_id = ?",
            (novo_nome_usuario.strip() or "Estudante", tema_escolhido, USER_ID),
        )
        st.success("Perfil atualizado!")
        st.rerun()
    st.caption("Para alterar nome de exibição, foto e status, veja a página '🙋 Meu Perfil'.")
    st.divider()
    if st.button("🚪 Sair (logout)"):
        st.session_state.auth_user_id = None
        st.session_state.active_course_id = None
        st.session_state.is_admin = False
        st.rerun()

cursos_df = df_query("SELECT * FROM courses WHERE user_id = ?", (USER_ID,))
nomes_cursos = cursos_df["name"].tolist()
ids_cursos = cursos_df["id"].tolist()

with st.sidebar.expander("📚 Modo Multi Cursos", expanded=False):
    curso_escolhido = st.selectbox(
        "Curso / Frente de estudo ativa",
        options=ids_cursos,
        format_func=lambda cid: cursos_df.loc[cursos_df["id"] == cid, "name"].values[0],
        index=ids_cursos.index(st.session_state.active_course_id)
        if st.session_state.active_course_id in ids_cursos else 0,
    )
    st.session_state.active_course_id = curso_escolhido

    novo_curso_nome = st.text_input("Novo curso/concurso", key="novo_curso_nome")
    if st.button("➕ Adicionar curso"):
        if novo_curso_nome.strip():
            try:
                run_query(
                    "INSERT INTO courses (user_id, name, exam_date, weekly_hours) VALUES (?, ?, ?, ?)",
                    (USER_ID, novo_curso_nome.strip(), (date.today() + timedelta(days=90)).isoformat(), 20),
                )
                st.success(f"Curso '{novo_curso_nome}' criado!")
                st.rerun()
            except psycopg2.IntegrityError:
                st.warning("Você já tem um curso com esse nome.")
        else:
            st.warning("Digite um nome válido para o curso.")

    st.divider()
    st.caption("✏️ Editar / excluir curso ativo")
    nome_curso_atual = cursos_df.loc[cursos_df["id"] == curso_escolhido, "name"].values[0]
    novo_nome_edicao = st.text_input("Renomear curso ativo", value=nome_curso_atual, key="renomear_curso")
    colr1, colr2 = st.columns(2)
    if colr1.button("💾 Salvar nome"):
        if novo_nome_edicao.strip():
            try:
                run_query(
                    "UPDATE courses SET name = ? WHERE id = ? AND user_id = ?",
                    (novo_nome_edicao.strip(), int(curso_escolhido), USER_ID),
                )
                st.success("Nome atualizado!")
                st.rerun()
            except psycopg2.IntegrityError:
                st.warning("Você já tem um curso com esse nome.")
        else:
            st.warning("Nome não pode ficar vazio.")

    if colr2.button("🗑️ Excluir curso", type="secondary"):
        if len(ids_cursos) <= 1:
            st.warning("Não é possível excluir o único curso existente.")
        else:
            st.session_state["confirmar_exclusao_curso"] = curso_escolhido

    if st.session_state.get("confirmar_exclusao_curso") == curso_escolhido:
        st.error(
            f"Confirma a exclusão de **{nome_curso_atual}**? Isso apagará TODAS as matérias, "
            "flashcards, questões e o cronograma associados a este curso. Ação irreversível."
        )
        colc1, colc2 = st.columns(2)
        if colc1.button("✅ Sim, excluir definitivamente"):
            # Remove registros de estudo (sem FK/cascade) associados às matérias do curso
            subjects_do_curso = df_query("SELECT id FROM subjects WHERE course_id = ?", (int(curso_escolhido),))
            for sid in subjects_do_curso["id"].tolist():
                run_query("DELETE FROM study_log WHERE subject_id = ?", (int(sid),))
            run_query("DELETE FROM schedule_board WHERE course_id = ?", (int(curso_escolhido),))
            run_query("DELETE FROM courses WHERE id = ? AND user_id = ?", (int(curso_escolhido), USER_ID))  # cascade cuida do resto
            st.session_state.active_course_id = None
            st.session_state.pop("confirmar_exclusao_curso", None)
            st.success("Curso excluído.")
            st.rerun()
        if colc2.button("❌ Cancelar"):
            st.session_state.pop("confirmar_exclusao_curso", None)
            st.rerun()

# Recarrega a lista de cursos caso alguma exclusão tenha acabado de ocorrer
cursos_df = df_query("SELECT * FROM courses WHERE user_id = ?", (USER_ID,))
ids_cursos = cursos_df["id"].tolist()
if st.session_state.active_course_id not in ids_cursos:
    st.session_state.active_course_id = int(cursos_df.iloc[0]["id"])

curso_atual = cursos_df[cursos_df["id"] == st.session_state.active_course_id].iloc[0]

opcoes_navegacao = [
    "🏠 Dashboard",
    "🗂️ Planner de Estudos",
    "📅 Cronograma, Pesos e Ciclo",
    "🗓️ Provas e Calendário",
    "📥 Importador de Editais/Materiais",
    "🎴 Flashcards (SM-2)",
    "❓ Simulador de Questões",
    "🧪 Gerador de Simulados (IA)",
    "🍅 Pomodoro",
    "📊 Relatórios e Ebbinghaus",
    "🙋 Meu Perfil",
    "🏆 Ranking",
]
if st.session_state.get("is_admin"):
    opcoes_navegacao.append("🛡️ Painel Admin")

pagina = st.sidebar.radio("Navegação", opcoes_navegacao)

st.sidebar.divider()
st.sidebar.caption(f"Curso ativo: **{curso_atual['name']}**")
if curso_atual["exam_date"]:
    dias_restantes = (datetime.fromisoformat(curso_atual["exam_date"]).date() - date.today()).days
    st.sidebar.caption(f"📆 Faltam **{dias_restantes} dias** para a prova.")

# =============================================================================
# PÁGINA 1 - DASHBOARD
# =============================================================================
if pagina == "🏠 Dashboard":
    nome_usuario = df_query("SELECT user_name FROM app_settings WHERE user_id = ?", (USER_ID,)).iloc[0]["user_name"]
    st.markdown(
        f"""<div class="cm-hero">
                <h1>Seja bem-vindo(a), {nome_usuario} 👋</h1>
                <p>Aqui está o resumo da sua performance de estudos até agora.</p>
            </div>""",
        unsafe_allow_html=True,
    )

    subquery_subjects_usuario = """(
        SELECT s.id FROM subjects s JOIN courses c ON s.course_id = c.id WHERE c.user_id = ?
    )"""

    total_questoes = df_query(
        f"SELECT COUNT(*) as c FROM question_attempts WHERE subject_id IN {subquery_subjects_usuario}",
        (USER_ID,),
    ).iloc[0]["c"]
    total_flashcards = df_query(
        f"SELECT COUNT(*) as c FROM flashcards WHERE subject_id IN {subquery_subjects_usuario}",
        (USER_ID,),
    ).iloc[0]["c"]
    acertos_df = df_query(
        f"SELECT AVG(is_correct) as media FROM question_attempts WHERE subject_id IN {subquery_subjects_usuario}",
        (USER_ID,),
    )
    pct_acerto = (acertos_df.iloc[0]["media"] or 0) * 100

    log_geral = df_query(
        f"SELECT * FROM study_log WHERE subject_id IN {subquery_subjects_usuario}", (USER_ID,)
    )
    tempo_total_min = log_geral["minutes"].sum() if not log_geral.empty else 0
    sessoes_realizadas = len(log_geral)
    dias_distintos = log_geral["log_date"].nunique() if not log_geral.empty else 0
    media_diaria_min = (tempo_total_min / dias_distintos) if dias_distintos else 0

    # ---- Linha 1: donut de aproveitamento + cards de resumo rápido ----
    col_donut, col_cards = st.columns([1, 2])
    with col_donut:
        tema_cores = THEMES.get(tema_ativo, THEMES[TEMA_PADRAO])
        cor_fundo_donut = "rgba(255,255,255,0.12)" if tema_cores["is_dark"] else "rgba(0,0,0,0.08)"
        fig_donut = go.Figure(go.Pie(
            values=[pct_acerto, max(0, 100 - pct_acerto)],
            hole=0.72, marker_colors=[tema_cores["accent"], cor_fundo_donut],
            textinfo="none", sort=False,
        ))
        fig_donut.update_layout(
            showlegend=False, height=220, margin=dict(t=10, b=10, l=10, r=10),
            annotations=[dict(text=f"<b>{pct_acerto:.0f}%</b><br><span style='font-size:11px'>acerto</span>",
                               x=0.5, y=0.5, showarrow=False, font=dict(size=22, color=tema_cores["text_main"]))],
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_donut, use_container_width=True)

    with col_cards:
        c1, c2, c3, c4 = st.columns(4)
        h, m = int(tempo_total_min // 60), int(tempo_total_min % 60)
        c1.metric("⏱️ Tempo Estudado", f"{h}h {m}min")
        c2.metric("📚 Sessões Realizadas", sessoes_realizadas)
        c3.metric("📝 Questões Respondidas", total_questoes)
        c4.metric("📅 Média Diária", f"{int(media_diaria_min)} min")

    st.divider()

    # ---- Revisões futuras (flashcards com vencimento mais próximo) ----
    st.subheader("🔮 Revisões Futuras")
    proximas = df_query(
        """SELECT f.id, f.front, f.due_date, s.name as materia FROM flashcards f
           JOIN subjects s ON f.subject_id = s.id
           WHERE s.course_id = ? AND f.due_date IS NOT NULL AND f.due_date > ?
           ORDER BY f.due_date ASC LIMIT 6""",
        (int(curso_atual["id"]), date.today().isoformat()),
    )
    if proximas.empty:
        st.caption("Nenhuma revisão futura agendada no momento.")
    else:
        for _, r in proximas.iterrows():
            colx1, colx2 = st.columns([4, 1])
            colx1.markdown(
                f"""<div class="cm-card"><span class="cm-badge">{r['materia']}</span>
                    &nbsp; {r['front'][:70]} &nbsp;
                    <span style="color:#93A4C3;font-size:0.8rem">vence em {r['due_date']}</span></div>""",
                unsafe_allow_html=True,
            )
            if colx2.button("⏩ Adiantar", key=f"adiantar_{r['id']}"):
                run_query("UPDATE flashcards SET due_date = ? WHERE id = ?", (date.today().isoformat(), int(r["id"])))
                st.success("Revisão adiantada para hoje!")
                st.rerun()

    st.divider()
    render_heatmap_constancia(USER_ID)

    st.divider()
    st.subheader("📈 Desempenho por Matéria (curso ativo)")
    subjects_df = df_query(
        "SELECT * FROM subjects WHERE course_id = ?", (int(curso_atual["id"]),)
    )
    if subjects_df.empty:
        st.info("Cadastre matérias na aba 'Cronograma, Pesos e Ciclo' para ver o desempenho aqui.")
    else:
        desempenhos = []
        for _, row in subjects_df.iterrows():
            desempenhos.append({
                "Matéria": row["name"],
                "Acerto (%)": round(calcular_desempenho_materia(row["id"]) * 100, 1),
            })
        fig = px.bar(pd.DataFrame(desempenhos), x="Matéria", y="Acerto (%)", color="Acerto (%)",
                     color_continuous_scale="Blues", range_color=[0, 100])
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

# =============================================================================
# PÁGINA - PLANNER DE ESTUDOS (Mensal / Semanal / Anual)
# =============================================================================
elif pagina == "🗂️ Planner de Estudos":
    st.title("🗂️ Planner de Estudos")

    todas_tarefas = df_query("SELECT * FROM tasks WHERE user_id = ?", (USER_ID,))
    total_tarefas = len(todas_tarefas)
    concluidas = len(todas_tarefas[todas_tarefas["status"] == "concluido"]) if not todas_tarefas.empty else 0
    pendentes = len(todas_tarefas[todas_tarefas["status"] == "pendente"]) if not todas_tarefas.empty else 0
    atrasadas = len(todas_tarefas[todas_tarefas["status"] == "atrasado"]) if not todas_tarefas.empty else 0

    cM1, cM2, cM3, cM4 = st.columns(4)
    cM1.metric("📋 Total", total_tarefas)
    cM2.metric("✅ Concluídas", concluidas)
    cM3.metric("🟠 Pendentes", pendentes)
    cM4.metric("🔴 Atrasadas", atrasadas)

    st.divider()
    aba_mensal, aba_semanal, aba_anual = st.tabs(["📅 Mensal", "🗓️ Semanal", "📆 Anual"])

    # -----------------------------------------------------------------
    # VISÃO MENSAL
    # -----------------------------------------------------------------
    with aba_mensal:
        colM1, colM2 = st.columns(2)
        mes_planner = colM1.selectbox(
            "Mês", list(range(1, 13)), index=date.today().month - 1,
            format_func=lambda m: ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
                                    "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"][m - 1],
            key="mes_planner",
        )
        ano_planner = colM2.number_input("Ano", min_value=2020, max_value=2100, value=date.today().year, step=1, key="ano_planner")
        year_month_str = f"{int(ano_planner)}-{int(mes_planner):02d}"

        tarefas_mes = df_query(
            "SELECT * FROM tasks WHERE user_id = ? AND task_date LIKE ?", (USER_ID, f"{year_month_str}-%")
        )
        contagem_por_dia = tarefas_mes.groupby("task_date").size().to_dict() if not tarefas_mes.empty else {}

        cal = calendar_lib.Calendar(firstweekday=0)
        semanas_mes = cal.monthdayscalendar(int(ano_planner), int(mes_planner))
        grid_html = "<table style='width:100%; border-collapse:separate; border-spacing:6px;'>"
        grid_html += "<tr>" + "".join(
            f"<th style='color:var(--cm-text-muted);font-weight:500;font-size:0.8rem'>{d}</th>"
            for d in ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
        ) + "</tr>"
        for semana in semanas_mes:
         grid_html += "<tr>"    
         for dia in semana:
         if dia == 0:
            grid_html += "<td></td>"
            continue

        data_iso = ...
        qtd = ...
        intensidade = ...
        ...
        grid_html += ...

    grid_html += "</tr>"

grid_html += "</table>"
st.markdown(grid_html, unsafe_allow_html=True)

st.subheader("✅ Checklist diário de matérias")
data_checklist = st.date_input(
            "Selecione o dia para o checklist", value=date.today(),
            min_value=date(int(ano_planner), int(mes_planner), 1), key="data_checklist_mensal",
        )
        data_checklist_str = data_checklist.isoformat()
        subjects_planner = df_query("SELECT * FROM subjects WHERE course_id = ?", (int(curso_atual["id"]),))
        tarefas_do_dia_checklist = df_query(
            "SELECT * FROM tasks WHERE user_id = ? AND task_date = ?", (USER_ID, data_checklist_str)
        )
        materias_ja_com_tarefa = set(tarefas_do_dia_checklist["subject_name"].tolist()) if not tarefas_do_dia_checklist.empty else set()

        if subjects_planner.empty:
            st.caption("Cadastre matérias na aba Cronograma para usar o checklist diário.")
        else:
            for _, materia in subjects_planner.iterrows():
                if materia["name"] in materias_ja_com_tarefa:
                    tarefa_existente = tarefas_do_dia_checklist[tarefas_do_dia_checklist["subject_name"] == materia["name"]].iloc[0]
                    marcado = st.checkbox(
                        materia["name"], value=tarefa_existente["status"] == "concluido",
                        key=f"chk_{materia['name']}_{data_checklist_str}",
                    )
                    novo_status_chk = "concluido" if marcado else "pendente"
                    if novo_status_chk != tarefa_existente["status"]:
                        run_query("UPDATE tasks SET status = ? WHERE id = ?", (novo_status_chk, int(tarefa_existente["id"])))
                        st.rerun()
                else:
                    marcado = st.checkbox(materia["name"], value=False, key=f"chk_{materia['name']}_{data_checklist_str}")
                    if marcado:
                        run_query(
                            """INSERT INTO tasks (user_id, title, subject_name, task_date, status, created_at)
                               VALUES (?, ?, ?, ?, 'concluido', ?)""",
                            (USER_ID, f"Estudar {materia['name']}", materia["name"], data_checklist_str, datetime.now().isoformat()),
                        )
                        st.rerun()

        st.divider()
        st.subheader("📝 Tópicos/Matérias para dar atenção especial este mês")
        nota_mensal_atual = obter_nota_mensal(USER_ID, year_month_str)
        nova_nota_mensal = st.text_area("Anotações do mês", value=nota_mensal_atual, height=100, key="nota_mensal_texto")
        if st.button("💾 Salvar anotação do mês"):
            salvar_nota_mensal(USER_ID, year_month_str, nova_nota_mensal)
            st.success("Anotação salva!")

    # -----------------------------------------------------------------
    # VISÃO SEMANAL
    # -----------------------------------------------------------------
    with aba_semanal:
        if "dia_selecionado_planner" not in st.session_state:
            st.session_state.dia_selecionado_planner = date.today().isoformat()

        col_dias, col_painel = st.columns([1, 3])
        with col_dias:
            hoje = date.today()
            inicio_semana_atual = hoje - timedelta(days=hoje.weekday())
            for i in range(7):
                dia_card = inicio_semana_atual + timedelta(days=i)
                nome_dia = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"][i]
                rotulo = f"{nome_dia[:3]} {dia_card.day:02d}"
                tipo_botao = "primary" if dia_card.isoformat() == st.session_state.dia_selecionado_planner else "secondary"
                if st.button(rotulo, key=f"dia_card_{i}", type=tipo_botao, use_container_width=True):
                    st.session_state.dia_selecionado_planner = dia_card.isoformat()
                    st.rerun()

        with col_painel:
            data_sel = datetime.fromisoformat(st.session_state.dia_selecionado_planner).date()
            nomes_dias_pt = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira",
                              "Sexta-feira", "Sábado", "Domingo"]
            nomes_meses_pt = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
                               "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
            semana_do_mes = (data_sel.day - 1) // 7 + 1
            st.subheader(f"{nomes_dias_pt[data_sel.weekday()]}, {nomes_meses_pt[data_sel.month - 1]} / Semana {semana_do_mes}")

            log_dia = obter_daily_log(USER_ID, data_sel.isoformat())

            colH, colM = st.columns(2)
            with colH:
                st.markdown("**💧 Hidratação**")
                colHa, colHb, colHc = st.columns([1, 1, 2])
                agua_atual = int(log_dia["agua_copos"] or 0)
                if colHa.button("➖", key="agua_menos"):
                    atualizar_daily_log_campo(USER_ID, data_sel.isoformat(), "agua_copos", max(0, agua_atual - 1))
                    st.rerun()
                if colHb.button("➕", key="agua_mais"):
                    atualizar_daily_log_campo(USER_ID, data_sel.isoformat(), "agua_copos", agua_atual + 1)
                    st.rerun()
                colHc.markdown(f"### {agua_atual} 🥤")
            with colM:
                st.markdown("**😊 Humor do dia**")
                opcoes_humor = ["😄 Ótimo", "🙂 Bem", "😐 Neutro", "😕 Cansado", "😣 Estressado"]
                humor_atual = log_dia["humor"] or opcoes_humor[2]
                novo_humor = st.selectbox(
                    "Humor", opcoes_humor, index=opcoes_humor.index(humor_atual) if humor_atual in opcoes_humor else 2,
                    label_visibility="collapsed", key="humor_select",
                )
                if novo_humor != humor_atual:
                    atualizar_daily_log_campo(USER_ID, data_sel.isoformat(), "humor", novo_humor)

            st.divider()
            st.markdown("**📌 Tarefas e cronograma de estudos do dia**")
            tarefas_dia = df_query(
                "SELECT * FROM tasks WHERE user_id = ? AND task_date = ? ORDER BY id", (USER_ID, data_sel.isoformat())
            )
            for _, tarefa in tarefas_dia.iterrows():
                cor = STATUS_TAREFA_CORES.get(tarefa["status"], "#5B8DEF")
                colT1, colT2, colT3, colT4 = st.columns([3, 1.3, 0.5, 0.5])
                colT1.markdown(
                    f"""<div class="cm-card" style="border-left:4px solid {cor}">
                            <b>{tarefa['title']}</b><br>
                            <span style="color:var(--cm-text-muted); font-size:0.8rem">{tarefa['subject_name'] or ''}</span>
                        </div>""",
                    unsafe_allow_html=True,
                )
                novo_status_tarefa = colT2.selectbox(
                    "Status", list(STATUS_TAREFA_LABELS.keys()),
                    index=list(STATUS_TAREFA_LABELS.keys()).index(tarefa["status"]) if tarefa["status"] in STATUS_TAREFA_LABELS else 2,
                    format_func=lambda s: STATUS_TAREFA_LABELS[s], key=f"status_tarefa_{tarefa['id']}",
                    label_visibility="collapsed",
                )
                if novo_status_tarefa != tarefa["status"]:
                    run_query("UPDATE tasks SET status = ? WHERE id = ?", (novo_status_tarefa, int(tarefa["id"])))
                    if novo_status_tarefa == "concluido":
                        subiu_nivel, nivel_novo = conceder_xp(USER_ID, 10)
                        if subiu_nivel:
                            st.balloons()
                    st.rerun()
                url_gcal_tarefa = gerar_link_google_calendar(
                    tarefa["title"], tarefa["task_date"], descricao=tarefa["subject_name"] or ""
                )
                colT3.link_button("📅", url_gcal_tarefa, use_container_width=True)
                if colT4.button("🗑️", key=f"del_tarefa_{tarefa['id']}"):
                    run_query("DELETE FROM tasks WHERE id = ?", (int(tarefa["id"]),))
                    st.rerun()

            with st.form(f"form_nova_tarefa_{data_sel.isoformat()}", clear_on_submit=True):
                colNT1, colNT2 = st.columns([3, 1])
                titulo_tarefa = colNT1.text_input("Nova tarefa")
                materia_tarefa = colNT2.text_input("Matéria (opcional)")
                add_tarefa = st.form_submit_button("➕ Adicionar tarefa")
                if add_tarefa and titulo_tarefa.strip():
                    run_query(
                        """INSERT INTO tasks (user_id, title, subject_name, task_date, status, created_at)
                           VALUES (?, ?, ?, ?, 'pendente', ?)""",
                        (USER_ID, titulo_tarefa.strip(), materia_tarefa.strip(), data_sel.isoformat(), datetime.now().isoformat()),
                    )
                    st.rerun()

            st.divider()
            st.markdown("**⏱️ Linha do tempo de estudos**")
            blocos_dia = df_query(
                "SELECT * FROM timeline_blocks WHERE user_id = ? AND block_date = ? ORDER BY start_time",
                (USER_ID, data_sel.isoformat()),
            )
            for _, bloco in blocos_dia.iterrows():
                colB1, colB2 = st.columns([4, 0.6])
                colB1.markdown(f"🕐 **{bloco['start_time']} – {bloco['end_time']}** · {bloco['subject_name']}")
                if colB2.button("🗑️", key=f"del_bloco_{bloco['id']}"):
                    run_query("DELETE FROM timeline_blocks WHERE id = ?", (int(bloco["id"]),))
                    st.rerun()
            with st.form(f"form_novo_bloco_{data_sel.isoformat()}", clear_on_submit=True):
                colBT1, colBT2, colBT3 = st.columns(3)
                hora_ini = colBT1.time_input("Início")
                hora_fim = colBT2.time_input("Fim")
                materia_bloco = colBT3.text_input("Matéria")
                add_bloco = st.form_submit_button("➕ Adicionar bloco")
                if add_bloco and materia_bloco.strip():
                    run_query(
                        """INSERT INTO timeline_blocks (user_id, block_date, start_time, end_time, subject_name, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (USER_ID, data_sel.isoformat(), hora_ini.strftime("%H:%M"), hora_fim.strftime("%H:%M"),
                         materia_bloco.strip(), datetime.now().isoformat()),
                    )
                    st.rerun()

            st.divider()
            st.markdown("**🧠 Notas & pensamentos / resumos**")
            notas_valor = st.text_area(
                "Anotações rápidas (salvas automaticamente ao sair do campo)",
                value=log_dia["notas"] or "", height=100, key=f"notas_{data_sel.isoformat()}",
                on_change=lambda: atualizar_daily_log_campo(
                    USER_ID, data_sel.isoformat(), "notas", st.session_state[f"notas_{data_sel.isoformat()}"]
                ),
            )

            st.markdown("**🗒️ Observações de estudos do dia**")
            observ_valor = st.text_area("Observações gerais", value=log_dia["observacoes"] or "", height=80, key="observacoes_dia")
            if st.button("💾 Salvar observações"):
                atualizar_daily_log_campo(USER_ID, data_sel.isoformat(), "observacoes", observ_valor)
                st.success("Observações salvas!")

    # -----------------------------------------------------------------
    # VISÃO ANUAL
    # -----------------------------------------------------------------
    with aba_anual:
        ano_anual = st.number_input("Ano", min_value=2020, max_value=2100, value=date.today().year, step=1, key="ano_anual_planner")
        tarefas_ano = df_query(
            "SELECT * FROM tasks WHERE user_id = ? AND task_date LIKE ? AND status = 'concluido'",
            (USER_ID, f"{int(ano_anual)}-%"),
        )
        if tarefas_ano.empty:
            st.info("Nenhuma tarefa concluída registrada neste ano ainda.")
        else:
            tarefas_ano["mes"] = tarefas_ano["task_date"].str.slice(5, 7).astype(int)
            contagem_mensal = tarefas_ano.groupby("mes").size().reindex(range(1, 13), fill_value=0)
            nomes_meses_curto = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
            fig_anual = px.bar(
                x=nomes_meses_curto, y=contagem_mensal.values,
                labels={"x": "Mês", "y": "Tarefas concluídas"}, title=f"Tarefas concluídas por mês - {int(ano_anual)}",
            )
            fig_anual.update_traces(marker_color="#5B8DEF")
            fig_anual.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig_anual, use_container_width=True)
        render_heatmap_constancia(USER_ID)

# =============================================================================
# PÁGINA 2 - CRONOGRAMA, PESOS E CICLO DE ESTUDOS
# =============================================================================
elif pagina == "📅 Cronograma, Pesos e Ciclo":
    st.title("📅 Cronograma, Pesos e Ciclo de Estudos")

    with st.expander("⚙️ Configurações do curso", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            nova_data_prova = st.date_input(
                "Data da prova",
                value=datetime.fromisoformat(curso_atual["exam_date"]).date()
                if curso_atual["exam_date"] else date.today() + timedelta(days=90),
            )
        with c2:
            novas_horas = st.number_input(
                "Total de horas semanais disponíveis", min_value=1.0, max_value=100.0,
                value=float(curso_atual["weekly_hours"]), step=1.0,
            )
        if st.button("💾 Salvar configurações do curso"):
            run_query(
                "UPDATE courses SET exam_date = ?, weekly_hours = ? WHERE id = ?",
                (nova_data_prova.isoformat(), novas_horas, int(curso_atual["id"])),
            )
            st.success("Configurações atualizadas!")
            st.rerun()

    st.subheader("➕ Cadastrar nova matéria")
    with st.form("form_nova_materia", clear_on_submit=True):
        col1, col2, col3 = st.columns([2, 1, 1])
        nome_materia = col1.text_input("Nome da matéria")
        importancia = col2.slider("Importância", 1, 5, 3)
        dificuldade = col3.slider("Dificuldade", 1, 5, 3)
        enviado = st.form_submit_button("Adicionar matéria")
        if enviado:
            if nome_materia.strip():
                run_query(
                    "INSERT INTO subjects (course_id, name, importance, difficulty) VALUES (?, ?, ?, ?)",
                    (int(curso_atual["id"]), nome_materia.strip(), importancia, dificuldade),
                )
                st.success(f"Matéria '{nome_materia}' cadastrada!")
                st.rerun()
            else:
                st.warning("Informe um nome para a matéria.")

    st.divider()
    subjects_df = df_query("SELECT * FROM subjects WHERE course_id = ?", (int(curso_atual["id"]),))

    if subjects_df.empty:
        st.info("Nenhuma matéria cadastrada ainda para este curso.")
    else:
        subjects_df["weight"] = subjects_df.apply(
            lambda r: calcular_peso(r["importance"], r["difficulty"]), axis=1
        )
        subjects_df = distribuir_horas(subjects_df, float(curso_atual["weekly_hours"]))

        st.subheader("📋 Tabela de matérias, pesos e horas semanais")
        tabela_exibicao = subjects_df[
            ["name", "importance", "difficulty", "weight", "weekly_hours_alloc"]
        ].rename(columns={
            "name": "Matéria", "importance": "Importância", "difficulty": "Dificuldade",
            "weight": "Peso", "weekly_hours_alloc": "Horas/semana alocadas",
        })
        st.dataframe(tabela_exibicao, use_container_width=True, hide_index=True)

        with st.expander("✏️ Editar / remover matéria"):
            materia_alvo = st.selectbox(
                "Selecione a matéria", subjects_df["name"].tolist(), key="editar_materia"
            )
            linha_alvo = subjects_df.loc[subjects_df["name"] == materia_alvo].iloc[0]
            with st.form("form_editar_materia"):
                novo_nome = st.text_input("Nome", value=linha_alvo["name"])
                colE1, colE2 = st.columns(2)
                nova_importancia = colE1.slider("Importância", 1, 5, int(linha_alvo["importance"]))
                nova_dificuldade = colE2.slider("Dificuldade", 1, 5, int(linha_alvo["difficulty"]))
                colBtn1, colBtn2 = st.columns(2)
                salvar_edicao = colBtn1.form_submit_button("💾 Salvar alterações")
                excluir_materia = colBtn2.form_submit_button("🗑️ Excluir matéria", type="secondary")

            if salvar_edicao:
                if novo_nome.strip():
                    run_query(
                        "UPDATE subjects SET name = ?, importance = ?, difficulty = ? WHERE id = ?",
                        (novo_nome.strip(), nova_importancia, nova_dificuldade, int(linha_alvo["id"])),
                    )
                    st.success("Matéria atualizada!")
                    st.rerun()
                else:
                    st.warning("O nome não pode ficar vazio.")

            if excluir_materia:
                sid = int(linha_alvo["id"])
                run_query("DELETE FROM subjects WHERE id = ?", (sid,))
                run_query("DELETE FROM study_log WHERE subject_id = ?", (sid,))
                st.success("Matéria removida (junto com flashcards e questões vinculados a ela).")
                st.rerun()

        st.divider()
        st.subheader("🔄 Modo de organização do cronograma")
        modo = st.radio(
            "Escolha o modo de cronograma",
            ["Cronograma Semanal Fixo", "Modo Ciclo de Estudos"],
            horizontal=True,
        )

        urgencia = fator_urgencia_prova(curso_atual["exam_date"])
        if urgencia > 1.0:
            st.warning(
                f"⚠️ A prova está se aproximando! Fator de intensificação de revisões: **{urgencia}x**. "
                "O algoritmo está comprimindo os intervalos de revisão automaticamente."
            )

        if modo == "Cronograma Semanal Fixo":
            distribuicao = []
            for i, row in subjects_df.iterrows():
                dia_sugerido = DIAS_SEMANA[i % len(DIAS_SEMANA)]
                distribuicao.append({
                    "Dia sugerido": dia_sugerido,
                    "Matéria": row["name"],
                    "Horas na semana": row["weekly_hours_alloc"],
                })
            st.dataframe(pd.DataFrame(distribuicao), use_container_width=True, hide_index=True)
        else:
            ciclo_df = sugerir_ordem_ciclo(subjects_df)
            st.markdown("**Ordem sugerida do ciclo (prioridade dinâmica = peso × desempenho fraco):**")
            ciclo_exibicao = ciclo_df[["name", "weight", "desempenho", "prioridade_ciclo"]].rename(
                columns={
                    "name": "Matéria", "weight": "Peso",
                    "desempenho": "Taxa de Acerto Atual", "prioridade_ciclo": "Prioridade no Ciclo",
                }
            )
            ciclo_exibicao["Taxa de Acerto Atual"] = (ciclo_exibicao["Taxa de Acerto Atual"] * 100).round(1)
            st.dataframe(ciclo_exibicao, use_container_width=True, hide_index=True)
            st.info(
                f"👉 Próxima matéria recomendada pelo ciclo: **{ciclo_df.iloc[0]['name']}**"
            )

    # -------------------------------------------------------------------
    # QUADRO DE CRONOGRAMA ESTILO TRELLO (ARRASTAR E SOLTAR ENTRE OS DIAS)
    # -------------------------------------------------------------------
    st.divider()
    st.subheader("📌 Quadro de Cronograma (arraste os blocos entre os dias)")
    st.caption(
        "Arraste cada bloco de estudo para o dia desejado — igual a um quadro Trello. "
        "Arraste um bloco até a coluna de lixeira para excluí-lo. Não esqueça de salvar."
    )

    board = carregar_board(int(curso_atual["id"]), subjects_df if not subjects_df.empty else pd.DataFrame())

    with st.form("form_add_bloco"):
        colA1, colA2, colA3 = st.columns([2, 1, 1])
        texto_bloco = colA1.text_input("Novo bloco de estudo (ex: 'Farmacologia - Revisão')")
        dia_destino = colA2.selectbox("Dia", DIAS_SEMANA)
        adicionar_bloco = colA3.form_submit_button("➕ Adicionar ao quadro")
        if adicionar_bloco:
            if texto_bloco.strip():
                board.setdefault(dia_destino, []).append(texto_bloco.strip())
                salvar_board(int(curso_atual["id"]), board)
                st.success("Bloco adicionado ao quadro!")
                st.rerun()
            else:
                st.warning("Digite um texto para o bloco.")

    if sort_items is not None:
        containers_board = [{"header": dia, "items": board.get(dia, [])} for dia in DIAS_SEMANA]
        containers_board.append({"header": COLUNA_LIXEIRA, "items": board.get(COLUNA_LIXEIRA, [])})

        board_atualizado = sort_items(containers_board, multi_containers=True, direction="vertical")

        if st.button("💾 Salvar cronograma (após arrastar os blocos)"):
            novo_board = {item["header"]: item["items"] for item in board_atualizado}
            itens_removidos = len(novo_board.get(COLUNA_LIXEIRA, []))
            salvar_board(int(curso_atual["id"]), novo_board)
            if itens_removidos:
                st.success(f"Cronograma salvo! {itens_removidos} bloco(s) excluído(s) via lixeira.")
            else:
                st.success("Cronograma salvo!")
            st.rerun()
    else:
        st.warning(
            "⚠️ O componente de arrastar-e-soltar (`streamlit-sortables`) não está instalado. "
            "Rode `pip install streamlit-sortables` e reinicie o app para habilitar o quadro visual. "
            "Enquanto isso, use a movimentação manual abaixo."
        )
        # Fallback funcional sem a biblioteca de drag-and-drop: mover bloco por seletor
        col_view, col_move = st.columns([2, 1])
        with col_view:
            for dia in DIAS_SEMANA:
                if board.get(dia):
                    st.markdown(f"**{dia}**")
                    for item in board[dia]:
                        st.write(f"• {item}")
        with col_move:
            todos_itens = [(dia, item) for dia in DIAS_SEMANA for item in board.get(dia, [])]
            if todos_itens:
                escolha_item = st.selectbox(
                    "Mover bloco", options=range(len(todos_itens)),
                    format_func=lambda i: f"{todos_itens[i][1]} (em {todos_itens[i][0]})",
                )
                novo_dia = st.selectbox("Para o dia", DIAS_SEMANA, key="novo_dia_mover")
                if st.button("↪️ Mover bloco selecionado"):
                    dia_origem, item_texto = todos_itens[escolha_item]
                    board[dia_origem].remove(item_texto)
                    board.setdefault(novo_dia, []).append(item_texto)
                    salvar_board(int(curso_atual["id"]), board)
                    st.success(f"Bloco movido para {novo_dia}!")
                    st.rerun()
                if st.button("🗑️ Excluir bloco selecionado"):
                    dia_origem, item_texto = todos_itens[escolha_item]
                    board[dia_origem].remove(item_texto)
                    salvar_board(int(curso_atual["id"]), board)
                    st.success("Bloco excluído!")
                    st.rerun()

# =============================================================================
# PÁGINA 2.5 - PROVAS E CALENDÁRIO
# =============================================================================
elif pagina == "🗓️ Provas e Calendário":
    st.title("🗓️ Provas e Calendário")
    st.caption("Cadastre suas provas, acompanhe a contagem regressiva e visualize sua constância no calendário.")

    with st.expander("➕ Nova Prova", expanded=False):
        with st.form("form_nova_prova", clear_on_submit=True):
            colp1, colp2 = st.columns(2)
            nome_prova = colp1.text_input("Nome da prova")
            data_prova = colp2.date_input("Data", value=date.today() + timedelta(days=30))
            colp3, colp4 = st.columns(2)
            local_prova = colp3.text_input("Local (opcional)")
            cor_prova = colp4.color_picker("Cor de identificação", value="#5B8DEF")
            alerta_dias = st.slider("Alertar com quantos dias de antecedência?", 1, 30, 7)
            salvar_prova = st.form_submit_button("💾 Salvar prova")
            if salvar_prova:
                if nome_prova.strip():
                    run_query(
                        """INSERT INTO exams (course_id, name, exam_date, location, color, alert_days_before, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (int(curso_atual["id"]), nome_prova.strip(), data_prova.isoformat(),
                         local_prova.strip(), cor_prova, alerta_dias, datetime.now().isoformat()),
                    )
                    st.success(f"Prova '{nome_prova}' cadastrada!")
                    st.rerun()
                else:
                    st.warning("Informe um nome para a prova.")

    st.divider()
    st.subheader("📋 Suas provas cadastradas")
    provas_df = df_query(
        "SELECT * FROM exams WHERE course_id = ? ORDER BY exam_date ASC", (int(curso_atual["id"]),)
    )
    if provas_df.empty:
        st.info("Nenhuma prova cadastrada ainda para este curso.")
    else:
        for _, prova in provas_df.iterrows():
            dias_falta = (datetime.fromisoformat(prova["exam_date"]).date() - date.today()).days
            situacao = "🔴 Hoje/atrasada" if dias_falta <= 0 else f"faltam {dias_falta} dias"
            if dias_falta <= prova["alert_days_before"] and dias_falta >= 0:
                situacao = f"⚠️ {situacao} — dentro da janela de alerta!"

            colpr1, colpr2, colpr3 = st.columns([4, 1.3, 0.7])
            colpr1.markdown(
                f"""<div class="cm-card" style="border-left:4px solid {prova['color']}">
                        <b>{prova['name']}</b> &nbsp;
                        <span style="color:#93A4C3;font-size:0.85rem">
                            {prova['exam_date']} {('· ' + prova['location']) if prova['location'] else ''} · {situacao}
                        </span>
                    </div>""",
                unsafe_allow_html=True,
            )
            # Link para adicionar ao Google Calendar (sem necessidade de OAuth/credenciais)
            url_gcal = gerar_link_google_calendar(prova["name"], prova["exam_date"], local=prova["location"] or "")
            colpr2.link_button("📅 Google Agenda", url_gcal, use_container_width=True)
            if colpr3.button("🗑️", key=f"del_prova_{prova['id']}"):
                run_query("DELETE FROM exams WHERE id = ?", (int(prova["id"]),))
                st.rerun()

    st.divider()
    st.subheader("📆 Calendário mensal de constância")
    st.caption(
        "Visualização mês a mês dos dias estudados. Para o mapa de calor anual completo, veja o Dashboard."
    )
    colm1, colm2 = st.columns(2)
    mes_sel = colm1.selectbox("Mês", list(range(1, 13)), index=date.today().month - 1,
                               format_func=lambda m: ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                                                       "Julho", "Agosto", "Setembro", "Outubro", "Novembro",
                                                       "Dezembro"][m - 1])
    ano_sel = colm2.number_input("Ano", min_value=2020, max_value=2100, value=date.today().year, step=1)

    log_mes = df_query(
        """SELECT log_date, SUM(minutes) as minutos FROM study_log
           WHERE log_date LIKE ? AND subject_id IN (
               SELECT s.id FROM subjects s JOIN courses c ON s.course_id = c.id WHERE c.user_id = ?
           )
           GROUP BY log_date""",
        (f"{ano_sel}-{mes_sel:02d}-%", USER_ID),
    )
    dias_estudados = set(log_mes["log_date"].tolist()) if not log_mes.empty else set()
    provas_do_mes = {}
    if not provas_df.empty:
        for _, p in provas_df.iterrows():
            if p["exam_date"].startswith(f"{ano_sel}-{mes_sel:02d}"):
                provas_do_mes[p["exam_date"]] = p["name"]

    cal = calendar_lib.Calendar(firstweekday=0)
    semanas_mes = cal.monthdayscalendar(int(ano_sel), int(mes_sel))

    grid_html = "<table style='width:100%; border-collapse:separate; border-spacing:6px;'>"
    grid_html += "<tr>" + "".join(
        f"<th style='color:#93A4C3;font-weight:500;font-size:0.8rem'>{d}</th>"
        for d in ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    ) + "</tr>"
    for semana in semanas_mes:
        grid_html += "<tr>"
        for dia in semana:
            if dia == 0:
                grid_html += "<td></td>"
                continue
            data_iso = f"{int(ano_sel)}-{int(mes_sel):02d}-{dia:02d}"
            estudou = data_iso in dias_estudados
            eh_prova = data_iso in provas_do_mes
            cor_fundo = "#5B8DEF" if estudou else "rgba(255,255,255,0.04)"
            borda = "2px solid #FF6B6B" if eh_prova else "1px solid rgba(255,255,255,0.08)"
            titulo = provas_do_mes.get(data_iso, "")
            grid_html += (
                f"<td title='{titulo}' style='background:{cor_fundo}; border:{borda}; border-radius:10px; "
                f"text-align:center; padding:10px 0; color:#E6EBF5; font-size:0.85rem'>{dia}</td>"
            )
        grid_html += "</tr>"
    grid_html += "</table>"
    st.markdown(grid_html, unsafe_allow_html=True)
    st.caption("🔵 Dia estudado · 🔴 borda vermelha = data de prova cadastrada")

# =============================================================================
# PÁGINA 3 - IMPORTADOR DE EDITAIS E MATERIAIS
# =============================================================================
elif pagina == "📥 Importador de Editais/Materiais":
    st.title("📥 Importador de Editais e Materiais de Estudo")
    st.caption(
        "Envie um PDF ou TXT. O sistema descarta automaticamente cabeçalhos, rodapés, "
        "numeração de página, marcas d'água e avisos editoriais, extrai os tópicos e gera "
        "flashcards e questões baseados estritamente no conteúdo médico essencial do material."
    )

    # ------------------------------------------------------------------
    # Seletor de modo de geração: Heurístico (local/gratuito) x IA (Claude)
    # ------------------------------------------------------------------
    with st.expander("🤖 Modo de geração: Heurístico x IA (Máxima Precisão)", expanded=True):
        modo_geracao = st.radio(
            "Como o conteúdo médico deve ser identificado e gerado?",
            [
                "⚙️ Heurístico local (regex + vocabulário médico, gratuito, offline)",
                "🎯 IA - Claude (leitura semântica real, máxima precisão)",
            ],
        )
        usar_ia = modo_geracao.startswith("🎯")

        cliente_ia = None
        modelo_ia = ANTHROPIC_MODEL_PADRAO
        if usar_ia:
            if Anthropic is None:
                st.error(
                    "A biblioteca `anthropic` não está instalada. Rode `pip install anthropic` "
                    "e reinicie o app para usar o modo de máxima precisão."
                )
            else:
                chave_atual = obter_chave_api()
                if not chave_atual:
                    st.text_input(
                        "Chave de API da Anthropic (não é salva no banco de dados, só nesta sessão)",
                        type="password",
                        key="anthropic_api_key_manual",
                        help="Obtenha sua chave em console.anthropic.com. Alternativamente, "
                             "configure ANTHROPIC_API_KEY em st.secrets para não precisar digitar toda vez.",
                    )
                modelo_ia = st.selectbox(
                    "Modelo",
                    ["claude-sonnet-5", "claude-haiku-4-5-20251001", "claude-opus-4-8"],
                    index=0,
                    help="Sonnet 5: melhor equilíbrio precisão/custo. Opus 4.8: máxima qualidade. "
                         "Haiku 4.5: mais rápido/barato.",
                )
                cliente_ia = obter_cliente_anthropic()
                if cliente_ia:
                    st.success("✅ Conectado à API da Anthropic - modo de máxima precisão ativo.")
                else:
                    st.warning("Informe uma chave de API válida acima para ativar o modo de máxima precisão.")

    arquivo = st.file_uploader("Selecione o arquivo (PDF ou TXT)", type=["pdf", "txt"])

    if arquivo is not None:
        with st.spinner("Lendo, limpando e processando o material..."):
            texto_extraido, stats_limpeza = extrair_texto_arquivo(arquivo)

        if not texto_extraido.strip():
            st.error("Não foi possível extrair texto do arquivo enviado.")
        else:
            st.success(f"Arquivo processado! {len(texto_extraido)} caracteres úteis extraídos.")

            if stats_limpeza.get("linhas_removidas", 0) > 0:
                st.info(
                    f"🧹 Limpeza automática (etapa local, roda sempre): **{stats_limpeza['linhas_removidas']} linha(s)** "
                    f"de cabeçalho/rodapé/numeração/marca d'água/aviso editorial foram descartadas "
                    f"(de {stats_limpeza['linhas_antes']} linhas originais), mantendo "
                    f"{stats_limpeza['linhas_depois']} linhas de conteúdo."
                )

            with st.spinner("Identificando tópicos..."):
                if usar_ia and cliente_ia:
                    topicos = ia_extrair_topicos_medicos(cliente_ia, modelo_ia, texto_extraido)
                else:
                    topicos = extrair_topicos(texto_extraido)

            st.subheader("🗂️ Tópicos identificados no material")
            st.write(topicos if topicos else "Nenhum tópico claro identificado.")

            with st.expander("👁️ Visualizar texto já limpo (prévia)"):
                st.text_area("Prévia do conteúdo pós-limpeza", texto_extraido[:3000], height=200)

            st.divider()
            st.subheader("⚙️ Associar conteúdo a uma matéria")

            subjects_df = df_query(
                "SELECT * FROM subjects WHERE course_id = ?", (int(curso_atual["id"]),)
            )
            opcoes_materia = ["➕ Criar nova matéria a partir deste material"] + subjects_df["name"].tolist()
            escolha = st.selectbox("Matéria de destino", opcoes_materia)

            if escolha.startswith("➕"):
                nome_sugerido = topicos[0] if topicos else arquivo.name.rsplit(".", 1)[0]
                nome_nova_materia = st.text_input("Nome da nova matéria", value=nome_sugerido)
            else:
                nome_nova_materia = None

            col1, col2 = st.columns(2)
            qtd_flashcards = col1.slider("Quantidade de flashcards a gerar", 5, 40, 15)
            qtd_questoes = col2.slider("Quantidade de questões a gerar", 5, 30, 10)

            if usar_ia and not cliente_ia:
                st.info("⬆️ Configure a chave de API acima para habilitar a geração no modo de máxima precisão.")

            botao_desabilitado = usar_ia and not cliente_ia
            if st.button("🤖 Gerar flashcards e questões automaticamente", disabled=botao_desabilitado):
                if escolha.startswith("➕"):
                    if not nome_nova_materia.strip():
                        st.warning("Informe um nome para a nova matéria.")
                        st.stop()
                    run_query(
                        "INSERT INTO subjects (course_id, name, importance, difficulty) VALUES (?, ?, 3, 3)",
                        (int(curso_atual["id"]), nome_nova_materia.strip()),
                    )
                    subject_id = df_query(
                        "SELECT id FROM subjects WHERE name = ? AND course_id = ?",
                        (nome_nova_materia.strip(), int(curso_atual["id"])),
                    ).iloc[0]["id"]
                else:
                    subject_id = int(subjects_df.loc[subjects_df["name"] == escolha, "id"].values[0])

                if usar_ia and cliente_ia:
                    with st.spinner("🎯 Claude está lendo o material e gerando conteúdo com máxima precisão..."):
                        n_fc, desc_fc = ia_gerar_flashcards(cliente_ia, modelo_ia, texto_extraido, int(subject_id), qtd_flashcards)
                        n_q, desc_q = ia_gerar_questoes(cliente_ia, modelo_ia, texto_extraido, int(subject_id), qtd_questoes)
                    origem = "IA (Claude) - leitura semântica"
                else:
                    with st.spinner("Filtrando conteúdo médico (heurística local) e gerando material de estudo..."):
                        n_fc, desc_fc = gerar_flashcards_de_texto(texto_extraido, int(subject_id), qtd_flashcards)
                        n_q, desc_q = gerar_questoes_de_texto(texto_extraido, int(subject_id), qtd_questoes)
                    origem = "heurística local"

                st.success(
                    f"✅ Gerados {n_fc} flashcards e {n_q} questões (modo: {origem}), baseados estritamente "
                    f"no conteúdo médico essencial identificado no material."
                )
                total_descartado = desc_fc + desc_q
                if total_descartado > 0:
                    st.caption(
                        f"🩺 {total_descartado} trecho(s) foram ignorados na geração por não "
                        "representarem conteúdo clínico/médico reconhecível (ex: texto institucional, "
                        "administrativo ou contextual não essencial)."
                    )
                if n_fc == 0 and n_q == 0:
                    st.warning(
                        "Nenhum conteúdo médico reconhecível foi encontrado neste material. "
                        "Verifique se o arquivo enviado é, de fato, conteúdo clínico/médico."
                    )
                st.balloons()

# =============================================================================
# PÁGINA 4 - FLASHCARDS COM SM-2
# =============================================================================
elif pagina == "🎴 Flashcards (SM-2)":
    st.title("🎴 Sistema de Flashcards (Repetição Espaçada SM-2)")

    subjects_df = df_query("SELECT * FROM subjects WHERE course_id = ?", (int(curso_atual["id"]),))
    if subjects_df.empty:
        st.info("Cadastre uma matéria primeiro (aba Cronograma) ou importe um material.")
        st.stop()

    materia_nome = st.selectbox("Filtrar por matéria", ["Todas"] + subjects_df["name"].tolist())

    # ---------------------------------------------------------------
    # MODAL: CRIAR NOVO DECK (com geração automática via IA)
    # ---------------------------------------------------------------
    with st.expander("🗂️ Criar novo deck"):
        colD1, colD2 = st.columns(2)
        nome_deck = colD1.text_input("Nome do deck")
        materia_opcoes = subjects_df["name"].tolist() + ["➕ Nova matéria..."]
        materia_deck_sel = colD2.selectbox("Matéria", materia_opcoes, key="materia_deck")
        if materia_deck_sel == "➕ Nova matéria...":
            nome_nova_materia_deck = st.text_input("Nome da nova matéria", key="nova_materia_deck")
        colD3, colD4 = st.columns(2)
        topico_deck = colD3.text_input("Tópico (opcional)")
        cor_deck = colD4.color_picker("Cor do deck", value="#5B8DEF")

        conteudo_deck = st.text_area(
            "Cole aqui o conteúdo do qual deseja gerar flashcards", height=180, key="conteudo_deck"
        )
        st.caption(f"{len(conteudo_deck)} caracteres")

        colD5, colD6 = st.columns(2)
        qtd_fc_deck = colD5.slider("Quantidade de flashcards a gerar", 5, 40, 15, key="qtd_fc_deck")
        usar_ia_deck = colD6.checkbox("Usar IA (Claude) para máxima precisão", value=Anthropic is not None)

        if st.button("🤖 Criar deck e gerar flashcards"):
            if not nome_deck.strip():
                st.warning("Informe um nome para o deck.")
                st.stop()
            if not conteudo_deck.strip():
                st.warning("Cole o conteúdo de origem para gerar os flashcards.")
                st.stop()

            if materia_deck_sel == "➕ Nova matéria...":
                if not nome_nova_materia_deck.strip():
                    st.warning("Informe o nome da nova matéria.")
                    st.stop()
                run_query(
                    "INSERT INTO subjects (course_id, name, importance, difficulty) VALUES (?, ?, 3, 3)",
                    (int(curso_atual["id"]), nome_nova_materia_deck.strip()),
                )
                sid_deck = df_query(
                    "SELECT id FROM subjects WHERE name = ? AND course_id = ?",
                    (nome_nova_materia_deck.strip(), int(curso_atual["id"])),
                ).iloc[0]["id"]
            else:
                sid_deck = int(subjects_df.loc[subjects_df["name"] == materia_deck_sel, "id"].values[0])

            resultado_deck = run_query(
                "INSERT INTO decks (subject_id, name, topic, color, created_at) VALUES (?, ?, ?, ?, ?) RETURNING id",
                (int(sid_deck), nome_deck.strip(), topico_deck.strip(), cor_deck, datetime.now().isoformat()),
                fetch=True,
            )
            deck_id_novo = int(resultado_deck[0])

            texto_limpo_deck = limpar_texto_medico(conteudo_deck)
            cliente_deck = obter_cliente_anthropic() if usar_ia_deck else None

            with st.spinner("Gerando flashcards para o deck..."):
                if cliente_deck:
                    n_fc, _ = ia_gerar_flashcards(
                        cliente_deck, ANTHROPIC_MODEL_PADRAO, texto_limpo_deck, int(sid_deck),
                        qtd_fc_deck, deck_id=int(deck_id_novo),
                    )
                else:
                    n_fc, _ = gerar_flashcards_de_texto(
                        texto_limpo_deck, int(sid_deck), qtd_fc_deck, deck_id=int(deck_id_novo)
                    )
            st.success(f"✅ Deck '{nome_deck}' criado com {n_fc} flashcards!")
            st.rerun()

    with st.expander("🛠️ Gerenciar decks (editar / excluir)"):
        decks_df = df_query(
            """SELECT d.*, s.name as subject_name FROM decks d
               JOIN subjects s ON d.subject_id = s.id
               WHERE s.course_id = ? ORDER BY d.id DESC""",
            (int(curso_atual["id"]),),
        )
        if decks_df.empty:
            st.caption("Nenhum deck criado ainda neste curso.")
        else:
            opcoes_deck = {
                f"{r['name']} · {r['subject_name']}": r["id"] for _, r in decks_df.iterrows()
            }
            escolha_deck = st.selectbox("Selecione o deck", list(opcoes_deck.keys()), key="escolha_deck_editar")
            deck_id_sel = opcoes_deck[escolha_deck]
            deck_linha = decks_df.loc[decks_df["id"] == deck_id_sel].iloc[0]
            qtd_fc_no_deck = df_query(
                "SELECT COUNT(*) as c FROM flashcards WHERE deck_id = ?", (int(deck_id_sel),)
            ).iloc[0]["c"]
            st.caption(f"Este deck contém {qtd_fc_no_deck} flashcard(s).")

            with st.form("form_editar_deck"):
                novo_nome_deck = st.text_input("Nome do deck", value=deck_linha["name"])
                novo_topico_deck = st.text_input("Tópico", value=deck_linha["topic"] or "")
                nova_cor_deck = st.color_picker("Cor", value=deck_linha["color"] or "#5B8DEF")
                excluir_flashcards_junto = st.checkbox(
                    "Ao excluir o deck, excluir também os flashcards dele (senão eles apenas ficam soltos)"
                )
                colDK1, colDK2 = st.columns(2)
                salvar_deck = colDK1.form_submit_button("💾 Salvar alterações")
                excluir_deck = colDK2.form_submit_button("🗑️ Excluir deck", type="secondary")

            if salvar_deck:
                if novo_nome_deck.strip():
                    run_query(
                        "UPDATE decks SET name = ?, topic = ?, color = ? WHERE id = ?",
                        (novo_nome_deck.strip(), novo_topico_deck.strip(), nova_cor_deck, int(deck_id_sel)),
                    )
                    st.success("Deck atualizado!")
                    st.rerun()
                else:
                    st.warning("O nome do deck não pode ficar vazio.")

            if excluir_deck:
                if excluir_flashcards_junto:
                    run_query("DELETE FROM flashcards WHERE deck_id = ?", (int(deck_id_sel),))
                else:
                    run_query("UPDATE flashcards SET deck_id = NULL WHERE deck_id = ?", (int(deck_id_sel),))
                run_query("DELETE FROM decks WHERE id = ?", (int(deck_id_sel),))
                st.success("Deck excluído!")
                st.rerun()

    st.divider()

    with st.expander("➕ Criar flashcard manualmente"):
        with st.form("form_flashcard_manual", clear_on_submit=True):
            materia_fc = st.selectbox("Matéria", subjects_df["name"].tolist(), key="materia_fc_manual")
            frente = st.text_area("Frente (pergunta)")
            verso = st.text_area("Verso (resposta)")
            criar_fc = st.form_submit_button("Criar flashcard")
            if criar_fc:
                if frente.strip() and verso.strip():
                    sid = int(subjects_df.loc[subjects_df["name"] == materia_fc, "id"].values[0])
                    run_query(
                        """INSERT INTO flashcards
                           (subject_id, front, back, ease, review_interval, repetitions, due_date, created_at, source)
                           VALUES (?, ?, ?, 2.5, 0, 0, ?, ?, 'manual')""",
                        (sid, frente.strip(), verso.strip(), date.today().isoformat(), datetime.now().isoformat()),
                    )
                    st.success("Flashcard criado!")
                    st.rerun()
                else:
                    st.warning("Preencha frente e verso.")

    # ---------------------------------------------------------------
    # GERENCIAR FLASHCARDS (EDITAR / EXCLUIR)
    # ---------------------------------------------------------------
    with st.expander("🛠️ Gerenciar flashcards (editar / excluir)"):
        query_gerenciar = """
            SELECT f.*, s.name as subject_name FROM flashcards f
            JOIN subjects s ON f.subject_id = s.id
            WHERE s.course_id = ?
        """
        params_gerenciar = [int(curso_atual["id"])]
        if materia_nome != "Todas":
            query_gerenciar += " AND s.name = ?"
            params_gerenciar.append(materia_nome)
        query_gerenciar += " ORDER BY f.id DESC"
        todos_flashcards = df_query(query_gerenciar, tuple(params_gerenciar))

        if todos_flashcards.empty:
            st.caption("Nenhum flashcard cadastrado com esse filtro.")
        else:
            opcoes_fc = {
                f"#{r['id']} · {r['subject_name']} · {r['front'][:50]}": r["id"]
                for _, r in todos_flashcards.iterrows()
            }
            escolha_fc = st.selectbox("Selecione o flashcard", list(opcoes_fc.keys()), key="escolha_fc_editar")
            fc_id_sel = opcoes_fc[escolha_fc]
            fc_linha = todos_flashcards.loc[todos_flashcards["id"] == fc_id_sel].iloc[0]

            with st.form("form_editar_flashcard"):
                novo_front = st.text_area("Frente", value=fc_linha["front"])
                novo_back = st.text_area("Verso", value=fc_linha["back"])
                colFB1, colFB2 = st.columns(2)
                salvar_fc = colFB1.form_submit_button("💾 Salvar alterações")
                excluir_fc = colFB2.form_submit_button("🗑️ Excluir flashcard", type="secondary")

            if salvar_fc:
                if novo_front.strip() and novo_back.strip():
                    run_query(
                        "UPDATE flashcards SET front = ?, back = ? WHERE id = ?",
                        (novo_front.strip(), novo_back.strip(), int(fc_id_sel)),
                    )
                    st.success("Flashcard atualizado!")
                    st.rerun()
                else:
                    st.warning("Frente e verso não podem ficar vazios.")

            if excluir_fc:
                run_query("DELETE FROM flashcards WHERE id = ?", (int(fc_id_sel),))
                st.success("Flashcard excluído!")
                st.rerun()

    st.divider()

    query = """
        SELECT f.*, s.name as subject_name FROM flashcards f
        JOIN subjects s ON f.subject_id = s.id
        WHERE s.course_id = ? AND (f.due_date IS NULL OR f.due_date <= ?)
    """
    params = [int(curso_atual["id"]), date.today().isoformat()]
    if materia_nome != "Todas":
        query += " AND s.name = ?"
        params.append(materia_nome)
    query += " ORDER BY f.due_date ASC LIMIT 1"

    cartao = df_query(query, tuple(params))

    total_pendentes = df_query(
        """SELECT COUNT(*) as c FROM flashcards f JOIN subjects s ON f.subject_id = s.id
           WHERE s.course_id = ? AND (f.due_date IS NULL OR f.due_date <= ?)""",
        (int(curso_atual["id"]), date.today().isoformat()),
    ).iloc[0]["c"]

    st.metric("Flashcards pendentes de revisão hoje", total_pendentes)

    if cartao.empty:
        st.success("🎉 Nenhum flashcard pendente no momento. Volte mais tarde ou crie novos!")
    else:
        card = cartao.iloc[0]
        st.subheader(f"📘 Matéria: {card['subject_name']}")
        st.markdown(f"### {card['front']}")

        card_id = int(card["id"])
        mostrar = st.session_state.show_answer_map.get(card_id, False)

        if not mostrar:
            if st.button("👁️ Mostrar Resposta", key=f"show_{card_id}"):
                st.session_state.show_answer_map[card_id] = True
                st.rerun()
        else:
            st.info(card["back"])
            urgencia = fator_urgencia_prova(curso_atual["exam_date"])

            colb1, colb2, colb3 = st.columns(3)

            def avaliar(qualidade):
                reps, ease, interval, due = sm2(
                    qualidade, int(card["repetitions"]), float(card["ease"]),
                    float(card["review_interval"]), urgencia,
                )
                run_query(
                    """UPDATE flashcards SET repetitions = ?, ease = ?, review_interval = ?,
                       due_date = ?, last_review = ? WHERE id = ?""",
                    (reps, ease, interval, due, datetime.now().isoformat(), card_id),
                )
                run_query(
                    "INSERT INTO flashcard_reviews (flashcard_id, quality, timestamp) VALUES (?, ?, ?)",
                    (card_id, qualidade, datetime.now().isoformat()),
                )
                registrar_estudo(int(card["subject_id"]), 2, "flashcard")
                subiu_nivel, _ = conceder_xp(USER_ID, 5)
                st.session_state.show_answer_map[card_id] = False
                if subiu_nivel:
                    st.balloons()
                st.rerun()

            if colb1.button("❌ Errado/Difícil"):
                avaliar(0)
            if colb2.button("✅ Bom/Médio"):
                avaliar(3)
            if colb3.button("⭐ Fácil"):
                avaliar(5)


# =============================================================================
# PÁGINA 5 - SIMULADOR DE QUESTÕES E DESEMPENHO
# =============================================================================
elif pagina == "❓ Simulador de Questões":
    st.title("❓ Simulador de Questões e Desempenho")

    subjects_df = df_query("SELECT * FROM subjects WHERE course_id = ?", (int(curso_atual["id"]),))
    if subjects_df.empty:
        st.info("Cadastre uma matéria primeiro ou importe um material com questões.")
        st.stop()

    materia_escolhida = st.selectbox("Escolha a matéria para o simulado", subjects_df["name"].tolist())
    sid = int(subjects_df.loc[subjects_df["name"] == materia_escolhida, "id"].values[0])

    qtd_questoes_disp = df_query("SELECT COUNT(*) as c FROM questions WHERE subject_id = ?", (sid,)).iloc[0]["c"]

    if qtd_questoes_disp == 0:
        st.warning("Nenhuma questão cadastrada para esta matéria. Importe um material ou cadastre manualmente.")

    with st.expander("➕ Cadastrar questão manualmente"):
        with st.form("form_questao_manual", clear_on_submit=True):
            enunciado = st.text_area("Enunciado")
            oa = st.text_input("Opção A")
            ob = st.text_input("Opção B")
            oc = st.text_input("Opção C")
            od = st.text_input("Opção D")
            oe = st.text_input("Opção E")
            correta = st.selectbox("Alternativa correta", ["A", "B", "C", "D", "E"])
            explicacao = st.text_area("Gabarito comentado (explicação)")
            criar_q = st.form_submit_button("Cadastrar questão")
            if criar_q:
                if enunciado.strip() and oa.strip() and ob.strip():
                    run_query(
                        """INSERT INTO questions
                           (subject_id, statement, option_a, option_b, option_c, option_d, option_e,
                            correct_option, explanation, priority, created_at, source)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, 'manual')""",
                        (sid, enunciado, oa, ob, oc, od, oe, correta, explicacao, datetime.now().isoformat()),
                    )
                    st.success("Questão cadastrada!")
                    st.rerun()
                else:
                    st.warning("Preencha ao menos enunciado, opção A e opção B.")

    st.divider()

    with st.expander("🛠️ Gerenciar questões (editar / excluir)"):
        todas_questoes = df_query(
            "SELECT * FROM questions WHERE subject_id = ? ORDER BY id DESC", (sid,)
        )
        if todas_questoes.empty:
            st.caption("Nenhuma questão cadastrada para esta matéria.")
        else:
            opcoes_q = {
                f"#{r['id']} · {r['statement'][:60]}": r["id"] for _, r in todas_questoes.iterrows()
            }
            escolha_q = st.selectbox("Selecione a questão", list(opcoes_q.keys()), key="escolha_q_editar")
            q_id_sel = opcoes_q[escolha_q]
            q_linha = todas_questoes.loc[todas_questoes["id"] == q_id_sel].iloc[0]

            with st.form("form_editar_questao"):
                novo_enunciado = st.text_area("Enunciado", value=q_linha["statement"])
                colQ1, colQ2 = st.columns(2)
                nova_oa = colQ1.text_input("Opção A", value=q_linha["option_a"] or "")
                nova_ob = colQ2.text_input("Opção B", value=q_linha["option_b"] or "")
                colQ3, colQ4 = st.columns(2)
                nova_oc = colQ3.text_input("Opção C", value=q_linha["option_c"] or "")
                nova_od = colQ4.text_input("Opção D", value=q_linha["option_d"] or "")
                nova_oe = st.text_input("Opção E", value=q_linha["option_e"] or "")
                nova_correta = st.selectbox(
                    "Alternativa correta", ["A", "B", "C", "D", "E"],
                    index=["A", "B", "C", "D", "E"].index(str(q_linha["correct_option"]).strip().upper())
                    if str(q_linha["correct_option"]).strip().upper() in ["A", "B", "C", "D", "E"] else 0,
                )
                nova_explicacao = st.text_area("Gabarito comentado", value=q_linha["explanation"] or "")
                colQB1, colQB2 = st.columns(2)
                salvar_q = colQB1.form_submit_button("💾 Salvar alterações")
                excluir_q = colQB2.form_submit_button("🗑️ Excluir questão", type="secondary")

            if salvar_q:
                if novo_enunciado.strip():
                    run_query(
                        """UPDATE questions SET statement = ?, option_a = ?, option_b = ?, option_c = ?,
                           option_d = ?, option_e = ?, correct_option = ?, explanation = ? WHERE id = ?""",
                        (novo_enunciado.strip(), nova_oa, nova_ob, nova_oc, nova_od, nova_oe,
                         nova_correta, nova_explicacao, int(q_id_sel)),
                    )
                    st.success("Questão atualizada!")
                    st.rerun()
                else:
                    st.warning("O enunciado não pode ficar vazio.")

            if excluir_q:
                run_query("DELETE FROM questions WHERE id = ?", (int(q_id_sel),))
                st.success("Questão excluída!")
                st.rerun()

    st.divider()

    n_questoes_simulado = st.slider("Quantas questões deseja no simulado?", 1, max(1, int(qtd_questoes_disp)), min(5, max(1, int(qtd_questoes_disp))))

    if st.button("🚀 Iniciar novo simulado"):
        # Prioriza questões com maior 'priority' (as que o usuário mais errou)
        banco = df_query(
            "SELECT * FROM questions WHERE subject_id = ? ORDER BY priority DESC", (sid,)
        )
        if not banco.empty:
            amostra = banco.sample(n=min(n_questoes_simulado, len(banco)), weights=banco["priority"])
            st.session_state.current_quiz = {
                "questions": amostra.to_dict("records"),
                "answers": {},
                "index": 0,
                "subject_id": sid,
                "finished": False,
            }
            st.rerun()

    quiz = st.session_state.current_quiz
    if quiz and not quiz.get("finished") and quiz.get("subject_id") == sid:
        idx = quiz["index"]
        questoes = quiz["questions"]

        if idx < len(questoes):
            q = questoes[idx]
            st.subheader(f"Questão {idx + 1} de {len(questoes)}")
            st.markdown(f"**{q['statement']}**")

            opcoes = {
                "A": q["option_a"], "B": q["option_b"], "C": q["option_c"],
                "D": q["option_d"], "E": q["option_e"],
            }
            opcoes_validas = {k: v for k, v in opcoes.items() if v and str(v).strip()}

            resposta = st.radio(
                "Selecione a alternativa:",
                list(opcoes_validas.keys()),
                format_func=lambda k: f"{k}) {opcoes_validas[k]}",
                key=f"resp_{idx}",
            )

            if st.button("Confirmar resposta", key=f"confirmar_{idx}"):
                correta = str(q["correct_option"]).strip().upper()
                acertou = resposta.strip().upper() == correta
                quiz["answers"][idx] = {"resposta": resposta, "correta": acertou}

                run_query(
                    "INSERT INTO question_attempts (question_id, subject_id, is_correct, timestamp) VALUES (?, ?, ?, ?)",
                    (int(q["id"]), sid, 1 if acertou else 0, datetime.now().isoformat()),
                )

                # Fila de prioridade: erro aumenta prioridade, acerto reduz
                nova_prioridade = float(q["priority"]) * (1.6 if not acertou else 0.7)
                nova_prioridade = max(0.3, min(nova_prioridade, 10))
                run_query("UPDATE questions SET priority = ? WHERE id = ?", (nova_prioridade, int(q["id"])))

                if acertou:
                    st.success("✅ Resposta correta!")
                else:
                    st.error(f"❌ Resposta incorreta. Gabarito: {correta}")
                if q["explanation"]:
                    st.info(f"📖 Comentário: {q['explanation']}")

                subiu_nivel, _ = conceder_xp(USER_ID, 8 if acertou else 3)
                if subiu_nivel:
                    st.balloons()

                quiz["index"] += 1
                if quiz["index"] >= len(questoes):
                    quiz["finished"] = True
                    registrar_estudo(sid, len(questoes) * 2, "simulado")
                st.session_state.current_quiz = quiz

            st.button("➡️ Próxima questão", key=f"next_{idx}", on_click=lambda: None)

    if quiz and quiz.get("finished"):
        respostas = quiz["answers"]
        total = len(respostas)
        acertos = sum(1 for r in respostas.values() if r["correta"])
        erros = total - acertos
        pct = (acertos / total * 100) if total else 0

        st.divider()
        st.subheader("📊 Relatório de Desempenho do Simulado")
        c1, c2, c3 = st.columns(3)
        c1.metric("Percentual de Acertos", f"{pct:.1f}%")
        c2.metric("Acertos (absoluto)", acertos)
        c3.metric("Erros (absoluto)", erros)

        fig = px.pie(
            names=["Acertos", "Erros"], values=[acertos, erros],
            color=["Acertos", "Erros"], color_discrete_map={"Acertos": "#2ecc71", "Erros": "#e74c3c"},
        )
        st.plotly_chart(fig, use_container_width=True)

        if erros > 0:
            st.warning(
                f"⚠️ {erros} questão(ões) errada(s) foram adicionadas com prioridade "
                "elevada na fila de Revisões por Desempenho."
            )

        if st.button("🔁 Fazer novo simulado"):
            st.session_state.current_quiz = None
            st.rerun()

# =============================================================================
# PÁGINA 5.5 - GERADOR DE SIMULADOS POR IA (PADRÃO RESIDÊNCIA MÉDICA)
# =============================================================================
elif pagina == "🧪 Gerador de Simulados (IA)":
    st.title("🧪 Gerador de Simulados por IA")
    st.caption(
        "Crie simulados no padrão de provas de residência médica: casos clínicos contextualizados, "
        "5 alternativas, nível de dificuldade e estilo de banca configuráveis, com gabarito comentado "
        "gerado pela IA."
    )

    subjects_df = df_query("SELECT * FROM subjects WHERE course_id = ?", (int(curso_atual["id"]),))
    if subjects_df.empty:
        st.info("Cadastre ao menos uma matéria na aba Cronograma antes de gerar um simulado.")
        st.stop()

    if Anthropic is None:
        st.error("A biblioteca `anthropic` não está instalada. Rode `pip install anthropic` para usar esta função.")
        st.stop()

    chave_atual_sim = obter_chave_api()
    if not chave_atual_sim:
        st.text_input(
            "Chave de API da Anthropic (não é salva no banco de dados, só nesta sessão)",
            type="password", key="anthropic_api_key_manual",
        )

    cliente_sim = obter_cliente_anthropic()
    if not cliente_sim:
        st.warning("⬆️ Informe uma chave de API válida para usar o Gerador de Simulados por IA.")
        st.stop()

    if not st.session_state.get("current_quiz_ia"):
        st.subheader("⚙️ Configuração do simulado")

        materias_selecionadas = st.multiselect(
            "1. Selecione os conteúdos/matérias a cobrir", subjects_df["name"].tolist(),
            default=subjects_df["name"].tolist()[:1],
        )
        topicos_texto = st.text_input("Tópicos específicos (opcional, separados por vírgula)")

        conteudo_base = st.text_area(
            "2. Área de importação de conteúdo (opcional): cole diretrizes, resumos ou trechos de "
            "material para a IA usar como base exclusiva de parte das questões",
            height=140,
        )
        arquivo_base = st.file_uploader("...ou envie um PDF/TXT como base", type=["pdf", "txt"], key="upload_sim_ia")
        if arquivo_base is not None:
            texto_arquivo_base, _ = extrair_texto_arquivo(arquivo_base)
            conteudo_base = (conteudo_base + "\n" + texto_arquivo_base).strip()

        col1, col2 = st.columns(2)
        quantidade_questoes = col1.slider("3. Quantidade de questões", 5, 50, 10)
        dificuldade_sim = col2.selectbox(
            "4. Nível de dificuldade", ["Fácil", "Médio", "Difícil", "Padrão Residência Médica"], index=3
        )

        bancas_disponiveis = ["ENARE", "USP-SP", "UNIFESP", "SUS-SP", "SES-PE", "AMRIGS", "SURCE", "Outra (geral)"]
        bancas_selecionadas = st.multiselect("5. Estilo de banca a simular", bancas_disponiveis, default=["ENARE"])

        if st.button("🚀 Gerar simulado com IA", type="primary"):
            if not materias_selecionadas:
                st.warning("Selecione ao menos uma matéria.")
                st.stop()
            mapa_subject_ids = {
                nome: int(subjects_df.loc[subjects_df["name"] == nome, "id"].values[0])
                for nome in materias_selecionadas
            }
            with st.spinner("🩺 A IA está elaborando os casos clínicos e o gabarito comentado..."):
                ids_geradas = ia_gerar_simulado_residencia(
                    cliente_sim, ANTHROPIC_MODEL_PADRAO, mapa_subject_ids, topicos_texto,
                    conteudo_base, dificuldade_sim, bancas_selecionadas, quantidade_questoes,
                )
            if not ids_geradas:
                st.error("Não foi possível gerar questões. Tente novamente ou ajuste os parâmetros.")
            else:
                questoes_geradas = df_query(
                    f"SELECT * FROM questions WHERE id IN ({','.join('?' * len(ids_geradas))})",
                    tuple(ids_geradas),
                )
                st.session_state.current_quiz_ia = {
                    "questions": questoes_geradas.to_dict("records"),
                    "answers": {}, "index": 0, "finished": False,
                }
                st.session_state.quiz_ia_start_ts = time.time()
                st.success(f"✅ {len(ids_geradas)} questões geradas! Iniciando o simulado...")
                st.rerun()

    quiz_ia = st.session_state.get("current_quiz_ia")
    if quiz_ia and not quiz_ia.get("finished"):
        idx = quiz_ia["index"]
        questoes = quiz_ia["questions"]
        decorrido = int(time.time() - st.session_state.get("quiz_ia_start_ts", time.time()))
        st.caption(f"⏱️ Tempo decorrido: {decorrido // 60:02d}:{decorrido % 60:02d}")

        if idx < len(questoes):
            q = questoes[idx]
            st.subheader(f"Questão {idx + 1} de {len(questoes)}  ·  {q.get('dificuldade', '')} · {q.get('banca', '')}")
            st.markdown(f"**{q['statement']}**")

            opcoes = {
                "A": q["option_a"], "B": q["option_b"], "C": q["option_c"],
                "D": q["option_d"], "E": q["option_e"],
            }
            opcoes_validas = {k: v for k, v in opcoes.items() if v and str(v).strip()}

            resposta = st.radio(
                "Selecione a alternativa:", list(opcoes_validas.keys()),
                format_func=lambda k: f"{k}) {opcoes_validas[k]}", key=f"resp_ia_{idx}",
            )

            if st.button("Confirmar resposta", key=f"confirmar_ia_{idx}"):
                correta = str(q["correct_option"]).strip().upper()
                acertou = resposta.strip().upper() == correta
                quiz_ia["answers"][idx] = {"resposta": resposta, "correta": acertou}

                run_query(
                    "INSERT INTO question_attempts (question_id, subject_id, is_correct, timestamp) VALUES (?, ?, ?, ?)",
                    (int(q["id"]), int(q["subject_id"]), 1 if acertou else 0, datetime.now().isoformat()),
                )
                nova_prioridade = float(q["priority"]) * (1.6 if not acertou else 0.7)
                run_query("UPDATE questions SET priority = ? WHERE id = ?",
                           (max(0.3, min(nova_prioridade, 10)), int(q["id"])))

                if acertou:
                    st.success("✅ Resposta correta!")
                else:
                    st.error(f"❌ Resposta incorreta. Gabarito: {correta}")
                st.info(f"📖 Gabarito comentado: {q['explanation']}")

                subiu_nivel, _ = conceder_xp(USER_ID, 12 if acertou else 4)
                if subiu_nivel:
                    st.balloons()

                quiz_ia["index"] += 1
                if quiz_ia["index"] >= len(questoes):
                    quiz_ia["finished"] = True
                    tempo_total_min = max(1, int((time.time() - st.session_state.quiz_ia_start_ts) / 60))
                    if questoes:
                        registrar_estudo(int(questoes[0]["subject_id"]), tempo_total_min, "simulado_ia")
                st.session_state.current_quiz_ia = quiz_ia

            st.button("➡️ Próxima questão", key=f"next_ia_{idx}", on_click=lambda: None)

    if quiz_ia and quiz_ia.get("finished"):
        respostas = quiz_ia["answers"]
        total = len(respostas)
        acertos = sum(1 for r in respostas.values() if r["correta"])
        erros = total - acertos
        pct = (acertos / total * 100) if total else 0
        tempo_final = int(time.time() - st.session_state.get("quiz_ia_start_ts", time.time()))

        st.divider()
        st.subheader("📊 Relatório de Desempenho do Simulado (IA)")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Percentual de Acertos", f"{pct:.1f}%")
        c2.metric("Acertos", acertos)
        c3.metric("Erros", erros)
        c4.metric("Tempo Total", f"{tempo_final // 60:02d}:{tempo_final % 60:02d}")

        fig = px.pie(
            names=["Acertos", "Erros"], values=[acertos, erros],
            color=["Acertos", "Erros"], color_discrete_map={"Acertos": "#5B8DEF", "Erros": "#FF6B6B"},
        )
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

        st.info("O desempenho deste simulado já foi salvo no histórico e reflete nas métricas do Dashboard.")

        if st.button("🔁 Gerar novo simulado"):
            st.session_state.current_quiz_ia = None
            st.rerun()

# =============================================================================
# PÁGINA 6 - CRONÔMETRO POMODORO
# =============================================================================
elif pagina == "🍅 Pomodoro":
    st.title("🍅 Cronômetro Pomodoro")
    st.caption("Registre seu tempo líquido de estudo diretamente no sistema.")

    subjects_df = df_query("SELECT * FROM subjects WHERE course_id = ?", (int(curso_atual["id"]),))

    col1, col2, col3 = st.columns(3)
    minutos_foco = col1.number_input("Duração do foco (min)", 5, 120, 25)
    minutos_pausa = col2.number_input("Duração da pausa (min)", 1, 60, 5)
    materia_pomodoro = col3.selectbox(
        "Matéria a registrar", subjects_df["name"].tolist() if not subjects_df.empty else ["Geral"]
    )

    duracao_atual = minutos_foco * 60 if st.session_state.pomodoro_mode == "foco" else minutos_pausa * 60

    placeholder_timer = st.empty()

    colb1, colb2, colb3 = st.columns(3)
    if colb1.button("▶️ Iniciar" if not st.session_state.pomodoro_running else "⏸️ Pausar"):
        if not st.session_state.pomodoro_running:
            st.session_state.pomodoro_start_ts = time.time()
            st.session_state.pomodoro_running = True
        else:
            st.session_state.pomodoro_running = False
        st.rerun()

    if colb2.button("⏹️ Resetar ciclo"):
        st.session_state.pomodoro_running = False
        st.session_state.pomodoro_start_ts = None
        st.session_state.pomodoro_mode = "foco"
        st.rerun()

    if colb3.button("✅ Concluir e registrar manualmente"):
        if not subjects_df.empty:
            sid = int(subjects_df.loc[subjects_df["name"] == materia_pomodoro, "id"].values[0])
            registrar_estudo(sid, minutos_foco, "pomodoro")
            st.success(f"{minutos_foco} minutos registrados em '{materia_pomodoro}'!")
        else:
            st.warning("Cadastre uma matéria antes de registrar o tempo.")

    # Loop de atualização do timer (padrão comum em apps Streamlit para "tempo real")
    if st.session_state.pomodoro_running and st.session_state.pomodoro_start_ts:
        decorrido = time.time() - st.session_state.pomodoro_start_ts
        restante = max(0, duracao_atual - decorrido)
        minutos, segundos = divmod(int(restante), 60)
        emoji = "🎯 FOCO" if st.session_state.pomodoro_mode == "foco" else "☕ PAUSA"
        placeholder_timer.markdown(f"## {emoji} — {minutos:02d}:{segundos:02d}")

        if restante <= 0:
            if st.session_state.pomodoro_mode == "foco":
                if not subjects_df.empty:
                    sid = int(subjects_df.loc[subjects_df["name"] == materia_pomodoro, "id"].values[0])
                    registrar_estudo(sid, minutos_foco, "pomodoro")
                st.session_state.pomodoro_cycle_count += 1
                st.session_state.pomodoro_mode = "pausa"
                subiu_nivel, _ = conceder_xp(USER_ID, 15)
                st.toast("✅ Ciclo de foco concluído! Hora da pausa.")
                if subiu_nivel:
                    st.balloons()
            else:
                st.session_state.pomodoro_mode = "foco"
                st.toast("🔔 Pausa concluída! Hora de focar novamente.")
            st.session_state.pomodoro_start_ts = time.time()

        time.sleep(1)
        st.rerun()
    else:
        minutos, segundos = divmod(int(duracao_atual), 60)
        placeholder_timer.markdown(f"## ⏳ Pronto para iniciar — {minutos:02d}:{segundos:02d}")

    st.metric("Ciclos de foco concluídos hoje", st.session_state.pomodoro_cycle_count)

# =============================================================================
# PÁGINA 7 - RELATÓRIOS E CURVA DE EBBINGHAUS
# =============================================================================
elif pagina == "📊 Relatórios e Ebbinghaus":
    st.title("📊 Relatórios Semanais e Curva de Esquecimento")

    inicio_semana = date.today() - timedelta(days=7)
    log_df = df_query(
        """SELECT * FROM study_log WHERE log_date >= ? AND subject_id IN (
               SELECT s.id FROM subjects s JOIN courses c ON s.course_id = c.id WHERE c.user_id = ?
           )""",
        (inicio_semana.isoformat(), USER_ID),
    )

    if log_df.empty:
        st.info("Ainda não há dados de estudo registrados nos últimos 7 dias.")
    else:
        log_df["log_date"] = pd.to_datetime(log_df["log_date"])
        resumo_diario = log_df.groupby("log_date")["minutes"].sum().reset_index()
        fig = px.line(
            resumo_diario, x="log_date", y="minutes", markers=True,
            title="Minutos estudados nos últimos 7 dias", labels={"minutes": "Minutos", "log_date": "Data"},
        )
        st.plotly_chart(fig, use_container_width=True)

        subjects_all = df_query("SELECT id, name FROM subjects WHERE course_id = ?", (int(curso_atual["id"]),))
        if not subjects_all.empty:
            log_com_nome = log_df.merge(subjects_all, left_on="subject_id", right_on="id", how="left")
            resumo_materia = log_com_nome.groupby("name")["minutes"].sum().reset_index()
            fig2 = px.bar(resumo_materia, x="name", y="minutes", title="Distribuição de tempo por matéria (7 dias)",
                          labels={"name": "Matéria", "minutes": "Minutos"})
            st.plotly_chart(fig2, use_container_width=True)

        st.subheader("💡 Sugestões estratégicas")
        subjects_df = df_query("SELECT * FROM subjects WHERE course_id = ?", (int(curso_atual["id"]),))
        if not subjects_df.empty:
            for _, row in subjects_df.iterrows():
                desempenho = calcular_desempenho_materia(row["id"])
                if desempenho < 0.5:
                    st.warning(
                        f"📌 **{row['name']}**: desempenho de {desempenho*100:.0f}%. "
                        "Priorize revisões e refaça questões desta matéria em breve."
                    )
                elif desempenho > 0.85:
                    st.success(
                        f"🌟 **{row['name']}**: ótimo desempenho ({desempenho*100:.0f}%). "
                        "Considere espaçar mais as revisões e focar tempo em outras matérias."
                    )

    st.divider()
    st.subheader("🧠 Curva de Esquecimento de Ebbinghaus")
    st.caption(
        "A retenção de memória cai exponencialmente com o tempo sem revisão. "
        "O CRONOMODY agenda revisões nos pontos ideais para 'resetar' a curva antes do esquecimento crítico."
    )

    dias = np.linspace(0, 30, 200)
    retencao_sem_revisao = 100 * np.exp(-dias / 5)

    fig_ebb = go.Figure()
    fig_ebb.add_trace(go.Scatter(x=dias, y=retencao_sem_revisao, mode="lines", name="Sem revisão", line=dict(color="red")))

    pontos_revisao = [1, 7, 16, 30]
    retencao_com_revisao = []
    nivel = 100
    ultimo_dia = 0
    xs, ys = [], []
    for d in dias:
        if pontos_revisao and d >= pontos_revisao[0]:
            nivel = 100
            ultimo_dia = pontos_revisao.pop(0)
        val = nivel * np.exp(-(d - ultimo_dia) / 5)
        xs.append(d)
        ys.append(val)
    fig_ebb.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name="Com revisões espaçadas (SM-2)", line=dict(color="green")))

    for marco in [1, 7, 16, 30]:
        fig_ebb.add_vline(x=marco, line_dash="dot", line_color="gray")

    fig_ebb.update_layout(
        xaxis_title="Dias", yaxis_title="Retenção de memória (%)",
        title="Impacto das revisões espaçadas na retenção de memória",
        height=400,
    )
    st.plotly_chart(fig_ebb, use_container_width=True)

# =============================================================================
# PÁGINA - MEU PERFIL (nome, foto, status)
# =============================================================================
elif pagina == "🙋 Meu Perfil":
    st.title("🙋 Meu Perfil")

    dados_perfil = df_query(
        "SELECT username, display_name, foto_perfil, status_atual, xp, nivel, streak FROM users WHERE id = ?",
        (USER_ID,),
    ).iloc[0]

    col_foto, col_dados = st.columns([1, 2])
    with col_foto:
        if dados_perfil["foto_perfil"]:
            st.markdown(
                f"""<img src="data:image/jpeg;base64,{dados_perfil['foto_perfil']}"
                        style="width:160px;height:160px;border-radius:50%;object-fit:cover;
                        border:3px solid var(--cm-accent);" />""",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                """<div style="width:160px;height:160px;border-radius:50%;background:rgba(255,255,255,0.08);
                        display:flex;align-items:center;justify-content:center;font-size:3rem;">🙂</div>""",
                unsafe_allow_html=True,
            )
        nova_foto = st.file_uploader("Alterar foto de perfil", type=["jpg", "jpeg", "png"])

    with col_dados:
        st.metric("🏅 Nível", dados_perfil["nivel"])
        st.metric("⭐ XP total", dados_perfil["xp"])
        st.metric("🔥 Ofensiva", f"{dados_perfil['streak']} dia(s)")

    st.divider()
    with st.form("form_meu_perfil"):
        novo_display_name = st.text_input("Nome / apelido de exibição", value=dados_perfil["display_name"] or dados_perfil["username"])
        novo_status_perfil = st.text_input("Status atual", value=dados_perfil["status_atual"] or "", placeholder="Ex: Estudando Cardiologia")
        salvar_perfil = st.form_submit_button("💾 Salvar perfil")

    if salvar_perfil:
        foto_base64 = dados_perfil["foto_perfil"]
        if nova_foto is not None:
            try:
                from PIL import Image
                img = Image.open(nova_foto).convert("RGB")
                img.thumbnail((300, 300))
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=80)
                foto_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
            except ImportError:
                # Sem Pillow instalado: guarda a imagem original em base64 (sem redimensionar)
                foto_base64 = base64.b64encode(nova_foto.read()).decode("utf-8")
        run_query(
            "UPDATE users SET display_name = ?, status_atual = ?, foto_perfil = ? WHERE id = ?",
            (novo_display_name.strip(), novo_status_perfil.strip(), foto_base64, USER_ID),
        )
        st.success("Perfil atualizado!")
        st.rerun()

# =============================================================================
# PÁGINA - RANKING / LEADERBOARD
# =============================================================================
elif pagina == "🏆 Ranking":
    st.title("🏆 Ranking")
    st.caption("Os usuários com mais XP e maior ofensiva da plataforma.")

    ranking_df = df_query(
        """SELECT username, display_name, foto_perfil, xp, nivel, streak FROM users
           WHERE is_active = TRUE ORDER BY xp DESC, streak DESC LIMIT 50"""
    )
    if ranking_df.empty:
        st.info("Ainda não há usuários suficientes para exibir o ranking.")
    else:
        for posicao, (_, u) in enumerate(ranking_df.iterrows(), start=1):
            nome_exibicao = u["display_name"] or u["username"]
            medalha = {1: "🥇", 2: "🥈", 3: "🥉"}.get(posicao, f"#{posicao}")
            col_pos, col_foto_r, col_info = st.columns([0.6, 0.8, 4])
            col_pos.markdown(f"### {medalha}")
            with col_foto_r:
                if u["foto_perfil"]:
                    st.markdown(
                        f"""<img src="data:image/jpeg;base64,{u['foto_perfil']}"
                                style="width:44px;height:44px;border-radius:50%;object-fit:cover;" />""",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown("🙂")
            col_info.markdown(
                f"**{nome_exibicao}** · Nível {u['nivel']} · {u['xp']} XP · 🔥 {u['streak']} dia(s)"
            )

# =============================================================================
# PÁGINA - PAINEL ADMIN
# =============================================================================
elif pagina == "🛡️ Painel Admin":
    if not st.session_state.get("is_admin"):
        st.error("Acesso restrito a administradores.")
        st.stop()

    st.title("🛡️ Painel de Administração")

    usuarios_df = df_query(
        """SELECT id, username, display_name, created_at, is_admin, is_active, xp, nivel
           FROM users ORDER BY id ASC"""
    )
    st.subheader("👥 Usuários cadastrados")
    st.dataframe(
        usuarios_df.rename(columns={
            "id": "ID", "username": "Usuário", "display_name": "Nome de exibição",
            "created_at": "Cadastrado em", "is_admin": "Admin?", "is_active": "Ativo?",
            "xp": "XP", "nivel": "Nível",
        }),
        use_container_width=True, hide_index=True,
    )

    st.divider()
    st.subheader("⚙️ Gerenciar conta por ID")
    ids_usuarios = usuarios_df["id"].tolist()
    if ids_usuarios:
        id_selecionado = st.selectbox(
            "Selecione o usuário", ids_usuarios,
            format_func=lambda uid: f"#{uid} · {usuarios_df.loc[usuarios_df['id'] == uid, 'username'].values[0]}",
        )
        linha_admin = usuarios_df.loc[usuarios_df["id"] == id_selecionado].iloc[0]

        colA1, colA2, colA3 = st.columns(3)
        if bool(linha_admin["is_active"]):
            if colA1.button("🚫 Suspender conta"):
                if int(id_selecionado) == USER_ID:
                    st.warning("Você não pode suspender a própria conta.")
                else:
                    run_query("UPDATE users SET is_active = FALSE WHERE id = ?", (int(id_selecionado),))
                    st.success("Conta suspensa.")
                    st.rerun()
        else:
            if colA1.button("✅ Reativar conta"):
                run_query("UPDATE users SET is_active = TRUE WHERE id = ?", (int(id_selecionado),))
                st.success("Conta reativada.")
                st.rerun()

        if bool(linha_admin["is_admin"]):
            if colA2.button("⬇️ Remover admin"):
                if int(id_selecionado) == USER_ID:
                    st.warning("Você não pode remover seu próprio acesso de admin.")
                else:
                    run_query("UPDATE users SET is_admin = FALSE WHERE id = ?", (int(id_selecionado),))
                    st.success("Acesso de admin removido.")
                    st.rerun()
        else:
            if colA2.button("⬆️ Tornar admin"):
                run_query("UPDATE users SET is_admin = TRUE WHERE id = ?", (int(id_selecionado),))
                st.success("Usuário promovido a admin.")
                st.rerun()

        if colA3.button("🗑️ Excluir definitivamente", type="secondary"):
            st.session_state["confirmar_exclusao_usuario"] = int(id_selecionado)

        if st.session_state.get("confirmar_exclusao_usuario") == int(id_selecionado):
            st.error(f"Confirma a exclusão definitiva de **{linha_admin['username']}** e todos os seus dados?")
            colE1, colE2 = st.columns(2)
            if colE1.button("✅ Sim, excluir definitivamente"):
                if int(id_selecionado) == USER_ID:
                    st.warning("Você não pode excluir a própria conta enquanto estiver logado.")
                else:
                    run_query("DELETE FROM users WHERE id = ?", (int(id_selecionado),))
                    st.session_state.pop("confirmar_exclusao_usuario", None)
                    st.success("Usuário excluído.")
                    st.rerun()
            if colE2.button("❌ Cancelar"):
                st.session_state.pop("confirmar_exclusao_usuario", None)
                st.rerun()

# =============================================================================
# RODAPÉ
# =============================================================================
st.sidebar.divider()
st.sidebar.caption("CRONOMODY © 2026 — Estude com método, não com sorte.")
